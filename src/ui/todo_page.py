import streamlit as st

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


def render_todo_page(user_id: int) -> None:
    text = st.text_area(
        "自然语言输入 Todo",
        value="我这周要复习机器学习第 3-6 章，周五交数据库作业，周日之前看完一篇 Agent 论文。",
    )
    if st.button("解析并保存", type="primary") and text:
        todos = parse_and_save_todos(user_id, text)
        update_working_memory(st.session_state, current_task_type="todo_parse", last_user_input=text, last_agent_output=f"已解析 {len(todos)} 个任务")
        st.success(f"已保存 {len(todos)} 个任务。")

    st.subheader("当前 Todo-list")
    todos = list_todos(user_id)
    for todo in todos:
        cols = st.columns([5, 2, 2, 1])
        cols[0].write(f"{todo['title']}")
        cols[1].write(todo["deadline"] or "无截止")
        cols[2].write(f"{todo['priority']} / {todo['status']}")
        if todo["status"] != "done" and cols[3].button("完成", key=f"done_{todo['id']}"):
            mark_todo_done(user_id, todo["id"])
            st.rerun()
        subtasks = list_subtasks(user_id, todo["id"])
        if subtasks:
            with st.expander(f"子任务：{todo['title']}", expanded=False):
                for subtask in subtasks:
                    sub_cols = st.columns([6, 2, 1])
                    sub_cols[0].write(subtask["title"])
                    sub_cols[1].write(subtask["status"])
                    if subtask["status"] != "done" and sub_cols[2].button("完成", key=f"subtask_{subtask['id']}"):
                        mark_subtask_done(user_id, subtask["id"])
                        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("生成今日计划"):
            result = generate_today_plan(user_id)
            update_working_memory(st.session_state, current_task_type="todo_today_plan", last_user_input="生成今日计划", last_agent_output=result[:500])
            st.write(result)
    with col2:
        if st.button("生成本周计划 Dynamic Thought Tree"):
            result = generate_week_plan(user_id)
            update_working_memory(st.session_state, current_task_type="todo_week_plan", last_user_input="生成本周计划", last_agent_output=result["best"]["plan"][:500])
            st.write("最佳方案")
            st.write(result["best"]["plan"])
            st.caption(f"评分：{result['best']['score']}；{result['best']['reason']}")
            with st.expander("查看候选方案"):
                for idx, plan in enumerate(result["candidates"], 1):
                    st.markdown(f"**候选方案 {idx}**")
                    st.write(plan)
