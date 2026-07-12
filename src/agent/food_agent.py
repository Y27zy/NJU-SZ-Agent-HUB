from __future__ import annotations

import json
import re
from typing import Any, Callable

from src.agent.food_data_agent import search_new_food_places
from src.agent.food_models import FoodDataStore
from src.agent.food_tools import (
    PreferenceReader,
    choose_canteen_food,
    choose_nearby_restaurant,
    choose_takeaway,
    exclude_recommendation,
    save_user_food_preference,
)
from src.agent.runtime import AgentRun, record_agent_run
from src.llm.gateway import chat_with_user_model


FOOD_AGENT_SYSTEM_PROMPT = """你是 NJU-SZ Agent Hub 的 FoodAgent 总控，只理解需求和选择工具。
你绝不能自行生成餐厅、食堂、窗口、菜品、价格、距离、平台或营业时间；具体推荐必须来自 Python 选择工具。
意图映射：校内/食堂/窗口/在学校吃 -> choose_canteen_food；附近餐厅/出去吃/堂食/聚餐 -> choose_nearby_restaurant；外卖/不想出去/送到宿舍/配送 -> choose_takeaway。
换一个/不想吃这个 -> exclude_recommendation 后重复上次选择工具；以后不要推荐/我不吃/我喜欢 -> save_user_food_preference；新店/联网查 -> search_new_food_places。
只输出 JSON，字段为 mode、meal_time、budget、taste、category、max_distance_minutes、group_size、action、preference。不得输出推荐对象。"""


IntentParser = Callable[[str], dict[str, Any]]


class FoodAgent:
    """Route food requests to auditable Python tools and format one result."""

    def __init__(
        self,
        user_id: int,
        *,
        store: FoodDataStore | None = None,
        intent_parser: IntentParser | None = None,
        preference_reader: PreferenceReader | None = None,
        persist_runs: bool = True,
    ):
        self.user_id = user_id
        self.store = store or FoodDataStore()
        self.intent_parser = intent_parser
        self.preference_reader = preference_reader
        self.persist_runs = persist_runs

    def handle_request(self, user_request: str, ui_constraints: dict | None = None) -> AgentRun:
        """Understand a request, call one allowed Python tool, and return a concise AgentRun."""
        request = user_request.strip()
        constraints = dict(ui_constraints or {})
        parsed = self._understand(request, constraints)
        merged = {**parsed, **{key: value for key, value in constraints.items() if value not in (None, "")}}
        action = merged.get("action") or "recommend"
        plan = {"goal": "给出一个来自已审核数据的明确选择", "reasoning": "按意图选择受控 Python 工具", "tool_calls": []}
        trace: list[dict[str, Any]] = []

        if action == "save_preference":
            output = save_user_food_preference(self.user_id, merged.get("preference") or request)
            plan["tool_calls"] = [{"tool": "save_user_food_preference", "args": {"content": output.get("preference", request)}}]
            trace.append({"tool": "save_user_food_preference", "args": plan["tool_calls"][0]["args"], "ok": output["success"], "output": output})
            answer = "已记住这条饮食偏好。" if output["success"] else output["message"]
            return self._finish(request, merged, plan, trace, answer)

        if action == "search":
            output = search_new_food_places(self.user_id, request, store=self.store)
            plan["tool_calls"] = [{"tool": "search_new_food_places", "args": {"query": request}}]
            trace.append({"tool": "search_new_food_places", "args": {"query": request}, "ok": output["success"], "output": output})
            answer = f"联网发现了 {output['pending_added']} 条新线索，已放入待审核区，不会直接参与推荐。"
            return self._finish(request, merged, plan, trace, answer)

        excluded = list(merged.get("excluded_ids") or [])
        if action == "change" and merged.get("last_recommendation_id"):
            exclusion = exclude_recommendation(merged["last_recommendation_id"], excluded)
            excluded = exclusion["excluded_ids"]
            plan["tool_calls"].append({"tool": "exclude_recommendation", "args": {"record_id": merged["last_recommendation_id"]}})
            trace.append({"tool": "exclude_recommendation", "args": plan["tool_calls"][-1]["args"], "ok": True, "output": exclusion})

        mode = self._resolve_mode(request, merged)
        if not mode:
            answer = "你想在校内食堂吃、出去堂食，还是点外卖？"
            return self._finish(request, merged, plan, trace, answer, status="needs_clarification")

        tool_name, tool_args = self._tool_call(mode, merged, excluded)
        plan["tool_calls"].append({"tool": tool_name, "args": tool_args})
        try:
            output = self._execute_tool(tool_name, tool_args)
            trace.append({"tool": tool_name, "args": tool_args, "ok": True, "output": output})
        except Exception as exc:
            trace.append({"tool": tool_name, "args": tool_args, "ok": False, "error": str(exc)[:500]})
            return self._finish(request, merged, plan, trace, "选择工具执行失败，请稍后重试。", status="failed")

        if not output.get("success"):
            return self._finish(request, merged, plan, trace, output.get("message", "当前没有符合条件的已审核记录。"), status="no_match")
        return self._finish(request, merged, plan, trace, self._format_result(output))

    def _understand(self, request: str, ui: dict[str, Any]) -> dict[str, Any]:
        deterministic = self._parse_rules(request)
        if ui.get("mode") not in (None, "", "随机") or deterministic.get("action") != "recommend" or deterministic.get("mode"):
            return deterministic
        parser = self.intent_parser or self._parse_with_llm
        parsed = parser(request)
        return {**deterministic, **{key: value for key, value in parsed.items() if value not in (None, "")}}

    def _parse_with_llm(self, request: str) -> dict[str, Any]:
        response = chat_with_user_model(
            self.user_id,
            FOOD_AGENT_SYSTEM_PROMPT,
            f"用户请求：{request}\n只提取约束和工具意图，不得推荐任何具体对象。",
            temperature=0.0,
        )
        match = re.search(r"\{.*\}", response, flags=re.DOTALL)
        if not match:
            raise ValueError("模型没有返回可解析的 FoodAgent 意图。")
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _parse_rules(request: str) -> dict[str, Any]:
        result: dict[str, Any] = {"action": "recommend"}
        if any(word in request for word in ("换一个", "不想吃这个", "换一家")):
            result["action"] = "change"
        elif any(word in request for word in ("以后不要", "以后别", "我不吃", "我喜欢", "我通常")):
            result.update(action="save_preference", preference=request)
        elif any(word in request for word in ("新开", "新店", "联网查", "上网查")):
            result["action"] = "search"
        if any(word in request for word in ("外卖", "配送", "送到宿舍", "不想出门", "不想出去")):
            result["mode"] = "takeaway"
        elif any(word in request for word in ("附近", "周边", "学校旁", "出去吃", "堂食", "聚餐", "出校门")):
            result["mode"] = "restaurant"
        elif any(word in request for word in ("校内", "食堂", "窗口", "在学校吃")):
            result["mode"] = "canteen"
        for meal in ("早餐", "午餐", "晚餐"):
            if meal in request or {"早餐": "早饭", "午餐": "午饭", "晚餐": "晚饭"}[meal] in request:
                result["meal_time"] = meal
        budget = re.search(r"(?:人均|预算|以内|不超过|左右)[^\d]{0,6}(\d{1,3})|(?:\d{1,3})\s*块", request)
        if budget:
            number = budget.group(1) or re.search(r"\d{1,3}", budget.group(0)).group(0)
            result["budget"] = int(number)
        group = re.search(r"(\d+)\s*个人|([一二三四五六七八九十两]+)个人", request)
        if group:
            chinese = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6}
            result["group_size"] = int(group.group(1)) if group.group(1) else chinese.get(group.group(2), 2)
        elif any(word in request for word in ("女朋友", "男朋友", "对象", "朋友", "同学", "一起")):
            result["group_size"] = 2
        if "不辣" in request or "不吃辣" in request or "不要辣" in request:
            result["taste"] = "不吃辣"
        elif "辣" in request:
            result["taste"] = "想吃辣"
        elif "清淡" in request:
            result["taste"] = "清淡"
        for category in ("米饭", "面食", "粉", "小吃", "轻食"):
            if category in request:
                result["category"] = category
        return result

    @staticmethod
    def _resolve_mode(request: str, constraints: dict[str, Any]) -> str | None:
        mode = constraints.get("mode") or constraints.get("last_mode")
        if mode in {"canteen", "restaurant", "takeaway"}:
            return mode
        if mode == "随机":
            return "canteen"
        return FoodAgent._parse_rules(request).get("mode")

    def _tool_call(self, mode: str, values: dict[str, Any], excluded: list[str]) -> tuple[str, dict[str, Any]]:
        common = {"user_id": self.user_id, "excluded_ids": excluded}
        if mode == "canteen":
            return "choose_canteen_food", {**common, "meal_time": values.get("meal_time"), "budget": values.get("budget"), "taste": values.get("taste"), "category": values.get("category")}
        if mode == "restaurant":
            return "choose_nearby_restaurant", {**common, "budget_per_person": values.get("budget_per_person") or values.get("budget"), "taste": values.get("taste"), "category": values.get("category"), "max_distance_minutes": values.get("max_distance_minutes"), "group_size": values.get("group_size")}
        return "choose_takeaway", {**common, "budget": values.get("budget"), "taste": values.get("taste"), "category": values.get("category"), "meal_time": values.get("meal_time")}

    def _execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tools = {
            "choose_canteen_food": choose_canteen_food,
            "choose_nearby_restaurant": choose_nearby_restaurant,
            "choose_takeaway": choose_takeaway,
        }
        if name not in tools:
            raise ValueError(f"未注册的 FoodAgent 工具：{name}")
        optional = {"preference_reader": self.preference_reader} if self.preference_reader else {}
        return tools[name](**args, store=self.store, **optional)

    @staticmethod
    def _format_result(result: dict[str, Any]) -> str:
        if result["result_type"] == "canteen":
            lead = f"今天吃：{result['title']}的{result['food_name']}"
        elif result["result_type"] == "restaurant":
            lead = f"今天去：{result['title']}，点{result['food_name']}"
        else:
            lead = f"今天点：{result['title']}的{result['food_name']}"
        details = "，".join(value for value in (result.get("price_text"), result.get("distance_text")) if value)
        return f"{lead}。{details}。" if details else f"{lead}。"

    def _finish(self, task: str, constraints: dict[str, Any], plan: dict[str, Any], trace: list[dict[str, Any]], answer: str, status: str = "completed") -> AgentRun:
        run = AgentRun("FoodAgent", task, constraints, plan, trace, answer)
        if self.persist_runs:
            record_agent_run(self.user_id, run, status)
        return run


def selected_result(run: AgentRun) -> dict[str, Any] | None:
    """Extract the approved Python selection result from an AgentRun."""
    for event in reversed(run.trace):
        output = event.get("output") or {}
        if event.get("tool", "").startswith("choose_") and output.get("success"):
            return output
    return None
