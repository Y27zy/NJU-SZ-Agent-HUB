import streamlit as st

from src.memory.working_memory import update_working_memory
from src.modules.food_agent import random_canteen_food, recommend_restaurants, save_food_preference


def render_food_page(user_id: int) -> None:
    tab1, tab2 = st.tabs(["校外餐厅推荐", "食堂随机吃什么"])

    with tab1:
        budget = st.slider("预算", min_value=15, max_value=120, value=40, step=5)
        taste = st.selectbox("口味", ["清淡", "辣", "米饭", "面食", "随便"])
        distance = st.selectbox("距离偏好", ["近一点", "都可以"])
        is_group = st.checkbox("是否聚餐")
        spicy = st.checkbox("想吃辣")
        light = st.checkbox("想吃清淡")
        if st.button("推荐校外餐厅"):
            recommendations = recommend_restaurants(budget, taste, distance, is_group, spicy, light)
            update_working_memory(
                st.session_state,
                current_task_type="food_restaurant",
                last_user_input=f"预算 {budget}，口味 {taste}，距离 {distance}",
                last_agent_output="; ".join(item["name"] for item in recommendations),
            )
            for item in recommendations:
                st.markdown(f"**{item['name']}** | {item['type']} | 人均 {item['avg_price']} | {item['distance']}")
                st.write(item["recommendation"])

    with tab2:
        meal_time = st.selectbox("餐次", ["早餐", "午餐", "晚餐", "随机"])
        taste2 = st.selectbox("想吃", ["清淡", "重口", "随便"])
        category = st.selectbox("类别", ["米饭", "面食", "小吃", "随机"])
        if st.button("随机推荐"):
            item = random_canteen_food(meal_time, taste2, category)
            update_working_memory(st.session_state, current_task_type="food_canteen", last_user_input=f"{meal_time}/{taste2}/{category}", last_agent_output=item["food_name"])
            st.success(f"{item['canteen']} - {item['window']}：{item['food_name']}")
            st.write(item["reason"])

    st.subheader("保存饮食偏好到记忆")
    pref = st.text_input("例如：我晚餐喜欢清淡一点，预算 30 元以内。")
    if st.button("保存饮食偏好") and pref:
        save_food_preference(user_id, pref)
        update_working_memory(st.session_state, current_task_type="food_memory", last_user_input=pref, last_agent_output="饮食偏好已保存")
        st.success("已保存到 User Memory。")
