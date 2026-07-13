"""Shared visual language for the public application pages."""

import streamlit as st


def inject_theme() -> None:
    """Install the common navigation, layout and component styling."""
    st.markdown(
        """
        <style>
        :root {
            --page-max: 1320px;
            --nju-purple: #5b2a86;
            --nju-purple-soft: #f2edf8;
            --campus-teal: #087f78;
            --campus-teal-soft: #e5f4f1;
            --youth-coral: #d95f45;
            --sun-yellow: #e7b93f;
            --ink: #172033;
            --muted: #667085;
            --line: #dfe3ea;
            --paper: #fbfcfe;
            --surface: #ffffff;
        }
        [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"],
        .stDeployButton, header [data-testid="stToolbar"], [data-testid="stSidebar"], [data-testid="stHeader"] {
            display: none !important;
            visibility: hidden !important;
        }
        .stApp { background: var(--paper); color: var(--ink); }
        .block-container { max-width: var(--page-max); padding: 0 2.35rem 4.25rem; }
        .st-key-top_nav {
            position: sticky; top: 0; z-index: 999;
            margin: 0 -2.35rem 2.25rem; padding: .9rem 2.35rem .76rem;
            background: rgba(251, 252, 254, .94); border-bottom: 1px solid var(--line);
            backdrop-filter: blur(16px);
        }
        .brand-lockup { display: flex; align-items: center; gap: 10px; min-height: 42px; white-space: nowrap; }
        .brand-mark { display: grid; place-items: center; width: 34px; height: 34px; color: white;
            background: var(--nju-purple); border-radius: 6px; font-weight: 800; box-shadow: 0 4px 10px rgba(91,42,134,.16); }
        .brand-name { font-weight: 760; color: var(--ink); font-size: .98rem; line-height: 1.1; }
        .brand-sub { margin-top: 4px; color: var(--muted); font-size: .7rem; line-height: 1; }
        .page-eyebrow { margin-top: .4rem; color: var(--campus-teal); font-size: .72rem; font-weight: 780; letter-spacing: .13em; }
        h1, h2, h3 { color: var(--ink); letter-spacing: 0 !important; }
        h2 { margin-top: .45rem; }

        .hub-hero { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(360px, .95fr);
            align-items: center; gap: 70px; min-height: 410px; padding: 26px 0 54px; border-bottom: 1px solid var(--line); }
        .hero-copy h1 { max-width: 690px; margin: 12px 0 18px; font-size: 60px; line-height: 1.07; color: var(--ink); }
        .hero-copy h1 span { color: var(--nju-purple); }
        .hero-copy p { max-width: 590px; margin: 0; color: var(--muted); font-size: 1.02rem; line-height: 1.82; }
        .hero-note { display: inline-flex; align-items: center; gap: 8px; margin-top: 25px; color: var(--campus-teal); font-size: .84rem; font-weight: 700; }
        .hero-note::before { width: 8px; height: 8px; border-radius: 50%; background: var(--sun-yellow); content: ""; }
        .campus-board { position: relative; min-height: 302px; padding: 27px 28px; overflow: hidden;
            background: #1f3149; color: white; border-radius: 8px; box-shadow: 14px 14px 0 #dceeea; }
        .campus-board::after { position: absolute; right: -54px; bottom: -74px; width: 210px; height: 210px;
            border: 1px solid rgba(255,255,255,.18); border-radius: 50%; content: ""; }
        .board-head { color: #9ee0d7; font-size: .72rem; font-weight: 760; letter-spacing: .12em; }
        .board-title { position: relative; z-index: 1; margin: 21px 0 25px; font-size: 1.7rem; font-weight: 760; line-height: 1.35; }
        .board-flow { position: relative; z-index: 1; display: grid; gap: 0; }
        .board-row { display: grid; grid-template-columns: 28px 1fr auto; gap: 10px; align-items: center;
            padding: 13px 0; border-top: 1px solid rgba(255,255,255,.16); }
        .board-no { color: #f2ca59; font-family: Consolas, monospace; font-size: .9rem; }
        .board-tag { color: #a9d7e4; font-size: .76rem; }

        .module-band { padding: 42px 0 8px; }
        .module-band h2 { margin-bottom: 22px; font-size: 2rem; }
        .module-grid { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid var(--line); border-right: 0; }
        .module-item { min-height: 165px; padding: 24px 22px; border-right: 1px solid var(--line); background: var(--surface); }
        .module-item:nth-child(even) { background: #f9fbfc; }
        .module-index { color: var(--campus-teal); font-size: .72rem; font-weight: 780; letter-spacing: .06em; }
        .module-item strong { display: block; margin: 20px 0 8px; color: var(--ink); font-size: 1.06rem; }
        .module-item p { margin: 0; color: var(--muted); font-size: .87rem; line-height: 1.65; }
        .desk-strip { display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 18px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
        .desk-stat { min-height: 92px; padding: 18px; border-right: 1px solid var(--line); background: var(--surface); }
        .desk-stat:last-child { border-right: 0; }
        .desk-stat span { display: block; color: var(--muted); font-size: .78rem; }
        .desk-stat strong { display: block; margin-top: 7px; color: var(--ink); font-size: 1.65rem; font-weight: 720; overflow-wrap: anywhere; }
        .desk-stat.model strong { font-size: 1.15rem; color: var(--campus-teal); }

        [data-testid="stButton"] button, [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primary"] {
            border-radius: 6px !important; min-height: 40px; font-weight: 650;
        }
        [data-testid="stBaseButton-primary"] { background: var(--nju-purple) !important; border-color: var(--nju-purple) !important; }
        [data-testid="stBaseButton-secondary"] { background: white !important; border-color: #cfd4dc !important; color: var(--ink) !important; }
        [data-testid="stBaseButton-secondary"] p { color: var(--ink) !important; }
        [data-testid="stPopoverButton"] { background: white !important; border: 1px solid #cfd4dc !important; color: var(--ink) !important; border-radius: 6px !important; }
        [data-testid="stPopoverButton"] p, [data-testid="stPopoverButton"] span { color: var(--ink) !important; }
        [data-testid="stBaseButton-pills"] { background: transparent !important; border: 1px solid transparent !important; color: var(--muted) !important; border-radius: 999px !important; }
        [data-testid="stBaseButton-pills"] p { color: var(--muted) !important; }
        [data-testid="stBaseButton-pills"]:hover { background: white !important; border-color: var(--line) !important; }
        [data-testid="stBaseButton-pillsActive"] { background: var(--nju-purple-soft) !important; border: 1px solid #d7c6e7 !important; color: var(--nju-purple) !important; border-radius: 999px !important; }
        [data-testid="stBaseButton-pillsActive"] p { color: var(--nju-purple) !important; }
        [data-testid="stFileUploaderDropzone"], [data-testid="stForm"], [data-testid="stExpander"] { border-radius: 6px !important; }
        [data-testid="stMetric"] { background: white; border-left: 4px solid var(--campus-teal); padding: 12px 15px; }
        [data-testid="stWidgetLabel"] p { color: var(--ink) !important; }
        [data-baseweb="select"] > div, [data-baseweb="input"] > div, [data-baseweb="textarea"] { background: white !important; color: var(--ink) !important; border-color: #cfd4dc !important; }
        [data-baseweb="select"] span, [data-baseweb="select"] input, [data-baseweb="input"] input, [data-baseweb="textarea"] textarea { color: var(--ink) !important; background: white !important; }

        @media (max-width: 900px) {
            .block-container { padding-inline: 1rem; }
            .st-key-top_nav { margin-inline: -1rem; padding-inline: 1rem; }
            .hub-hero { grid-template-columns: 1fr; gap: 32px; min-height: auto; }
            .hero-copy h1 { font-size: 42px; }
            .module-grid { grid-template-columns: 1fr 1fr; }
        }
        @media (max-width: 620px) {
            .module-grid, .desk-strip { grid-template-columns: 1fr; }
            .module-item, .desk-stat { border-right: 0; border-bottom: 1px solid var(--line); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
