from src.llm.base import BaseLLMProvider
from src.llm.providers import MockLLMProvider


def generate_candidate_plans(task: str, context: str, n: int = 3, llm: BaseLLMProvider | None = None) -> list[str]:
    provider = llm or MockLLMProvider()
    candidates = []
    for i in range(n):
        prompt = (
            f"任务：{task}\n上下文：{context}\n"
            f"请生成第 {i + 1} 个候选计划，强调可执行性、优先级和时间安排。"
        )
        candidates.append(provider.chat([{"role": "user", "content": prompt}], temperature=0.8))
    return candidates


def evaluate_plan(plan: str, task: str, context: str) -> dict:
    score = 50
    keywords = ["截止", "优先", "复盘", "上午", "下午", "晚上", "子任务", "时间"]
    score += sum(6 for word in keywords if word in plan)
    score += min(len(plan) // 80, 20)
    if "最高优先级" in plan or "高优先级" in plan:
        score += 8
    return {"plan": plan, "score": min(score, 100), "reason": "根据可执行性、时间结构和优先级表达进行轻量评分。"}


def select_best_plan(candidates: list[str], task: str = "", context: str = "") -> dict:
    evaluated = [evaluate_plan(plan, task, context) for plan in candidates]
    return max(evaluated, key=lambda item: item["score"]) if evaluated else {"plan": "", "score": 0, "reason": "无候选方案"}


def dynamic_thought_tree(task: str, context: str, llm: BaseLLMProvider | None = None) -> dict:
    candidates = generate_candidate_plans(task, context, n=3, llm=llm)
    best = select_best_plan(candidates, task, context)
    return {"task": task, "candidates": candidates, "best": best}
