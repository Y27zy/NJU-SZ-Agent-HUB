from src.agent.thought_tree import dynamic_thought_tree
from src.llm.base import BaseLLMProvider


def plan_complex_task(task: str, context: str, llm: BaseLLMProvider) -> dict:
    return dynamic_thought_tree(task, context, llm)
