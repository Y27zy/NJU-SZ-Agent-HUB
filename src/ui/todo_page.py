import streamlit as st

from src.llm.providers import LLMProviderError
from src.memory.working_memory import update_working_memory
from src.modules.todo_agent import (
    generate_today_plan,
    generate_week_plan,
    list_subtasks,
    list_todos,
    mark_subtask_done,
    mark_todo_done,
    parse_and_save_todos,
)


def _inject_todo_theme() -> None:
    st.markdown('<span class="todo-page-marker"></span>', unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        .stApp:has(.todo-page-marker) .block-container { max-width:1320px; }
        .stApp:has(.todo-page-marker) .st-key-todo_capture,
        .stApp:has(.todo-page-marker) .st-key-todo_planner,
        .stApp:has(.todo-page-marker) .st-key-todo_list {
            padding:22px; border:1px solid #e1e2e6; border-radius:6px; background:white;
        }
        .stApp:has(.todo-page-marker) .st-key-todo_capture { border-top:4px solid #5b2a86; }
        .stApp:has(.todo-page-marker) .st-key-todo_planner { border-top:4px solid #147d75; }
        .stApp:has(.todo-page-marker) .st-key-todo_list { margin-top:22px; }
        .stApp:has(.todo-page-marker) [class*="st-key-todo_item_"] {
            padding:13px 14px; border-top:1px solid #e7e8eb;
        }
        .stApp:has(.todo-page-marker) [class*="st-key-todo_item_"]:first-of-type { border-top:0; }
        .todo-stats { display:grid; grid-template-columns:repeat(3,1fr); margin:20px 0 24px; border:1px solid #e1e2e6; background:white; }
        .todo-stat { padding:14px 18px; border-right:1px solid #e1e2e6; }
        .todo-stat:last-child { border-right:0; }
        .todo-stat strong { display:block; margin-top:4px; color:#20232a; font-size:24px; }
        .todo-stat span { color:#686c75; font-size:12px; }
        .todo-meta { color:#777b84; font-size:13px; }
        .priority-high { color:#d95f45; font-weight:700; }
        .priority-medium { color:#5b2a86; font-weight:700; }
        .plan-placeholder { min-height:210px; display:grid; place-items:center; padding:24px; border:1px dashed #cfd1d7; color:#858993; text-align:center; }
        @media(max-width:800px){.todo-stats{grid-template-columns:1fr}.todo-stat{border-right:0;border-bottom:1px solid #e1e2e6}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_plan_result() -> None:
    result = st.session_state.get("todo_plan_result")
    if not result:
        st.markdown('<div class="plan-placeholder">选择“今日安排”或“本周规划”，计划会固定显示在这里。</div>', unsafe_allow_html=True)
        return
    st.markdown(f"#### {result['title']}")
    st.markdown(result["content"])
    if result.get("score") is not None:
        st.caption(f"方案评分：{result['score']} · {result.get('reason', '')}")
    candidates = result.get("candidates") or []
    if candidates:
        with st.expander("比较候选方案"):
            for index, candidate in enumerate(candidates, 1):
                st.markdown(f"**方案 {index}**")
                st.markdown(candidate)


def _render_todo_item(user_id: int, todo: dict) -> None:
    with st.container(key=f"todo_item_{todo['id']}"):
        title_col, meta_col, action_col = st.columns([6, 2.3, 1.2], vertical_alignment="center")
        title_col.markdown(f"**{todo['title']}**")
        deadline = todo["deadline"] or "无明确截止"
        priority = "高优先级" if todo["priority"] == "high" else "普通"
        priority_class = "priority-high" if todo["priority"] == "high" else "priority-medium"
        meta_col.markdown(f'<span class="todo-meta">{deadline} · <span class="{priority_class}">{priority}</span></span>', unsafe_allow_html=True)
        if todo["status"] == "done":
            action_col.caption("已完成")
        elif action_col.button("完成", key=f"done_{todo['id']}", use_container_width=True):
            mark_todo_done(user_id, todo["id"])
            st.rerun()

        subtasks = list_subtasks(user_id, todo["id"])
        if subtasks:
            finished = sum(item["status"] == "done" for item in subtasks)
            with st.expander(f"子任务 {finished}/{len(subtasks)}"):
                for subtask in subtasks:
                    sub_title, sub_action = st.columns([7, 1.4], vertical_alignment="center")
                    sub_title.write(subtask["title"])
                    if subtask["status"] == "done":
                        sub_action.caption("完成")
                    elif sub_action.button("完成", key=f"subtask_{subtask['id']}", use_container_width=True):
                        mark_subtask_done(user_id, subtask["id"])
                        st.rerun()


def render_todo_page(user_id: int) -> None:
    _inject_todo_theme()
    st.markdown('<div class="page-eyebrow">TASK DESK</div>', unsafe_allow_html=True)
    st.markdown("## 任务规划")
    st.caption("把一句自然语言待办拆成任务，再生成可执行的今日或本周安排。")

    todos = list_todos(user_id)
    open_todos = [todo for todo in todos if todo["status"] != "done"]
    high_priority = sum(todo["priority"] == "high" for todo in open_todos)
    done_count = len(todos) - len(open_todos)
    st.markdown(
        f'<div class="todo-stats"><div class="todo-stat"><span>未完成</span><strong>{len(open_todos)}</strong></div>'
        f'<div class="todo-stat"><span>高优先级</span><strong>{high_priority}</strong></div>'
        f'<div class="todo-stat"><span>已完成</span><strong>{done_count}</strong></div></div>',
        unsafe_allow_html=True,
    )

    capture, planner = st.columns([0.42, 0.58], gap="large")
    with capture:
        with st.container(key="todo_capture"):
            st.markdown("### 快速收集")
            text = st.text_area(
                "写下这周要做的事",
                placeholder="例如：周五交数据库作业，周日之前看完一篇 Agent 论文。",
                height=150,
                label_visibility="collapsed",
            )
            if st.button("拆解并加入任务", type="primary", use_container_width=True, disabled=not text.strip()):
                parsed = parse_and_save_todos(user_id, text)
                update_working_memory(
                    st.session_state,
                    current_task_type="todo_parse",
                    last_user_input=text,
                    last_agent_output=f"已解析 {len(parsed)} 个任务",
                )
                st.success(f"已加入 {len(parsed)} 个任务。")
                st.rerun()
            st.caption("日期和优先级会从语句中自动识别，仍可在任务清单中核对。")

    with planner:
        with st.container(key="todo_planner"):
            st.markdown("### 智能排程")
            today_col, week_col = st.columns(2)
            today_clicked = today_col.button("今日安排", use_container_width=True)
            week_clicked = week_col.button("本周规划", type="primary", use_container_width=True)
            if today_clicked or week_clicked:
                try:
                    if today_clicked:
                        content = generate_today_plan(user_id)
                        st.session_state.todo_plan_result = {"title": "今日安排", "content": content}
                    else:
                        result = generate_week_plan(user_id)
                        st.session_state.todo_plan_result = {
                            "title": "本周最佳方案",
                            "content": result["best"]["plan"],
                            "score": result["best"]["score"],
                            "reason": result["best"]["reason"],
                            "candidates": result["candidates"],
                        }
                    update_working_memory(
                        st.session_state,
                        current_task_type="todo_plan",
                        last_user_input="生成任务计划",
                        last_agent_output=st.session_state.todo_plan_result["content"][:500],
                    )
                except LLMProviderError as exc:
                    st.error(str(exc))
            _render_plan_result()

    with st.container(key="todo_list"):
        list_head, filter_col = st.columns([0.7, 0.3], vertical_alignment="center")
        list_head.markdown("### 任务清单")
        status_filter = filter_col.pills("状态", ["未完成", "全部", "已完成"], default="未完成", label_visibility="collapsed")
        visible = todos
        if status_filter == "未完成":
            visible = open_todos
        elif status_filter == "已完成":
            visible = [todo for todo in todos if todo["status"] == "done"]
        if visible:
            for todo in visible:
                _render_todo_item(user_id, todo)
        else:
            st.info("这个视图中还没有任务。")
