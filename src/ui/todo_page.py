from datetime import datetime

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


SORT_OPTIONS = {
    "智能排序": "smart",
    "截止日期": "deadline",
    "优先级": "priority",
    "创建时间": "created",
    "完成时间": "completed",
}


def _inject_todo_theme() -> None:
    st.markdown('<span class="todo-page-marker"></span>', unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        .stApp:has(.todo-page-marker) .block-container{max-width:var(--page-max);padding-bottom:80px}
        .todo-hero{padding:26px 0 18px;border-bottom:1px solid #e4e6eb}.todo-kicker{color:#147d75;font-size:12px;font-weight:750;letter-spacing:.12em}
        .todo-hero h2{margin:7px 0 5px;font-size:34px}.todo-hero p{margin:0;color:#747983}
        .todo-summary{display:grid;grid-template-columns:repeat(3,1fr);margin:18px 0;border-top:1px solid #e1e3e8;border-bottom:1px solid #e1e3e8}
        .todo-summary div{padding:14px 18px;border-right:1px solid #e1e3e8}.todo-summary div:last-child{border-right:0}.todo-summary span{display:block;color:#797e88;font-size:12px}.todo-summary strong{display:block;margin-top:3px;font-size:22px}
        .stApp:has(.todo-page-marker) .st-key-todo_quick_add{padding:18px 20px;border:1px solid #dfe2e8;border-left:4px solid #5b2a86;background:#fff}
        .stApp:has(.todo-page-marker) .st-key-todo_quick_add button:disabled{border-color:#d8dbe1!important;background:#eef0f3!important;color:#9297a0!important;opacity:1!important}
        .stApp:has(.todo-page-marker) .st-key-todo_task_list{margin-top:18px;border-top:1px solid #dfe2e8}
        .stApp:has(.todo-page-marker) [class*="st-key-todo_item_"]{padding:13px 4px 11px;border-bottom:1px solid #e7e9ed;background:#fff}
        .stApp:has(.todo-page-marker) [class*="st-key-todo_steps_"]{margin:7px 0 2px 42px;padding:8px 12px;border-left:2px solid #d7c7e5;background:#faf8fc}
        .todo-title{font-size:16px;font-weight:650;color:#20232a}.todo-title.is-done{text-decoration:line-through;color:#8a8f98}
        .todo-meta{margin-top:3px;color:#777d87;font-size:12px}.todo-priority{color:#d95f45;font-weight:700}.todo-normal{color:#5b2a86;font-weight:650}
        .todo-step-done{text-decoration:line-through;color:#9297a0}.plan-placeholder{min-height:150px;display:grid;place-items:center;border:1px dashed #cfd3da;color:#858b95;text-align:center}
        @media(max-width:760px){.todo-summary{grid-template-columns:1fr}.todo-summary div{border-right:0;border-bottom:1px solid #e1e3e8}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_plan_result() -> None:
    result = st.session_state.get("todo_plan_result")
    if not result:
        st.markdown('<div class="plan-placeholder">选择今日安排或本周规划后，Agent 会把执行方案固定在这里。</div>', unsafe_allow_html=True)
        return
    st.markdown(f"#### {result['title']}")
    st.markdown(result["content"])
    if result.get("score") is not None:
        st.caption(f"方案评分：{result['score']} · {result.get('reason', '')}")
    if result.get("trace"):
        with st.expander("Agent 工具轨迹"):
            st.json(result["trace"], expanded=False)


def _render_todo_item(user_id: int, todo: dict) -> None:
    subtasks = list_subtasks(user_id, todo["id"])
    state_key = f"todo_steps_open_{todo['id']}"
    with st.container(key=f"todo_item_{todo['id']}"):
        done = todo["status"] == "done"
        complete_col, content_col, priority_col = st.columns([0.55, 8.2, 1.25], vertical_alignment="center")
        if done:
            complete_col.button("✓", key=f"todo_done_view_{todo['id']}", disabled=True, help="已完成")
        elif complete_col.button("○", key=f"todo_done_{todo['id']}", help="标记任务完成"):
            mark_todo_done(user_id, todo["id"])
            st.rerun()
        title_class = "todo-title is-done" if done else "todo-title"
        deadline = todo.get("deadline") or "无截止日期"
        content_col.markdown(
            f'<div class="{title_class}">{todo["title"]}</div><div class="todo-meta">{deadline}</div>',
            unsafe_allow_html=True,
        )
        priority_col.markdown(
            '<span class="todo-priority">★ 重要</span>' if todo["priority"] == "high" else '<span class="todo-normal">普通</span>',
            unsafe_allow_html=True,
        )

        if subtasks:
            finished = sum(item["status"] == "done" for item in subtasks)
            is_open = bool(st.session_state.get(state_key, False))
            if st.button(
                f"{'▾' if is_open else '›'} {finished}/{len(subtasks)} 个步骤",
                key=f"todo_steps_toggle_{todo['id']}",
                type="tertiary",
            ):
                st.session_state[state_key] = not is_open
                st.rerun()
            if st.session_state.get(state_key, False):
                with st.container(key=f"todo_steps_{todo['id']}"):
                    for index, subtask in enumerate(subtasks, 1):
                        step_col, step_action = st.columns([8, 1.3], vertical_alignment="center")
                        if subtask["status"] == "done":
                            step_col.markdown(f'<span class="todo-step-done">{index}. {subtask["title"]}</span>', unsafe_allow_html=True)
                            step_action.caption("已完成")
                        else:
                            step_col.write(f"{index}. {subtask['title']}")
                            if step_action.button("完成", key=f"subtask_{subtask['id']}", use_container_width=True):
                                st.session_state[state_key] = True
                                mark_subtask_done(user_id, subtask["id"])
                                st.rerun()


def _visible_todos(todos: list[dict], view: str) -> list[dict]:
    if view == "重要":
        return [item for item in todos if item["status"] != "done" and item["priority"] == "high"]
    if view == "已完成":
        return [item for item in todos if item["status"] == "done"]
    if view == "全部":
        return todos
    return [item for item in todos if item["status"] != "done"][:8]


def render_todo_page(user_id: int) -> None:
    _inject_todo_theme()
    initial = list_todos(user_id)
    open_todos = [item for item in initial if item["status"] != "done"]
    high_priority = sum(item["priority"] == "high" for item in open_todos)
    done_count = len(initial) - len(open_todos)
    today_label = datetime.now().strftime("%Y 年 %m 月 %d 日")
    st.markdown(
        f'<div class="todo-hero"><div class="todo-kicker">MY DAY · NJU-SZ</div><h2>我的一天</h2><p>{today_label}，先完成最重要的一步。</p></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="todo-summary"><div><span>待完成</span><strong>{len(open_todos)}</strong></div>'
        f'<div><span>重要任务</span><strong>{high_priority}</strong></div><div><span>已完成</span><strong>{done_count}</strong></div></div>',
        unsafe_allow_html=True,
    )

    with st.container(key="todo_quick_add"):
        st.markdown("### 添加任务")
        text = st.text_area(
            "自然语言任务",
            placeholder="例如：周五提交数据库作业；周日前读完 Agent 论文并准备 5 分钟汇报。",
            height=92,
            label_visibility="collapsed",
        )
        hint_col, add_col = st.columns([0.74, 0.26], vertical_alignment="center")
        hint_col.caption("Agent 会识别独立成果、截止时间与依赖，并生成按顺序执行的步骤。")
        if add_col.button("让 Agent 拆解", type="primary", use_container_width=True):
            if not text.strip():
                st.warning("请先输入需要拆解的任务。")
            else:
                try:
                    parsed = parse_and_save_todos(user_id, text)
                    update_working_memory(st.session_state, current_task_type="todo_parse", last_user_input=text, last_agent_output=f"已解析 {len(parsed)} 个任务")
                    st.toast(f"已加入 {len(parsed)} 个不重复任务。")
                    st.rerun()
                except (LLMProviderError, ValueError) as exc:
                    st.error(str(exc))

    with st.expander("智能规划", expanded=False):
        action_col, result_col = st.columns([0.3, 0.7], gap="large")
        with action_col:
            st.markdown("#### 生成执行方案")
            today_clicked = st.button("今日安排", use_container_width=True)
            week_clicked = st.button("本周规划", type="primary", use_container_width=True)
            if today_clicked or week_clicked:
                try:
                    if today_clicked:
                        content = generate_today_plan(user_id)
                        st.session_state.todo_plan_result = {"title": "今日安排", "content": content}
                    else:
                        result = generate_week_plan(user_id)
                        st.session_state.todo_plan_result = {
                            "title": "本周最佳方案", "content": result["best"]["plan"], "score": result["best"]["score"],
                            "reason": result["best"]["reason"], "trace": result.get("trace"),
                        }
                except LLMProviderError as exc:
                    st.error(str(exc))
        with result_col:
            _render_plan_result()

    toolbar_left, toolbar_right = st.columns([0.7, 0.3], vertical_alignment="center")
    view = toolbar_left.pills("任务视图", ["我的一天", "重要", "全部", "已完成"], default="我的一天", label_visibility="collapsed")
    sort_label = toolbar_right.selectbox("排序", list(SORT_OPTIONS), label_visibility="collapsed")
    todos = list_todos(user_id, sort_by=SORT_OPTIONS[sort_label])
    visible = _visible_todos(todos, view)
    with st.container(key="todo_task_list"):
        if visible:
            for todo in visible:
                _render_todo_item(user_id, todo)
        else:
            st.info("这个视图中没有任务。")
