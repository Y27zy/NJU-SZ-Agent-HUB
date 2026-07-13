from __future__ import annotations

import json
import html
import uuid
from typing import Any

import streamlit as st

from src.agent.food_agent import FoodAgent, selected_result
from src.agent.food_data_agent import (
    approve_pending_record,
    ensure_weekly_food_refresh,
    food_data_status,
    ignore_pending_record,
    refresh_food_database,
)
from src.agent.food_models import FoodDataStore
from src.agent.food_tools import exclude_recommendation, save_user_food_preference
from src.llm.providers import LLMProviderError
from src.memory.working_memory import update_working_memory


STATE_DEFAULTS = {
    "last_food_request": "",
    "last_food_constraints": {},
    "last_food_mode": "",
    "last_recommendation_id": "",
    "excluded_recommendation_ids": [],
    "last_agent_run": None,
}


def _init_state() -> None:
    for key, value in STATE_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value.copy() if isinstance(value, (dict, list)) else value


def _inject_theme() -> None:
    st.markdown('<span class="food-page-marker"></span>', unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        .stApp:has(.food-page-marker) .block-container { max-width:var(--page-max); }
        .food-result-card { border:1px solid #d9dce3; border-left:4px solid #5b2a86; padding:22px 24px; background:#fff; }
        .food-result-kicker { color:#147d75; font-size:12px; font-weight:750; text-transform:uppercase; }
        .food-result-title { color:#17191f; font-size:24px; font-weight:760; margin:7px 0 4px; }
        .food-result-food { color:#5b2a86; font-size:18px; font-weight:700; }
        .food-result-meta { color:#656a75; margin-top:8px; }
        .food-result-reason { color:#7b7f88; font-size:13px; margin-top:10px; }
        .food-empty { border:1px dashed #cfd2da; padding:34px; text-align:center; color:#808590; }
        .stApp:has(.food-page-marker) [data-testid="stVerticalBlockBorderWrapper"] { border-radius:6px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _serialize_run(run, result: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "agent_name": run.agent_name, "task": run.task, "constraints": run.constraints,
        "plan": run.plan, "trace": run.trace, "answer": run.answer, "result": result,
    }


def _run_agent(user_id: int, request: str, constraints: dict[str, Any], *, reset_exclusions: bool) -> None:
    if reset_exclusions:
        st.session_state.excluded_recommendation_ids = []
    agent_constraints = {
        **constraints,
        "excluded_ids": st.session_state.excluded_recommendation_ids,
        "last_mode": st.session_state.last_food_mode,
        "last_recommendation_id": st.session_state.last_recommendation_id,
    }
    run = FoodAgent(user_id).handle_request(request, agent_constraints)
    result = selected_result(run)
    st.session_state.last_food_request = request
    st.session_state.last_food_constraints = constraints
    st.session_state.last_food_mode = (result or {}).get("result_type") or constraints.get("mode", "")
    st.session_state.last_agent_run = _serialize_run(run, result)
    if result:
        st.session_state.last_recommendation_id = result["record_id"]
    update_working_memory(
        st.session_state,
        current_task_type="food_agent",
        last_user_input=request,
        last_agent_output=run.answer[:500],
    )


def _render_result(user_id: int) -> None:
    saved = st.session_state.last_agent_run
    if not saved:
        st.markdown('<div class="food-empty">你的下一顿，会在这里变成一个明确答案。</div>', unsafe_allow_html=True)
        return
    result = saved.get("result")
    if not result:
        st.info(saved.get("answer") or "当前没有可展示的结果。")
        return
    meta = " · ".join(value for value in (result.get("price_text"), result.get("distance_text")) if value)
    safe = {key: html.escape(str(result.get(key) or "")) for key in ("title", "food_name", "reason")}
    meta = html.escape(meta)
    st.markdown(
        f"""<div class="food-result-card">
        <div class="food-result-kicker">FoodAgent 决定</div>
        <div class="food-result-title">{safe['title']}</div>
        <div class="food-result-food">{safe['food_name']}</div>
        <div class="food-result-meta">{meta}</div>
        <div class="food-result-reason">{safe['reason']}</div>
        </div>""",
        unsafe_allow_html=True,
    )
    change, reject, remember = st.columns(3)
    if change.button("换一个", use_container_width=True):
        exclusion = exclude_recommendation(result["record_id"], st.session_state.excluded_recommendation_ids)
        st.session_state.excluded_recommendation_ids = exclusion["excluded_ids"]
        try:
            _run_agent(user_id, "换一个", st.session_state.last_food_constraints, reset_exclusions=False)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if reject.button("这个不想吃", use_container_width=True):
        exclusion = exclude_recommendation(result["record_id"], st.session_state.excluded_recommendation_ids)
        st.session_state.excluded_recommendation_ids = exclusion["excluded_ids"]
        st.toast("本次会话不会再推荐它。")
    if remember.button("记住我的偏好", use_container_width=True):
        st.session_state.show_food_preference = True
    if st.session_state.get("show_food_preference"):
        with st.form("food_preference_form"):
            preference = st.text_input("告诉 Agent 要长期记住什么", placeholder="例如：我不吃香菜；我更喜欢面食。")
            submitted = st.form_submit_button("保存偏好", type="primary")
        if submitted and preference.strip():
            save_user_food_preference(user_id, preference)
            st.session_state.show_food_preference = False
            st.success("偏好已保存。")


def _maintenance_area(user_id: int) -> None:
    store = FoodDataStore()
    data = store.load()
    with st.expander("数据维护（开发）"):
        st.caption(f"正式数据文件：`{store.path}`。人工记录建议设置 `origin=manual`、`locked=true`。")
        tabs = st.tabs(["食堂菜品", "附近餐厅", "外卖", "待审核", "手动新增"])
        for tab, key in zip(tabs[:3], ("canteen_dishes", "restaurants", "takeaways")):
            with tab:
                records = data.get(key) or []
                if records:
                    st.dataframe(records, use_container_width=True, hide_index=True)
                    disabled_id = st.selectbox("选择要启用/禁用的记录", [item["id"] for item in records], key=f"toggle_{key}")
                    if st.button("切换启用状态", key=f"toggle_button_{key}"):
                        for item in records:
                            if item["id"] == disabled_id:
                                item["enabled"] = not item.get("enabled", True)
                        store.replace_collection(key, records)
                        st.rerun()
                else:
                    st.caption("暂无已审核记录。")
        with tabs[3]:
            pending = [item for item in data.get("pending_review") or [] if item.get("status") == "pending"]
            if pending:
                st.dataframe(pending, use_container_width=True, hide_index=True)
                selected = st.selectbox("选择待审核线索", [item["id"] for item in pending], format_func=lambda value: next(item["name"] for item in pending if item["id"] == value))
                review_food = st.text_input("审核后的推荐菜（批准前必填）")
                review_area = st.text_input("区域")
                review_price = st.number_input("审核后人均价格", min_value=0.0, value=0.0, step=1.0)
                left, right = st.columns(2)
                if left.button("批准为餐厅", use_container_width=True, disabled=not review_food.strip() or review_price <= 0):
                    clue = next(item for item in pending if item["id"] == selected)
                    approve_pending_record(selected, "restaurants", {
                        "id": f"restaurant_{uuid.uuid4().hex[:10]}", "name": clue["name"], "area": review_area, "recommended_food": review_food,
                        "avg_price": review_price, "distance_minutes": None, "tastes": [], "categories": [], "suitable_for": [],
                        "weight": 1, "notes": f"来源：{clue.get('source_url', '')}",
                    })
                    st.rerun()
                if right.button("忽略线索", use_container_width=True):
                    ignore_pending_record(selected)
                    st.rerun()
            else:
                st.caption("暂无待审核线索。")
        with tabs[4]:
            kind = st.selectbox("记录类型", ["食堂菜品", "附近餐厅", "外卖"])
            with st.form("manual_food_record"):
                name = st.text_input("食堂/餐厅/外卖店名称")
                food = st.text_input("具体菜品或推荐菜")
                location = st.text_input("楼层与窗口 / 区域")
                price = st.number_input("价格或人均", min_value=0.0, value=0.0, step=1.0)
                submitted = st.form_submit_button("加入正式数据", type="primary")
            if submitted and name.strip() and food.strip():
                if kind == "食堂菜品":
                    key, record = "canteen_dishes", {"id": f"canteen_{uuid.uuid4().hex[:10]}", "venue": name, "floor": "", "window": location, "food_name": food, "meal_times": [], "tastes": [], "category": "其他", "price": price or None}
                elif kind == "附近餐厅":
                    key, record = "restaurants", {"id": f"restaurant_{uuid.uuid4().hex[:10]}", "name": name, "area": location, "recommended_food": food, "avg_price": price or None, "distance_minutes": None, "tastes": [], "categories": [], "suitable_for": []}
                else:
                    key, record = "takeaways", {"id": f"takeaway_{uuid.uuid4().hex[:10]}", "restaurant": name, "food_name": food, "platforms": [], "avg_price": price or None, "delivery_minutes": None, "meal_times": [], "tastes": [], "category": "其他"}
                store.replace_collection(key, [*(data.get(key) or []), {**record, "weight": 1, "enabled": True, "origin": "manual", "locked": True, "notes": ""}])
                st.rerun()
        if st.button("手动触发联网发现"):
            try:
                with st.spinner("正在搜索公开线索，只会写入待审核区..."):
                    refresh_food_database(user_id, force=True)
                st.success("发现任务完成。")
            except Exception as exc:
                st.error(f"联网发现失败，本地正式数据未受影响：{exc}")


def render_food_page(user_id: int) -> None:
    """Render the compact unified FoodAgent experience."""
    _init_state()
    _inject_theme()
    ensure_weekly_food_refresh(user_id)
    st.markdown('<div class="page-eyebrow">CAMPUS FOOD</div>', unsafe_allow_html=True)
    st.markdown("## 今天吃什么")
    st.caption("告诉 Agent 你的要求，或者直接使用筛选条件，让它替你做决定。")

    natural_column, quick_column = st.columns(2, gap="large")
    with natural_column:
        with st.container(border=True):
            st.markdown("### 描述你的需求")
            st.caption("用一句话说明场景、预算和偏好，FoodAgent 会选择正确的本地工具。")
            with st.form("food_natural_request"):
                request = st.text_area(
                    "你想吃什么？",
                    placeholder="今晚我想和女朋友去学校附近吃饭，预算 100\n午饭想在食堂吃，二十块以内，不要辣\n不想出门，帮我选个外卖",
                    height=176,
                )
                natural_submit = st.form_submit_button("帮我决定", type="primary", use_container_width=True)
            if natural_submit and request.strip():
                try:
                    with st.spinner("FoodAgent 正在调用本地选择工具..."):
                        _run_agent(user_id, request, {}, reset_exclusions=True)
                except (LLMProviderError, ValueError, json.JSONDecodeError) as exc:
                    st.error(f"自然语言理解暂不可用：{exc}。你仍可使用右侧快捷筛选。")

    with quick_column:
        with st.container(border=True):
            st.markdown("### 快捷筛选")
            st.caption("不需要模型。直接按条件从已审核数据中随机选择。")
            mode = st.segmented_control("用餐方式", ["随机", "校内食堂", "附近堂食", "外卖"], default="随机")
            meal, taste = st.columns(2)
            meal_time = meal.selectbox("餐次", ["随机", "早餐", "午餐", "晚餐"])
            taste_value = taste.selectbox("口味", ["随便", "清淡", "想吃辣", "不吃辣"])
            category_value = st.selectbox("品类", ["随机", "米饭", "面食", "粉", "小吃", "轻食", "其他"])
            budget, people = st.columns(2)
            budget_value = budget.number_input("预算（元）", min_value=0, value=30, step=5)
            group_size = people.number_input("人数（堂食）", min_value=1, value=1, step=1)
            distance_choice = st.selectbox("距离偏好（堂食）", ["不限", "骑行 5 分钟内", "骑行 10 分钟内", "骑行 20 分钟内"])
            if st.button("就吃这个", type="primary", use_container_width=True):
                mode_map = {"随机": "canteen", "校内食堂": "canteen", "附近堂食": "restaurant", "外卖": "takeaway"}
                constraints = {
                    "mode": mode_map[mode or "随机"], "meal_time": meal_time, "budget": budget_value,
                    "taste": taste_value, "category": category_value, "group_size": group_size,
                    "max_distance_minutes": {"不限": None, "骑行 5 分钟内": 5, "骑行 10 分钟内": 10, "骑行 20 分钟内": 20}[distance_choice],
                }
                _run_agent(user_id, "快捷筛选", constraints, reset_exclusions=True)

    st.markdown("### 这顿就吃")
    _render_result(user_id)

    with st.expander("查看数据状态"):
        status = food_data_status()
        st.json(status, expanded=False)
        if status.get("error"):
            st.warning(status["error"])
    with st.expander("查看 Agent 工具调用"):
        if st.session_state.last_agent_run:
            st.json(st.session_state.last_agent_run.get("trace") or [], expanded=False)
        else:
            st.caption("尚无工具调用。")
    _maintenance_area(user_id)
