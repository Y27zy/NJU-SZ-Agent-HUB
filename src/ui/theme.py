import streamlit as st


def inject_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --nju-purple: #5b2a86;
            --nju-purple-soft: #f0eaf6;
            --campus-teal: #147d75;
            --youth-coral: #d95f45;
            --sun-yellow: #e7b93f;
            --ink: #20232a;
            --muted: #686c75;
            --line: #e1e2e6;
            --paper: #fcfcfd;
        }
        [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"],
        .stDeployButton, header [data-testid="stToolbar"], [data-testid="stSidebar"], [data-testid="stHeader"] {
            display: none !important;
            visibility: hidden !important;
        }
        .stApp { background: var(--paper); color: var(--ink); }
        .block-container { max-width: 1480px; padding: 0 2.4rem 3rem; }
        .st-key-top_nav {
            position: sticky; top: 0; z-index: 999;
            margin: 0 -2.4rem 1.8rem; padding: .72rem 2.4rem;
            background: rgba(252, 252, 253, .96); border-bottom: 1px solid var(--line);
        }
        .brand-lockup { display: flex; align-items: center; gap: 10px; min-height: 42px; white-space: nowrap; }
        .brand-mark { display: grid; place-items: center; width: 34px; height: 34px; color: white;
            background: var(--nju-purple); border-radius: 5px; font-weight: 800; }
        .brand-name { font-weight: 760; color: var(--ink); font-size: 1rem; }
        .brand-sub { color: var(--muted); font-size: .72rem; }
        .page-eyebrow { margin-top: .4rem; color: var(--campus-teal); font-size: .76rem; font-weight: 760; letter-spacing: .12em; }
        h1, h2, h3 { letter-spacing: 0 !important; }
        h2 { color: var(--ink); }
        .hub-hero { min-height: 390px; display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(320px, .92fr);
            align-items: center; gap: 5vw; padding: 34px 0 50px; border-bottom: 1px solid var(--line); }
        .hero-copy h1 { max-width: 760px; margin: 10px 0 18px; font-size: clamp(42px, 5vw, 72px); line-height: 1.08; color: var(--ink); }
        .hero-copy h1 span { color: var(--nju-purple); }
        .hero-copy p { max-width: 680px; margin: 0; color: var(--muted); font-size: 1.08rem; line-height: 1.75; }
        .campus-board { min-height: 292px; padding: 26px; background: #32213f; color: white; border-radius: 6px;
            box-shadow: 18px 18px 0 #e8c454; }
        .board-head { color: #d8c4ea; font-size: .75rem; font-weight: 750; letter-spacing: .1em; }
        .board-title { margin: 20px 0 28px; font-size: 1.65rem; font-weight: 760; line-height: 1.35; }
        .board-flow { display: grid; gap: 9px; }
        .board-row { display: grid; grid-template-columns: 28px 1fr auto; gap: 10px; align-items: center;
            padding: 11px 0; border-top: 1px solid rgba(255,255,255,.16); }
        .board-no { color: #e8c454; font-family: Consolas, monospace; }
        .board-tag { color: #b5e2dc; font-size: .78rem; }
        .module-band { padding: 38px 0 12px; }
        .module-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; border: 1px solid var(--line); border-right: 0; }
        .module-item { min-height: 150px; padding: 22px; border-right: 1px solid var(--line); background: white; }
        .module-index { color: var(--youth-coral); font-size: .75rem; font-weight: 760; }
        .module-item strong { display: block; margin: 18px 0 8px; font-size: 1.05rem; }
        .module-item p { margin: 0; color: var(--muted); font-size: .86rem; line-height: 1.6; }
        [data-testid="stButton"] button, [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primary"] {
            border-radius: 5px !important; min-height: 40px; font-weight: 650;
        }
        [data-testid="stBaseButton-primary"] { background: var(--nju-purple) !important; border-color: var(--nju-purple) !important; }
        [data-testid="stBaseButton-secondary"] {
            background: white !important; border-color: #cfd1d7 !important; color: var(--ink) !important;
        }
        [data-testid="stBaseButton-secondary"] p { color: var(--ink) !important; }
        [data-testid="stPopoverButton"] {
            background: white !important; border: 1px solid #cfd1d7 !important; color: var(--ink) !important;
        }
        [data-testid="stPopoverButton"] p, [data-testid="stPopoverButton"] span { color: var(--ink) !important; }
        [data-testid="stBaseButton-pills"] {
            background: white !important; border: 1px solid var(--line) !important; color: var(--ink) !important;
        }
        [data-testid="stBaseButton-pills"] p { color: var(--ink) !important; }
        [data-testid="stBaseButton-pillsActive"] {
            background: var(--nju-purple-soft) !important; border: 1px solid #cbb8dc !important; color: var(--nju-purple) !important;
        }
        [data-testid="stBaseButton-pillsActive"] p { color: var(--nju-purple) !important; }
        [data-testid="stFileUploaderDropzone"], [data-testid="stForm"], [data-testid="stExpander"] { border-radius: 6px !important; }
        [data-testid="stMetric"] { background: white; border-left: 4px solid var(--campus-teal); padding: 12px 15px; }
        [data-testid="stWidgetLabel"] p { color: var(--ink) !important; }
        [data-baseweb="select"] > div, [data-baseweb="input"] > div, [data-baseweb="textarea"] {
            background: white !important; color: var(--ink) !important; border-color: #cfd1d7 !important;
        }
        [data-baseweb="select"] span, [data-baseweb="select"] input,
        [data-baseweb="input"] input, [data-baseweb="textarea"] textarea {
            color: var(--ink) !important; background: white !important;
        }
        @media (max-width: 900px) {
            .block-container { padding-inline: 1rem; }
            .st-key-top_nav { margin-inline: -1rem; padding-inline: 1rem; }
            .hub-hero { grid-template-columns: 1fr; }
            .hero-copy h1 { font-size: 42px; }
            .module-grid { grid-template-columns: 1fr 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
