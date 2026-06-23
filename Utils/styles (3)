import streamlit as st

def inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans', sans-serif;
    }

    .stApp {
        background: #0f1117;
        color: #e2e8f0;
    }

    section[data-testid="stSidebar"] {
        background: #1a1f2e;
        border-right: 1px solid #2d3748;
    }

    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stFileUploader label,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: #a0aec0 !important;
        font-size: 0.82rem;
        font-weight: 600;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }

    [data-testid="metric-container"] {
        background: #1a1f2e;
        border: 1px solid #2d3748;
        border-radius: 8px;
        padding: 12px 16px;
    }

    [data-testid="metric-container"] label {
        color: #718096 !important;
        font-size: 0.75rem !important;
    }

    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        color: #63b3ed !important;
        font-family: 'IBM Plex Mono', monospace;
    }

    .stTabs [data-baseweb="tab-list"] {
        background: #1a1f2e;
        border-radius: 8px;
        padding: 4px;
    }

    .stTabs [data-baseweb="tab"] {
        color: #718096;
        font-weight: 600;
        font-size: 0.82rem;
    }

    .stTabs [aria-selected="true"] {
        color: #63b3ed !important;
        background: #2d3748 !important;
        border-radius: 6px;
    }

    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #3182ce, #2b6cb0);
        color: white;
        border: none;
        border-radius: 6px;
        font-weight: 600;
        letter-spacing: 0.04em;
        transition: all 0.2s;
    }

    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #4299e1, #3182ce);
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(49,130,206,0.4);
    }

    .stDataFrame {
        border: 1px solid #2d3748;
        border-radius: 8px;
    }

    h1 {
        color: #e2e8f0 !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em !important;
    }

    h3 {
        color: #a0aec0 !important;
        font-weight: 600 !important;
        font-size: 1rem !important;
    }

    .streamlit-expanderHeader {
        font-size: 0.85rem !important;
        font-weight: 600;
        color: #a0aec0 !important;
    }

    .stDownloadButton > button {
        background: #276749;
        border: 1px solid #38a169;
        color: #c6f6d5;
        border-radius: 6px;
        font-weight: 600;
    }

    .stDownloadButton > button:hover {
        background: #2f855a;
    }
    </style>
    """, unsafe_allow_html=True)
