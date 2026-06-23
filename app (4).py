import io
import os
import gc
import tempfile
import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(
    page_title="Status Validation Analyzer",
    page_icon="chart_with_upwards_trend",
    layout="wide",
)

from utils.file_loaders import load_all_files
from utils.validators import run_sku_validation, run_pid_validation
from utils.report_generator import generate_status_report
from utils.styles import inject_css

inject_css()

# ── Persistent report directory ───────────────────────────────────────────────
REPORT_DIR = os.path.join(tempfile.gettempdir(), "svr_reports")
os.makedirs(REPORT_DIR, exist_ok=True)


def _make_filename(data, country):
    channel_map = {
        "lazada": "Lazada",
        "shopee": "Shopee",
        "zalora": "Zalora",
        "tiktok": "TikTok",
    }
    channels = []
    for key, label in channel_map.items():
        df = data.get(key, pd.DataFrame())
        if df is not None and not df.empty:
            channels.append(label)
    today = datetime.today().strftime("%Y-%m-%d")
    if channels:
        return "_".join(channels) + "_" + country + "_Status_Validation_Report_" + today + ".xlsx"
    return "Status_Validation_Report_" + country + "_" + today + ".xlsx"


def _write_report(sheets, fname):
    """Write report to persistent directory. Returns file path."""
    fpath = os.path.join(REPORT_DIR, fname)
    with pd.ExcelWriter(fpath, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            if not df.empty:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    return fpath


def _list_saved_reports():
    """List all saved report files sorted newest first."""
    files = []
    for f in os.listdir(REPORT_DIR):
        if f.endswith(".xlsx"):
            fpath = os.path.join(REPORT_DIR, f)
            mtime = os.path.getmtime(fpath)
            size_mb = round(os.path.getsize(fpath) / (1024 * 1024), 2)
            files.append((f, fpath, mtime, size_mb))
    files.sort(key=lambda x: x[2], reverse=True)
    return files


def show_df(df, max_rows=500):
    if df is None or df.empty:
        st.warning("No data to display.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Rows", len(df))
    if "Final Status" in df.columns:
        c2.metric("Active",   int((df["Final Status"] == "Active").sum()))
        c3.metric("Inactive", int((df["Final Status"] == "Inactive").sum()))
    if "Final Check" in df.columns:
        c4.metric("True Checks", int((df["Final Check"] == "True").sum()))
    preview = df.head(max_rows)
    if len(df) > max_rows:
        st.caption(
            "Showing first " + str(max_rows) + " of " + str(len(df)) +
            " rows. Download the full report for all data."
        )
    st.dataframe(preview, use_container_width=True, height=450)


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## Configuration")
    country = st.selectbox("Select Country", ["SG", "MY", "PH"])
    st.markdown("---")

    with st.expander("Lazada " + country):
        laz = st.file_uploader("Lazada File", type=["xlsx","xls","csv"], key="laz")

    with st.expander("Shopee " + country):
        sh_stk = st.file_uploader("Shopee Stock (ZIP)", type=["xlsx","xls","csv","zip"], key="sh_stk")
        sh_sts = st.file_uploader("Shopee Status", type=["xlsx","xls","csv","zip"], key="sh_sts")

    with st.expander("Zalora " + country):
        zal_stk = st.file_uploader("Zalora Stock", type=["xlsx","xls","csv"], key="zal_stk")
        zal_sts = st.file_uploader("Zalora Status", type=["xlsx","xls","csv"], key="zal_sts")

    tt_act = None
    tt_ina = None
    if country == "MY":
        with st.expander("TikTok MY"):
            tt_act = st.file_uploader("TikTok Active",   type=["xlsx","xls","csv"], key="tt_act")
            tt_ina = st.file_uploader("TikTok Inactive", type=["xlsx","xls","csv"], key="tt_ina")

    with st.expander("Reference Files"):
        cnt  = st.file_uploader("Content File",      type=["xlsx","xls","csv"], key="cnt")
        tc   = st.file_uploader("TC Inventory",      type=["xlsx","xls","csv"], key="tc")
        zec  = st.file_uploader("zEcom File",        type=["xlsx","xls","csv"], key="zec")
        alf  = st.file_uploader("ALL File",          type=["xlsx","xls","csv"], key="alf")
        excl = st.file_uploader("Exclusion List",    type=["xlsx","xls","csv"], key="excl")

    st.markdown("---")
    run_btn = st.button("Run Validation", use_container_width=True, type="primary")


# ── Main ──────────────────────────────────────────────────────────────────────
st.title("Status Validation Analyzer")
st.write("Country: " + country + "  |  Upload files in the sidebar then click Run Validation.")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Status Report",
    "SKU Validation",
    "PID Validation",
    "Downloads",
    "Saved Reports",
])

# ── Run validation ─────────────────────────────────────────────────────────────
if run_btn:
    with st.spinner("Loading files..."):
        try:
            data = load_all_files(
                country=country,
                lazada_file=laz,
                shopee_stock_file=sh_stk,
                shopee_status_file=sh_sts,
                zalora_stock_file=zal_stk,
                zalora_status_file=zal_sts,
                tiktok_active_file=tt_act,
                tiktok_inactive_file=tt_ina,
                content_file=cnt,
                tc_inv_file=tc,
                zecom_file=zec,
                all_file=alf,
                exclusion_file=excl,
            )

            parts = []
            for k, v in data.items():
                if isinstance(v, pd.DataFrame) and not v.empty:
                    parts.append(k + ":" + str(len(v)))
            st.success("Loaded: " + "  |  ".join(parts))

            with st.expander("Column names per file"):
                for k, v in data.items():
                    if isinstance(v, pd.DataFrame) and not v.empty:
                        st.write(k + " -> " + str(list(v.columns)))

            # Exclusion check
            from utils.validators import _build_article_map, _build_excl_map
            excl_df     = data.get("exclusion", pd.DataFrame())
            content_df  = data.get("content", pd.DataFrame())
            if excl_df is not None and not excl_df.empty:
                excl_map   = _build_excl_map(excl_df)
                art_map    = _build_article_map(content_df)
                if not art_map:
                    st.error(
                        "EXCLUSION WILL NOT APPLY: " + str(len(excl_map)) +
                        " exclusion entries loaded but NO Content File "
                        "SKU->Article No mapping found. Upload the Content "
                        "File with 'SKU' and 'Article No' columns."
                    )
                else:
                    matched = set(art_map.values()) & set(excl_map.keys())
                    if matched:
                        st.success("Exclusion OK: " + str(len(matched)) + " Article Nos matched.")
                    else:
                        st.warning(
                            "EXCLUSION WILL NOT APPLY: 0 matches between "
                            "Content Article Nos and Exclusion list. "
                            "Check Article No format consistency."
                        )

        except Exception as e:
            st.error("Load error: " + str(e))
            st.exception(e)
            st.stop()

    with st.spinner("Running validations..."):
        try:
            sk = run_sku_validation(data, country)
            pi = run_pid_validation(data, country)

            # Build Status Report preview from sk and pi to save time
            cols = [
                "Marketplace", "Seller SKU", "TC SKU", "Article No", "MP Status",
                "TC Status", "e-com (Yes/No)", "Launch Date", "Exclusion", "ECOM Status",
                "MP Stock", "TC Stock", "Reserved Stock", "Max 0"
            ]
            sr_parts = []
            if not sk.empty:
                sr_parts.append(sk[cols])
            if not pi.empty:
                # pi uses SellerSku instead of Seller SKU, so rename it
                pi_cols = [c if c != "Seller SKU" else "SellerSku" for c in cols]
                temp_pi = pi[pi_cols].rename(columns={"SellerSku": "Seller SKU"})
                sr_parts.append(temp_pi)
            sr = pd.concat(sr_parts, ignore_index=True) if sr_parts else pd.DataFrame()
        except Exception as e:
            st.error("Validation error: " + str(e))
            st.exception(e)
            st.stop()

    with st.spinner("Saving report to disk..."):
        try:
            fname  = _make_filename(data, country)
            sheets = {}
            if not sk.empty: sheets["SKU Validation"] = sk
            if not pi.empty: sheets["PID Validation"] = pi

            if sheets:
                fpath = _write_report(sheets, fname)
                st.session_state["report_path"]  = fpath
                st.session_state["report_fname"] = fname
                st.session_state["sr_preview"]   = sr.head(500) if not sr.empty else pd.DataFrame()
                st.session_state["sk_preview"]   = sk.head(500)
                st.session_state["pi_preview"]   = pi.head(500)
                st.session_state["sr_len"]       = len(sr)
                st.session_state["sk_len"]       = len(sk)
                st.session_state["pi_len"]       = len(pi)
                st.session_state["country"]      = country
                # Free large DataFrames from memory immediately
                del sr, sk, pi, data
                gc.collect()
                st.success("Validation complete! Report saved.")
            else:
                st.warning("No data generated. Check your input files.")
        except Exception as e:
            st.error("Report save error: " + str(e))
            st.exception(e)


# ── Tab 1 – Status Report ────────────────────────────────────────────────────
with tab1:
    if "sr_preview" in st.session_state:
        rc  = st.session_state.get("country", country)
        df  = st.session_state["sr_preview"].copy()
        tot = st.session_state.get("sr_len", len(df))
        st.markdown("### Status Report - " + rc)
        if not df.empty and "Marketplace" in df.columns:
            opts = sorted(df["Marketplace"].unique())
            sel  = st.multiselect("Filter by Marketplace", opts, default=opts, key="f1")
            df   = df[df["Marketplace"].isin(sel)]
        show_df(df)
        if tot > 500:
            st.info("Preview shows first 500 rows. Download full report for all " + str(tot) + " rows.")
    else:
        st.info("Run validation to see results.")


# ── Tab 2 – SKU Validation ───────────────────────────────────────────────────
with tab2:
    if "sk_preview" in st.session_state:
        rc  = st.session_state.get("country", country)
        df  = st.session_state["sk_preview"].copy()
        tot = st.session_state.get("sk_len", len(df))
        st.markdown("### SKU Validation - " + rc)
        if not df.empty:
            c1, c2 = st.columns(2)
            if "Final Check" in df.columns:
                opts = sorted(df["Final Check"].unique())
                sel  = c1.multiselect("Final Check", opts, default=opts, key="f2")
                df   = df[df["Final Check"].isin(sel)]
            if "Marketplace" in df.columns:
                opts2 = sorted(df["Marketplace"].unique())
                sel2  = c2.multiselect("Marketplace", opts2, default=opts2, key="f2b")
                df    = df[df["Marketplace"].isin(sel2)]
        show_df(df)
        if tot > 500:
            st.info("Preview shows first 500 rows. Download full report for all " + str(tot) + " rows.")
    else:
        st.info("Run validation to see results.")


# ── Tab 3 – PID Validation ───────────────────────────────────────────────────
with tab3:
    if "pi_preview" in st.session_state:
        rc  = st.session_state.get("country", country)
        df  = st.session_state["pi_preview"].copy()
        tot = st.session_state.get("pi_len", len(df))
        st.markdown("### PID Validation - " + rc)
        if not df.empty:
            c1, c2 = st.columns(2)
            if "Final Check" in df.columns:
                opts = sorted(df["Final Check"].unique())
                sel  = c1.multiselect("Final Check", opts, default=opts, key="f3")
                df   = df[df["Final Check"].isin(sel)]
            if "Dual Status" in df.columns:
                opts2 = sorted(df["Dual Status"].unique())
                sel2  = c2.multiselect("Dual Status", opts2, default=opts2, key="f3b")
                df    = df[df["Dual Status"].isin(sel2)]
        show_df(df)
        if tot > 500:
            st.info("Preview shows first 500 rows. Download full report for all " + str(tot) + " rows.")
    else:
        st.info("Run validation to see results.")


# ── Tab 4 – Downloads (current session) ──────────────────────────────────────
with tab4:
    st.markdown("### Download Current Report")
    report_path  = st.session_state.get("report_path")
    report_fname = st.session_state.get("report_fname")

    if report_path and os.path.exists(report_path):
        size_mb = round(os.path.getsize(report_path) / (1024 * 1024), 2)
        st.info("File: **" + report_fname + "**  (" + str(size_mb) + " MB)")
        with open(report_path, "rb") as f:
            st.download_button(
                "Download Excel Report",
                data=f.read(),
                file_name=report_fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_current",
            )
    else:
        st.info("Run validation first to generate a report.")


# ── Tab 5 – Saved Reports (persistent) ───────────────────────────────────────
with tab5:
    st.markdown("### All Saved Reports")
    st.caption(
        "Reports are saved to the server and remain available until "
        "the app is restarted. You can download any previous report here."
    )

    saved = _list_saved_reports()
    if not saved:
        st.info("No saved reports yet. Run validation to generate one.")
    else:
        for fname, fpath, mtime, size_mb in saved:
            col1, col2, col3 = st.columns([5, 2, 2])
            col1.write("**" + fname + "**")
            col2.write(str(size_mb) + " MB")
            ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            col3.write(ts)
            with open(fpath, "rb") as f:
                st.download_button(
                    "Download " + fname,
                    data=f.read(),
                    file_name=fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_" + fname,
                )
            st.markdown("---")

    if saved:
        if st.button("Clear all saved reports", type="secondary"):
            for _, fpath, _, _ in saved:
                try:
                    os.remove(fpath)
                except Exception:
                    pass
            st.success("All saved reports cleared.")
            st.rerun()
