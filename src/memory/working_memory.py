from typing import Any, MutableMapping


DEFAULT_WORKING_MEMORY = {
    "current_task_type": "",
    "current_document": "",
    "last_user_input": "",
    "last_agent_output": "",
}


def init_working_memory(session_state: MutableMapping[str, Any]) -> dict:
    if "working_memory" not in session_state:
        session_state["working_memory"] = DEFAULT_WORKING_MEMORY.copy()
    return session_state["working_memory"]


def update_working_memory(session_state: MutableMapping[str, Any], **kwargs: str) -> dict:
    memory = init_working_memory(session_state)
    for key, value in kwargs.items():
        if key in DEFAULT_WORKING_MEMORY:
            memory[key] = value
    session_state["working_memory"] = memory
    return memory


def format_working_memory(memory: dict) -> str:
    if not memory:
        return "暂无 Working Memory。"
    return "\n".join(f"- {key}: {value or '暂无'}" for key, value in memory.items())
