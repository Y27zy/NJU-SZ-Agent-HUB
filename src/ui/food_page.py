import html

import streamlit as st

from src.memory.working_memory import update_working_memory
from src.modules.food_agent import random_canteen_food, recommend_restaurants, save_food_preference


def _inject_food_theme() -> None:
    st.markdown('<span class="food-page-marker"></span>', unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        .stApp:has(.food-page-marker) .block-container { max-width:1320px; }
        .stApp:has(.food-page-marker) .st-key-restaurant_panel,
        .stApp:has(.food-page-marker) .st-key-canteen_panel {
            min-height:560px; padding:22px; border:1px solid #e1e2e6; border-radius:6px; background:white;
        }
        .stApp:has(.food-page-marker) .st-key-restaurant_panel { border-top:4px solid #5b2a86; }
        .stApp:has(.food-page-marker) .st-key-canteen_panel { border-top:4px solid #147d75; }
        .food-result-zone { min-height:180px; margin-top:18px; padding-top:16px; border-top:1px solid #e1e2e6; }
        .food-placeholder { min-height:150px; display:grid; place-items:center; color:#858993; text-align:center; }
        .restaurant-result { display:grid; grid-template-columns:1fr auto; gap:8px 16px; padding:13px 0; border-bottom:1px solid #ececef; }
        .restaurant-result:last-child { border-bottom:0; }
        .restaurant-result strong { color:#20232a; }
        .restaurant-result small { color:#5b2a86; font-weight:700; }
        .restaurant-result p { grid-column:1/-1; margin:0; color:#686c75; font-size:13px; line-height:1.55; }
        .canteen-pick { padding:22px; border:1px solid #b9d9d4; background:#eef8f6; text-align:center; }
        .canteen-pick span { color:#147d75; font-size:12px; font-weight:750; }
        .canteen-pick strong { display:block; margin:10px 0 6px; color:#20232a; font-size:25px; }
        .canteen-pick p { margin:0; color:#686c75; font-size:13px; }
        .preference-strip { margin-top:22px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _restaurant_results() -> None:
    recommendations = st.session_state.get("restaurant_recommendations")
    st.markdown('<div class="food-result-zone">', unsafe_allow_html=True)
    if not recommendations:
        st.markdown('<div class="food-placeholder">设置条件后生成 3 个候选，结果会留在这里方便比较。</div>', unsafe_allow_html=True)
    else:
        for item in recommendations:
            name = html.escape(str(item["name"]))
            meta = html.escape(f"{item['type']} · 人均 {item['avg_price']} · {item['distance']}")
            reason = html.escape(str(item["recommendation"]))
            st.markdown(
                f'<div class="restaurant-result"><strong>{name}</strong><small>{meta}</small><p>{reason}</p></div>',
                unsafe_allow_html=True,
            )
    st.markdown("</div>", unsafe_allow_html=True)


def _canteen_result() -> None:
    item = st.session_state.get("canteen_recommendation")
    st.markdown('<div class="food-result-zone">', unsafe_allow_html=True)
    if not item:
        st.markdown('<div class="food-placeholder">不想做决定时，让系统直接替你选一个窗口。</div>', unsafe_allow_html=True)
    else:
        location = html.escape(f"{item['canteen']} · {item['window']}")
        food_name = html.escape(str(item["food_name"]))
        reason = html.escape(str(item["reason"]))
        st.markdown(
            f'<div class="canteen-pick"><span>{location}</span><strong>{food_name}</strong><p>{reason}</p></div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def render_food_page(user_id: int) -> None:
    _inject_food_theme()
    st.markdown('<div class="page-eyebrow">CAMPUS FOOD</div>', unsafe_allow_html=True)
    st.markdown("## 今天吃什么")
    st.caption("左边认真筛选校外餐厅，右边把食堂选择交给随机推荐。")

    restaurant, canteen = st.columns(2, gap="large")
    with restaurant:
        with st.container(key="restaurant_panel"):
            st.markdown("### 校外餐厅")
            st.caption("按预算和场景筛选，不重复询问相同口味条件。")
            budget = st.slider("人均预算", min_value=15, max_value=120, value=40, step=5)
            taste_col, distance_col = st.columns(2)
            taste = taste_col.selectbox("偏好", ["随便", "米饭", "面食", "辣", "清淡"])
            distance = distance_col.selectbox("距离", ["近一点", "都可以"])
            scene_col, flavor_col = st.columns(2)
            is_group = scene_col.toggle("多人聚餐")
            flavor = flavor_col.selectbox("风味倾向", ["随便", "想吃辣", "清淡"])
            if st.button("生成餐厅候选", type="primary", use_container_width=True):
                recommendations = recommend_restaurants(
                    budget,
                    taste,
                    distance,
                    is_group,
                    flavor == "想吃辣",
                    flavor == "清淡",
                )
                st.session_state.restaurant_recommendations = recommendations
                update_working_memory(
                    st.session_state,
                    current_task_type="food_restaurant",
                    last_user_input=f"预算 {budget}，偏好 {taste}，距离 {distance}",
                    last_agent_output="; ".join(item["name"] for item in recommendations),
                )
            _restaurant_results()

    with canteen:
        with st.container(key="canteen_panel"):
            st.markdown("### 食堂随机选")
            st.caption("选三个条件，直接给出食堂、窗口和菜品。")
            meal_col, taste_col, category_col = st.columns(3)
            meal_time = meal_col.selectbox("餐次", ["早餐", "午餐", "晚餐", "随机"])
            taste = taste_col.selectbox("口味", ["清淡", "重口", "随便"])
            category = category_col.selectbox("类别", ["米饭", "面食", "小吃", "随机"])
            if st.button("替我决定", type="primary", use_container_width=True):
                item = random_canteen_food(meal_time, taste, category)
                st.session_state.canteen_recommendation = item
                update_working_memory(
                    st.session_state,
                    current_task_type="food_canteen",
                    last_user_input=f"{meal_time}/{taste}/{category}",
                    last_agent_output=item["food_name"],
                )
            _canteen_result()

    st.markdown('<div class="preference-strip"></div>', unsafe_allow_html=True)
    with st.expander("保存长期饮食偏好"):
        pref_col, action_col = st.columns([0.82, 0.18], vertical_alignment="bottom")
        pref = pref_col.text_input(
            "饮食偏好",
            placeholder="例如：晚餐偏清淡，人均预算 30 元以内。",
            label_visibility="collapsed",
        )
        if action_col.button("保存偏好", use_container_width=True, disabled=not pref.strip()):
            save_food_preference(user_id, pref)
            update_working_memory(
                st.session_state,
                current_task_type="food_preference",
                last_user_input=pref,
                last_agent_output="饮食偏好已保存",
            )
            st.success("饮食偏好已保存。")
