import streamlit as st

def inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans', sans-serif;
    }

    /* Tighten page margins and remove unnecessary empty space */
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 96% !important;
    }

    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    [data-testid="stHeader"],
    .stApp {
        background: #F9F5FF !important;
        color: #1D2939 !important;
    }

    section[data-testid="stSidebar"] {
        background: #F4EBFF !important;
        border-right: 1px solid #E4D0FF !important;
    }

    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stFileUploader label,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: #53389E !important;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }

    [data-testid="metric-container"] {
        background: #ffffff;
        border: 1px solid #E4D0FF;
        border-radius: 8px;
        padding: 12px 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }

    [data-testid="metric-container"] label {
        color: #344054 !important;
        font-weight: 600;
        font-size: 0.75rem !important;
    }

    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        color: #7F56D9 !important;
        font-family: 'IBM Plex Mono', monospace;
    }

    .stTabs [data-baseweb="tab-list"] {
        background: #F4EBFF;
        border-radius: 8px;
        padding: 4px;
    }

    .stTabs [data-baseweb="tab"] {
        color: #53389E;
        font-weight: 600;
        font-size: 0.82rem;
    }

    .stTabs [aria-selected="true"] {
        color: #7F56D9 !important;
        background: #ffffff !important;
        border-radius: 6px;
    }

    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #7F56D9, #53389E);
        color: white;
        border: none;
        border-radius: 6px;
        font-weight: 600;
        letter-spacing: 0.04em;
        transition: all 0.2s;
    }

    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #9E77ED, #7F56D9);
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(127, 86, 217, 0.3);
    }

    .stDataFrame {
        border: 1px solid #E4D0FF;
        border-radius: 8px;
    }

    h1 {
        color: #1D2939 !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em !important;
    }

    h3 {
        color: #1D2939 !important;
        font-weight: 600 !important;
        font-size: 1rem !important;
    }

    .streamlit-expanderHeader {
        font-size: 0.85rem !important;
        font-weight: 600;
        color: #1D2939 !important;
    }

    .stDownloadButton > button {
        background: #22C55E;
        border: 1px solid #22C55E;
        color: white;
        border-radius: 6px;
        font-weight: 600;
    }

    .stDownloadButton > button:hover {
        background: #16A34A;
    }

    /* Style the file uploader dropzones to be bold purple dashed */
    [data-testid="stFileUploaderDropzone"] {
        border: 2px dashed #7F56D9 !important;
        border-radius: 8px;
        background: #FAF5FF !important;
    }
    
    /* Listing QC Styles */
    .header-container {
        padding: 2rem;
        background-color: rgba(18, 20, 38, 0.6) !important;
        border: 1px solid rgba(217, 70, 239, 0.25) !important;
        border-radius: 16px;
        box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.9), 0 0 20px rgba(217, 70, 239, 0.05);
        backdrop-filter: blur(12px);
        margin-bottom: 2rem;
    }
    .main-title {
        font-size: 2.8rem;
        font-weight: 800;
        color: #ffffff !important;
        letter-spacing: -0.02em;
        margin-bottom: 0.5rem;
        text-shadow: 0 0 25px rgba(217, 70, 239, 0.3);
    }
    .sub-title {
        font-size: 1.05rem;
        font-weight: 400;
        color: #a5b4fc !important;
    }
    .metric-card {
        background-color: rgba(18, 20, 38, 0.8) !important;
        border: 1px solid rgba(255, 255, 255, 0.04) !important;
        border-radius: 12px;
        padding: 1.4rem;
        box-shadow: 0 8px 20px -5px rgba(0, 0, 0, 0.7);
        transition: all 0.25s ease-in-out;
    }
    .metric-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 15px 30px -8px rgba(0, 0, 0, 0.8);
        border-color: rgba(217, 70, 239, 0.4) !important;
    }
    .metric-title {
        font-size: 0.8rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #cbd5e1;
        margin-bottom: 0.4rem;
        opacity: 0.85;
    }
    .metric-value {
        font-size: 2.1rem;
        font-weight: 800;
        font-family: 'IBM Plex Mono', monospace;
        letter-spacing: -0.02em;
    }
    .metric-total {
        border-left: 4px solid #38bdf8 !important;
    }
    .metric-total .metric-value {
        color: #38bdf8 !important;
    }
    .metric-passed {
        border-left: 4px solid #10b981 !important;
    }
    .metric-passed .metric-value {
        color: #34d399 !important;
    }
    .metric-warnings {
        border-left: 4px solid #f59e0b !important;
    }
    .metric-warnings .metric-value {
        color: #fbbf24 !important;
    }
    .metric-failed {
        border-left: 4px solid #ef4444 !important;
    }
    .metric-failed .metric-value {
        color: #f87171 !important;
    }
    .log-box {
        font-family: 'IBM Plex Mono', monospace !important;
        background-color: #010204 !important;
        border: 1px solid rgba(217, 70, 239, 0.2) !important;
        border-radius: 10px !important;
        padding: 1rem !important;
        height: 250px !important;
        overflow-y: auto !important;
        color: #38bdf8 !important;
        font-size: 0.85rem !important;
        line-height: 1.5 !important;
        box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.8) !important;
    }
    .qc-error-badge {
        background-color: #7f1d1d !important;
        color: #fca5a5 !important;
        padding: 3px 8px !important;
        border-radius: 12px !important;
        font-size: 0.72rem !important;
        font-weight: 700 !important;
        display: inline-block !important;
    }
    .qc-warn-badge {
        background-color: #78350f !important;
        color: #fde047 !important;
        padding: 3px 8px !important;
        border-radius: 12px !important;
        font-size: 0.72rem !important;
        font-weight: 700 !important;
        display: inline-block !important;
    }
    .qc-pass-badge {
        background-color: #064e3b !important;
        color: #6ee7b7 !important;
        padding: 3px 8px !important;
        border-radius: 12px !important;
        font-size: 0.72rem !important;
        font-weight: 700 !important;
        display: inline-block !important;
    }
    .qc-table {
        width: 100%;
        border-collapse: separate !important;
        border-spacing: 0 !important;
        background-color: rgba(18, 20, 38, 0.7) !important;
        border: 1px solid rgba(217, 70, 239, 0.25) !important;
        border-radius: 12px !important;
        overflow: hidden !important;
        margin-top: 1rem !important;
        margin-bottom: 2rem !important;
        box-shadow: 0 10px 25px -10px rgba(0, 0, 0, 0.7);
    }
    .qc-table th {
        background-color: rgba(30, 41, 59, 0.9) !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        font-size: 0.85rem !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
        padding: 12px 16px !important;
        border-bottom: 1px solid rgba(217, 70, 239, 0.2) !important;
    }
    .qc-table td {
        padding: 12px 16px !important;
        font-size: 0.88rem !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05) !important;
        color: #e2e8f0 !important;
    }
    .qc-table tr:last-child td {
        border-bottom: none !important;
    }
    .qc-status-ok {
        background-color: rgba(6, 78, 59, 0.4) !important;
        color: #34d399 !important;
        border: 1px solid rgba(52, 211, 153, 0.3) !important;
        padding: 4px 10px !important;
        border-radius: 6px !important;
        font-weight: 700 !important;
        font-size: 0.75rem !important;
        text-align: center !important;
        display: inline-block !important;
    }
    .qc-status-mismatch {
        background-color: rgba(127, 29, 29, 0.4) !important;
        color: #f87171 !important;
        border: 1px solid rgba(248, 113, 113, 0.3) !important;
        padding: 4px 10px !important;
        border-radius: 6px !important;
        font-weight: 700 !important;
        font-size: 0.75rem !important;
        text-align: center !important;
        display: inline-block !important;
        box-shadow: 0 0 10px rgba(239, 68, 68, 0.1);
    }
    </style>
    """, unsafe_allow_html=True)
