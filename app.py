import io
import os
import gc
import tempfile
import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(
    page_title="PUMA Automation (Status & Stock, Order Valiation, Listing QC)",
    page_icon="chart_with_upwards_trend",
    layout="wide",
)

from file_loaders import load_all_files
from validators import run_sku_validation, run_pid_validation, save_df_to_excel_fast
from report_generator import generate_status_report
from styles import inject_css
# Removed order and listing imports for Status Validation only build

inject_css()

# Initialize Session States for Listing QC
if "lqc_ran_validation" not in st.session_state:
    st.session_state.lqc_ran_validation = False
if "lqc_val_df" not in st.session_state:
    st.session_state.lqc_val_df = pd.DataFrame()
if "lqc_exc_df" not in st.session_state:
    st.session_state.lqc_exc_df = pd.DataFrame()
if "lqc_logs" not in st.session_state:
    st.session_state.lqc_logs = []
if "lqc_qc_stage" not in st.session_state:
    st.session_state.lqc_qc_stage = "Internal QC"
if "lqc_channel" not in st.session_state:
    st.session_state.lqc_channel = "Shopee PH"
if "lqc_ran_comparison" not in st.session_state:
    st.session_state.lqc_ran_comparison = False
if "lqc_comp_df" not in st.session_state:
    st.session_state.lqc_comp_df = pd.DataFrame()
if "lqc_comp_metrics" not in st.session_state:
    st.session_state.lqc_comp_metrics = {}

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
    save_df_to_excel_fast(sheets, fpath)
    return fpath


def _write_qc_report(sheets, fname):
    """Write QC audit report to persistent directory. Returns file path."""
    fpath = os.path.join(REPORT_DIR, fname)
    save_df_to_excel_fast(sheets, fpath)
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
    st.markdown("## Task Selection")
    task = st.selectbox(
        "Select Task / Process",
        ["Status Validation", "Status validation QC"],
        key="selected_task"
    )
    st.markdown("---")

    if task in ["Status Validation", "Status validation QC"]:
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
        if task == "Status Validation":
            run_btn = st.button("Run Validation", use_container_width=True, type="primary")
            working_file = None
            run_qc_btn = False
        else:
            working_file = st.file_uploader(
                "Upload Team Working Sheet (.xlsx)", 
                type=["xlsx"], 
                key="qc_working_file"
            )
            run_qc_btn = st.button("Run QC Cross-Check", type="primary", use_container_width=True)
            run_btn = False

    if task != "Status validation QC":
        working_file = None
        run_qc_btn = False


# ── Main ──────────────────────────────────────────────────────────────────────
st.title("PUMA Automation (Status & Stock)")

if task == "Status Validation":
    st.write("Country: " + country + "  |  Upload files in the sidebar then click Run Validation.")
    
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
                from validators import _build_article_map, _build_excl_map, _normalise_article_no
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
                        norm_art_vals = {_normalise_article_no(v) for v in art_map.values()}
                        matched = norm_art_vals & set(excl_map.keys())
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
                
                # Generate filename before freeing raw data
                fname = _make_filename(data, country)
                
                # Aggressively delete raw data dictionary to reclaim hundreds of MBs of RAM
                del data
                gc.collect()
                
            except Exception as e:
                st.error("Validation error: " + str(e))
                st.exception(e)
                st.stop()

        with st.spinner("Saving report to disk..."):
            try:
                sheets = {}
                if not sk.empty: sheets["SKU Level Validation"] = sk
                if not pi.empty: sheets["PID Level Validation"] = pi

                if sheets:
                    fpath = _write_report(sheets, fname)
                    st.session_state["report_path"]  = fpath
                    st.session_state["report_fname"] = fname
                    st.session_state["sr_preview"]   = sr.head(500) if not sr.empty else pd.DataFrame()
                    st.session_state["sk_preview"]   = sk.head(500) if not sk.empty else pd.DataFrame()
                    st.session_state["pi_preview"]   = pi.head(500) if not pi.empty else pd.DataFrame()
                    st.session_state["sr_len"]       = len(sr)
                    st.session_state["sk_len"]       = len(sk)
                    st.session_state["pi_len"]       = len(pi)
                    st.session_state["country"]      = country
                    # Free large DataFrames from memory immediately
                    del sr, sk, pi, sheets
                    gc.collect()
                    st.success("Validation complete! Report saved.")
                else:
                    st.warning("No data generated. Check your input files.")
            except Exception as e:
                st.error("Report save error: " + str(e))
                st.exception(e)

    # ── Tabs for Status Validation ──
    tab1, tab2, tab3 = st.tabs([
        "Status Validation",
        "Downloads",
        "Saved Reports",
    ])

    # ── Tab 1 – Status Validation ────────────────────────────────────────────────────
    with tab1:
        if "sr_preview" in st.session_state:
            rc  = st.session_state.get("country", country)
            df  = st.session_state["sr_preview"].copy()
            tot = st.session_state.get("sr_len", len(df))
            st.markdown("### Status Validation - " + rc)
            if not df.empty and "Marketplace" in df.columns:
                opts = sorted(df["Marketplace"].unique())
                sel  = st.multiselect("Filter by Marketplace", opts, default=opts, key="f1")
                df   = df[df["Marketplace"].isin(sel)]
            show_df(df)
            if tot > 500:
                st.info("Preview shows first 500 rows. Download full report for all " + str(tot) + " rows.")
        else:
            st.info("Run validation to see results.")

    # ── Tab 3 – Downloads (current session) ──────────────────────────────────────
    with tab2:
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

    # ── Tab 4 – Saved Reports (persistent) ───────────────────────────────────────
    with tab3:
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


elif task == "Status validation QC":
    st.write("Country: " + country + "  |  Upload raw files and the team working sheet in the sidebar, then click Run QC Cross-Check.")
    tab1, = st.tabs(["Status validation QC"])
    with tab1:
        st.markdown("### Stock Validation QC Cross-Check")
        st.caption(
            "Upload a completed Status/Stock validation Excel report (working sheet) "
            "shared by team members. The tool will run the correct matching logic on "
            "the raw reference files uploaded in the sidebar and highlight any mismatches."
        )
    
        working_file = st.file_uploader(
            "Upload Team Working Sheet (.xlsx)", 
            type=["xlsx"], 
            key="qc_working_file"
        )
    
        run_qc_btn = st.button("Run QC Cross-Check", type="primary", use_container_width=True)
    
        # ── Persistent QC Report Download & Results display ──────────────────────
        qc_report_path = st.session_state.get("qc_report_path")
        qc_report_fname = st.session_state.get("qc_report_fname")
        if qc_report_path and os.path.exists(qc_report_path):
            size_mb = round(os.path.getsize(qc_report_path) / (1024 * 1024), 2)
            st.success(f"QC Audit complete! Report: **{qc_report_fname}** ({size_mb} MB)")
            with open(qc_report_path, "rb") as f:
                st.download_button(
                    "Download QC Audit Report (Excel)",
                    data=f.read(),
                    file_name=qc_report_fname,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="dl_qc_report"
                )
            st.markdown("---")
        
            # Render SKU results from session state
            if st.session_state.get("qc_has_sku"):
                st.markdown("#### SKU Validation Audit Results (Lazada / Zalora)")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total Rows Checked", st.session_state["qc_sku_total_checked"])
                m_count = st.session_state["qc_sku_m_count"]
                c2.metric("Mismatched Rows", m_count, delta=-m_count if m_count > 0 else 0, delta_color="inverse")
                c3.metric("Missing Rows", st.session_state["qc_sku_missing_count"])
                c4.metric("Extra Rows", st.session_state["qc_sku_extra_count"])
            
                m_df = st.session_state["qc_sku_m_df"]
                if m_count > 0 and not m_df.empty:
                    st.warning(f"Found {m_count} rows with value mismatches!")
                    st.dataframe(m_df, use_container_width=True, hide_index=True)
                else:
                    st.success("All SKU Validation values match perfectly!")
                
                missing_df = st.session_state["qc_sku_missing_df"]
                if not missing_df.empty:
                    with st.expander("Show Missing Rows (Present in computed but not in working sheet)"):
                        st.dataframe(missing_df, use_container_width=True, hide_index=True)
                    
                extra_df = st.session_state["qc_sku_extra_df"]
                if not extra_df.empty:
                    with st.expander("Show Extra Rows (Present in working sheet but not in computed results)"):
                        st.dataframe(extra_df, use_container_width=True, hide_index=True)
                    
            # Render PID results from session state
            if st.session_state.get("qc_has_pid"):
                if st.session_state.get("qc_has_sku"):
                    st.markdown("---")
                st.markdown("#### PID Validation Audit Results (Shopee / TikTok)")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total Rows Checked", st.session_state["qc_pid_total_checked"])
                m_count = st.session_state["qc_pid_m_count"]
                c2.metric("Mismatched Rows", m_count, delta=-m_count if m_count > 0 else 0, delta_color="inverse")
                c3.metric("Missing Rows", st.session_state["qc_pid_missing_count"])
                c4.metric("Extra Rows", st.session_state["qc_pid_extra_count"])
            
                m_df = st.session_state["qc_pid_m_df"]
                if m_count > 0 and not m_df.empty:
                    st.warning(f"Found {m_count} rows with value mismatches!")
                    st.dataframe(m_df, use_container_width=True, hide_index=True)
                else:
                    st.success("All PID Validation values match perfectly!")
                
                missing_df = st.session_state["qc_pid_missing_df"]
                if not missing_df.empty:
                    with st.expander("Show Missing Rows (Present in computed but not in working sheet)"):
                        st.dataframe(missing_df, use_container_width=True, hide_index=True)
                    
                extra_df = st.session_state["qc_pid_extra_df"]
                if not extra_df.empty:
                    with st.expander("Show Extra Rows (Present in working sheet but not in computed results)"):
                        st.dataframe(extra_df, use_container_width=True, hide_index=True)

        # ── Calculation Trigger ──────────────────────────────────────────────────
        if run_qc_btn:
            if not working_file:
                st.error("Please upload the team's working sheet first.")
            else:
                # Clear old QC results from session state
                for k in list(st.session_state.keys()):
                    if k.startswith("qc_"):
                        del st.session_state[k]
                    
                # 1. Load raw files from sidebar
                with st.spinner("Loading raw reference files from sidebar..."):
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
                    except Exception as e:
                        st.error("Failed to load raw reference files: " + str(e))
                        st.stop()
            
                # 2. Open the uploaded working sheet to inspect sheets
                with st.spinner("Reading uploaded working sheet..."):
                    try:
                        xls = pd.ExcelFile(working_file)
                        sheet_names = xls.sheet_names
                    except Exception as e:
                        st.error("Failed to read working sheet Excel structure: " + str(e))
                        st.stop()
            
                # 3. Perform comparison if sheets are found
                sku_sheet_name = None
                pid_sheet_name = None
                for name in sheet_names:
                    name_lower = name.lower().strip()
                    if "sku" in name_lower or "lazada" in name_lower or "zalora" in name_lower:
                        sku_sheet_name = name
                    elif "pid" in name_lower or "shopee" in name_lower or "tiktok" in name_lower:
                        pid_sheet_name = name
            
                has_sku = sku_sheet_name is not None
                has_pid = pid_sheet_name is not None
            
                if not has_sku and not has_pid:
                    st.error("The uploaded file does not contain 'SKU Level Validation' (or SKU Validation) or 'PID Level Validation' (or PID Validation) sheets. Found sheets: " + ", ".join(sheet_names))
                    st.stop()
                
                # Helper functions for standardizing working sheet format
                def standardize_columns(df):
                    mapping = {
                        "sellersku": "Seller SKU",
                        "seller sku": "Seller SKU",
                        "ecom (yes/no)": "e-com (Yes/No)",
                        "e-com (yes/no)": "e-com (Yes/No)",
                        "ecom(yes/no)": "e-com (Yes/No)",
                        "graas status": "TC Status",
                        "tc status": "TC Status",
                        "final status (t/f)": "Final Check",
                        "final check": "Final Check",
                        "final status": "Final Status",
                        "stock check": "Stock Check",
                        "max setup": "Max Setup",
                        "update 0": "Update 0",
                    }
                    new_cols = {}
                    for col in df.columns:
                        norm_col = str(col).strip().lower()
                        if norm_col in mapping:
                            new_cols[col] = mapping[norm_col]
                        else:
                            cleaned_col = norm_col.replace(" ", "").replace("-", "").replace("_", "")
                            matched = False
                            for k, v in mapping.items():
                                cleaned_k = k.replace(" ", "").replace("-", "").replace("_", "")
                                if cleaned_col == cleaned_k:
                                    new_cols[col] = v
                                    matched = True
                                    break
                            if not matched:
                                new_cols[col] = col
                    return df.rename(columns=new_cols)

                def prepare_working_df(working_df, correct_df, sheet_name, country):
                    working_df = standardize_columns(working_df)
                
                    # If Marketplace column is missing, populate it using correct_df mapping
                    if "Marketplace" not in working_df.columns:
                        if "Seller SKU" in working_df.columns and not correct_df.empty and "Seller SKU" in correct_df.columns:
                            sku_to_mp = dict(zip(correct_df["Seller SKU"], correct_df["Marketplace"]))
                            working_df["Marketplace"] = working_df["Seller SKU"].map(sku_to_mp)
                        else:
                            working_df["Marketplace"] = None
                    
                        fallback_mp = "Unknown"
                        sheet_lower = sheet_name.lower()
                        if "lazada" in sheet_lower:
                            fallback_mp = f"Lazada {country}"
                        elif "zalora" in sheet_lower:
                            fallback_mp = f"Zalora {country}"
                        elif "shopee" in sheet_lower:
                            fallback_mp = f"Shopee {country}"
                        elif "tiktok" in sheet_lower:
                            fallback_mp = "TikTok MY"
                    
                        working_df["Marketplace"] = working_df["Marketplace"].fillna(fallback_mp)
                    return working_df

                # Helper function for values matching
                def values_match_fast(val1, val2):
                    if val1 is val2:
                        return True
                
                    is_nan1 = (val1 is None or val1 != val1 or val1 == "nan" or val1 == "NaN")
                    is_nan2 = (val2 is None or val2 != val2 or val2 == "nan" or val2 == "NaN")
                
                    if is_nan1 and is_nan2:
                        return True
                    if is_nan1 or is_nan2:
                        return False
                    
                    s1 = str(val1).strip()
                    s2 = str(val2).strip()
                    if s1 == s2:
                        return True
                    
                    s1_lower = s1.lower()
                    s2_lower = s2.lower()
                    if s1_lower == s2_lower:
                        return True
                    
                    try:
                        f1 = float(s1.replace(",", ""))
                        f2 = float(s2.replace(",", ""))
                        if abs(f1 - f2) < 1e-5:
                            return True
                    except ValueError:
                        pass
                    return False

                def perform_qc_comparison(working_df, correct_df, key_cols, compare_cols):
                    working_df = working_df.copy()
                    correct_df = correct_df.copy()
                
                    # Verify columns exist
                    for col in key_cols:
                        if col not in working_df.columns:
                            return None, f"Missing key column '{col}' in working sheet."
                        if col not in correct_df.columns:
                            return None, f"Missing key column '{col}' in computed sheet."
                        
                    # Standardize keys
                    for col in key_cols:
                        working_df[col] = working_df[col].astype(str).str.strip()
                        correct_df[col] = correct_df[col].astype(str).str.strip()
                    
                    working_df["_merge_key"] = working_df[key_cols].agg("||".join, axis=1)
                    correct_df["_merge_key"] = correct_df[key_cols].agg("||".join, axis=1)
                
                    # Deduplicate merge keys
                    working_df = working_df.drop_duplicates(subset=["_merge_key"])
                    correct_df = correct_df.drop_duplicates(subset=["_merge_key"])
                
                    working_keys = set(working_df["_merge_key"])
                    correct_keys = set(correct_df["_merge_key"])
                
                    missing_in_working = correct_df[~correct_df["_merge_key"].isin(working_keys)].copy()
                    extra_in_working = working_df[~working_df["_merge_key"].isin(correct_keys)].copy()
                
                    common_keys = working_keys.intersection(correct_keys)
                
                    w_indexed = working_df.set_index("_merge_key")
                    c_indexed = correct_df.set_index("_merge_key")
                
                    # Use fast dict mapping to bypass pandas .loc indexing overhead in python loop
                    w_dict = w_indexed.to_dict(orient="index")
                    c_dict = c_indexed.to_dict(orient="index")
                
                    mismatches = []
                    cols_to_compare = [c for c in compare_cols if c in working_df.columns and c in correct_df.columns]
                
                    for key in common_keys:
                        w_row = w_dict[key]
                        c_row = c_dict[key]
                    
                        row_diff = {}
                        for col in cols_to_compare:
                            w_val = w_row[col]
                            c_val = c_row[col]
                            if not values_match_fast(w_val, c_val):
                                row_diff[col] = (w_val, c_val)
                            
                        if row_diff:
                            disp_vals = {col: w_row[col] for col in key_cols}
                            mismatches.append({
                                **disp_vals,
                                "diffs": row_diff
                            })
                        
                    return {
                        "mismatches": mismatches,
                        "missing_in_working": missing_in_working,
                        "extra_in_working": extra_in_working,
                        "total_checked": len(common_keys)
                    }, None

                qc_sheets = {}
                st.session_state["qc_has_sku"] = has_sku
                st.session_state["qc_has_pid"] = has_pid

                # SKU Validation Audit
                if has_sku:
                    with st.spinner("Running SKU Validation correct logic..."):
                        try:
                            correct_sku = run_sku_validation(data, country)
                            working_sku = pd.read_excel(working_file, sheet_name=sku_sheet_name)
                            working_sku = prepare_working_df(working_sku, correct_sku, sku_sheet_name, country)
                        except Exception as e:
                            st.error("SKU Validation Load Error: " + str(e))
                            st.stop()
                
                    if correct_sku.empty:
                        st.warning("No calculated results for SKU Validation (Lazada/Zalora raw files are empty).")
                    elif working_sku.empty:
                        st.warning("The uploaded SKU Validation sheet is empty.")
                    else:
                        if "SellerSku" in correct_sku.columns:
                            correct_sku = correct_sku.rename(columns={"SellerSku": "Seller SKU"})
                        
                        sku_cols = ["TC SKU", "Article No", "MP Status", "TC Status", "e-com (Yes/No)", "Launch Date", "Exclusion", "ECOM Status", "MP Stock", "TC Stock", "Reserved Stock", "Max 0", "Final Status", "Comments", "Final Check", "Stock Check", "Remarks", "Max Setup", "Update 0"]
                        sku_res, err = perform_qc_comparison(
                            working_df=working_sku,
                            correct_df=correct_sku,
                            key_cols=["Marketplace", "Seller SKU"],
                            compare_cols=sku_cols
                        )
                    
                        if err:
                            st.error(f"SKU Comparison Error: {err}")
                        else:
                            m_rows = []
                            for m in sku_res["mismatches"]:
                                for col, (w_val, c_val) in m["diffs"].items():
                                    m_rows.append({
                                        "Marketplace": m["Marketplace"],
                                        "Seller SKU": m["Seller SKU"],
                                        "Field Name": col,
                                        "Team Value (Working)": w_val,
                                        "Expected Value (Computed)": c_val
                                    })
                            sku_mismatch_df = pd.DataFrame(m_rows) if m_rows else pd.DataFrame(columns=["Marketplace", "Seller SKU", "Field Name", "Team Value (Working)", "Expected Value (Computed)"])
                            sku_missing_df = sku_res["missing_in_working"][["Marketplace", "Seller SKU", "Final Status"]].copy() if not sku_res["missing_in_working"].empty else pd.DataFrame(columns=["Marketplace", "Seller SKU", "Final Status"])
                            sku_extra_df = sku_res["extra_in_working"][["Marketplace", "Seller SKU", "Final Status"]].copy() if not sku_res["extra_in_working"].empty else pd.DataFrame(columns=["Marketplace", "Seller SKU", "Final Status"])
                        
                            qc_sheets["SKU Value Mismatches"] = sku_mismatch_df
                            qc_sheets["SKU Missing Rows"] = sku_missing_df
                            qc_sheets["SKU Extra Rows"] = sku_extra_df

                            # Save values to session state
                            st.session_state["qc_sku_total_checked"] = sku_res["total_checked"]
                            st.session_state["qc_sku_m_count"] = len(sku_res["mismatches"])
                            st.session_state["qc_sku_missing_count"] = len(sku_missing_df)
                            st.session_state["qc_sku_extra_count"] = len(sku_extra_df)
                            st.session_state["qc_sku_m_df"] = sku_mismatch_df
                            st.session_state["qc_sku_missing_df"] = sku_missing_df
                            st.session_state["qc_sku_extra_df"] = sku_extra_df

                # PID Validation Audit
                if has_pid:
                    with st.spinner("Running PID Validation correct logic..."):
                        try:
                            correct_pid = run_pid_validation(data, country)
                            working_pid = pd.read_excel(working_file, sheet_name=pid_sheet_name)
                            working_pid = prepare_working_df(working_pid, correct_pid, pid_sheet_name, country)
                        except Exception as e:
                            st.error("PID Validation Load Error: " + str(e))
                            st.stop()
                        
                    if correct_pid.empty:
                        st.warning("No calculated results for PID Validation (Shopee/TikTok raw files are empty).")
                    elif working_pid.empty:
                        st.warning("The uploaded PID Validation sheet is empty.")
                    else:
                        if "SellerSku" in correct_pid.columns:
                            correct_pid = correct_pid.rename(columns={"SellerSku": "Seller SKU"})
                        
                        pid_cols = ["TC SKU", "Product ID", "Article No", "MP Status", "TC Status", "e-com (Yes/No)", "Launch Date", "Exclusion", "ECOM Status", "Final Status", "Comments", "Final Check", "Dual Status", "Consolidated SUM QTY", "MP Stock", "TC Stock", "Reserved Stock", "Max 0", "Stock Check", "Remarks", "Max Setup", "Update 0"]
                        pid_res, err = perform_qc_comparison(
                            working_df=working_pid,
                            correct_df=correct_pid,
                            key_cols=["Marketplace", "Seller SKU"],
                            compare_cols=pid_cols
                        )
                    
                        if err:
                            st.error(f"PID Comparison Error: {err}")
                        else:
                            m_rows = []
                            for m in pid_res["mismatches"]:
                                for col, (w_val, c_val) in m["diffs"].items():
                                    m_rows.append({
                                        "Marketplace": m["Marketplace"],
                                        "Seller SKU": m["Seller SKU"],
                                        "Field Name": col,
                                        "Team Value (Working)": w_val,
                                        "Expected Value (Computed)": c_val
                                    })
                            pid_mismatch_df = pd.DataFrame(m_rows) if m_rows else pd.DataFrame(columns=["Marketplace", "Seller SKU", "Field Name", "Team Value (Working)", "Expected Value (Computed)"])
                            pid_missing_df = pid_res["missing_in_working"][["Marketplace", "Seller SKU", "Final Status"]].copy() if not pid_res["missing_in_working"].empty else pd.DataFrame(columns=["Marketplace", "Seller SKU", "Final Status"])
                            pid_extra_df = pid_res["extra_in_working"][["Marketplace", "Seller SKU", "Final Status"]].copy() if not pid_res["extra_in_working"].empty else pd.DataFrame(columns=["Marketplace", "Seller SKU", "Final Status"])
                        
                            qc_sheets["PID Value Mismatches"] = pid_mismatch_df
                            qc_sheets["PID Missing Rows"] = pid_missing_df
                            qc_sheets["PID Extra Rows"] = pid_extra_df

                            # Save values to session state
                            st.session_state["qc_pid_total_checked"] = pid_res["total_checked"]
                            st.session_state["qc_pid_m_count"] = len(pid_res["mismatches"])
                            st.session_state["qc_pid_missing_count"] = len(pid_missing_df)
                            st.session_state["qc_pid_extra_count"] = len(pid_extra_df)
                            st.session_state["qc_pid_m_df"] = pid_mismatch_df
                            st.session_state["qc_pid_missing_df"] = pid_missing_df
                            st.session_state["qc_pid_extra_df"] = pid_extra_df

                # Save the compiled QC report Excel file to disk
                if qc_sheets:
                    with st.spinner("Generating and saving QC Audit report..."):
                        try:
                            today = datetime.today().strftime("%Y-%m-%d")
                            qc_fname = f"QC_Audit_Report_{country}_{today}.xlsx"
                            qc_fpath = _write_qc_report(qc_sheets, qc_fname)
                            st.session_state["qc_report_path"] = qc_fpath
                            st.session_state["qc_report_fname"] = qc_fname
                        except Exception as e:
                            st.error("Failed to generate QC Excel report: " + str(e))

                del st.session_state["lqc_gsheet_error"]
            gsheet_urls = [url.strip() for url in lqc_gsheet_urls_str.split("\n") if url.strip()]
            errors = []
            private_error_found = False
            for i, url in enumerate(gsheet_urls):
                try:
                    with st.spinner(f"Downloading Google Sheet #{i+1}..."):
                        df = lqc_load_google_sheet(url, channel=lqc_channel)
                        id_match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
                        display_name = f"Google Sheet ({id_match.group(1)[:8]}...)" if id_match else f"Google Sheet #{i+1}"
                        upload_dfs[display_name] = df
                except Exception as e:
                    err_str = str(e)
                    errors.append(f"Sheet #{i+1}: {err_str}")
                    if "401" in err_str or "unauthorized" in err_str.lower() or "forbidden" in err_str.lower() or "403" in err_str:
                        private_error_found = True
            
            if errors:
                st.session_state["lqc_gsheet_error"] = " | ".join(errors)
                if private_error_found:
                    st.error("""
                    🔒 **Private Google Sheet detected (HTTP 401/403):**
                    
                    One or more Google Sheets do not have permission to be fetched.
                    
                    **To resolve this:**
                    1. In your Google Sheet, click the blue **Share** button in the top right.
                    2. Under *General Access*, change it from *Restricted* to **"Anyone with the link can view"** (Viewer access).
                    3. Copy the new link and paste it here.
                    
                    *Alternatively:* Go to Google Sheets ➔ **File** ➔ **Download** ➔ **Microsoft Excel (.xlsx)** or **Comma Separated Values (.csv)**, and upload it using the Upload Target Sheets (Excel/CSV) section above.
                    """)
                else:
                    st.error(f"❌ **Error downloading Google Sheet(s):**\n" + "\n".join([f"- {err}" for err in errors]))
            else:
                if "lqc_gsheet_error" in st.session_state:
                    del st.session_state["lqc_gsheet_error"]

        target_loaded = len(upload_dfs) > 0
        gsheet_error = st.session_state.get("lqc_gsheet_error")
        show_setup_dashboard = not (content_loaded and zecom_loaded and target_loaded)

        if show_setup_dashboard:
            st.markdown("---")
            st.subheader("🛠️ QC Validation Setup Dashboard")
            st.markdown("Please configure the required files and parameters in the sidebar to begin. Below is the current configuration status:")

            card_cols = st.columns(3)
            with card_cols[0]:
                st.markdown("""
                <div class="metric-card" style="border-top: 4px solid #d946ef; height: 100%;">
                    <div class="metric-title">1. Target Listings Sheet</div>
                """, unsafe_allow_html=True)
                if target_loaded:
                    fn_list = list(upload_dfs.keys())
                    fn_str = ", ".join(fn_list)
                    st.markdown(f"**Status**: ✅ Loaded<br><span style='font-size:0.85rem; color:#a7f3d0;'>{fn_str}</span>", unsafe_allow_html=True)
                elif gsheet_error:
                    st.markdown("**Status**: ❌ Error<br><span style='font-size:0.85rem; color:#fca5a5;'>Failed to download Google Sheet</span>", unsafe_allow_html=True)
                else:
                    st.markdown("**Status**: ❌ Missing<br><span style='font-size:0.85rem; color:#cbd5e1;'>Upload Target Sheet in sidebar</span>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with card_cols[1]:
                st.markdown("""
                <div class="metric-card" style="border-top: 4px solid #3b82f6; height: 100%;">
                    <div class="metric-title">2. Required References</div>
                """, unsafe_allow_html=True)
                if content_loaded:
                    st.markdown(f"**Content File**: ✅ Loaded<br><span style='font-size:0.8rem; color:#a7f3d0;'>{lqc_content_file.name}</span>", unsafe_allow_html=True)
                else:
                    st.markdown("**Content File**: ❌ Missing", unsafe_allow_html=True)
                st.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)
                if zecom_loaded:
                    st.markdown(f"**zEcom File**: ✅ Loaded<br><span style='font-size:0.8rem; color:#a7f3d0;'>{lqc_zecom_file.name}</span>", unsafe_allow_html=True)
                else:
                    st.markdown("**zEcom File**: ❌ Missing", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with card_cols[2]:
                st.markdown(f"""
                <div class="metric-card" style="border-top: 4px solid #10b981; height: 100%;">
                    <div class="metric-title">3. Channel & Settings</div>
                    <div><b>Channel</b>: <span style="color:#6ee7b7;">{lqc_channel}</span></div>
                    <div style="margin-top: 6px;"><b>Stage</b>: <span style="color:#6ee7b7;">{lqc_qc_stage}</span></div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            if gsheet_error:
                if "401" in gsheet_error or "unauthorized" in gsheet_error.lower() or "forbidden" in gsheet_error.lower() or "403" in gsheet_error:
                    st.error(f"""
                    🔒 **Private Google Sheet detected (HTTP 401/403):**
                    The app does not have permission to fetch this private sheet.
                    **How to resolve this:**
                    1. In your Google Sheet, click the blue **Share** button in the top right.
                    2. Under *General Access*, change it from *Restricted* to **"Anyone with the link can view"** (Viewer access).
                    3. Copy the new link and paste it in the sidebar.
                    *Alternatively:* Go to Google Sheets ➔ **File** ➔ **Download** ➔ **Microsoft Excel (.xlsx)** or **Comma Separated Values (.csv)**, and upload it using the Upload Target Sheets (Excel/CSV) section in the sidebar.
                    **Raw Error:** `{gsheet_error}`
                    """)
                else:
                    st.error(f"❌ **Error downloading Google Sheet:** {gsheet_error}\n\nPlease verify that the URL is correct and public 'Anyone with the link can view'.")

            if not target_loaded and not gsheet_error:
                st.info("💡 **Getting Started:** Use the sidebar control panel to upload your listing files. You will need a target listings file and reference content/zEcom files.")
            if target_loaded and not (content_loaded and zecom_loaded):
                st.warning("⚠️ **Reference Files Needed:** You have uploaded the target sheet, but you must upload both the **Content File** and **zEcom File** in the sidebar to run validations. Since they are at the top of the sidebar, you may need to **scroll up** in the sidebar to find their file uploaders.")

        if target_loaded:
            st.subheader("📋 Column Mapping Alignment (Upload Sheet)")
            st.markdown("Align the columns in your uploaded target sheet to the standard QC validation fields:")

            all_headers = []
            for fn, df in upload_dfs.items():
                all_headers.extend(df.columns.tolist())
            all_headers = sorted(list(set(all_headers)))

            auto_maps = lqc_auto_map_columns(all_headers)
            fields_to_map = list(LQC_CANONICAL_LABELS.keys())
            if lqc_qc_stage == "Internal QC":
                fields_to_map = [f for f in fields_to_map if f not in ["images", "size_chart"]]

            cols = st.columns(3)
            manual_mapping = {}

            for i, canonical in enumerate(fields_to_map):
                col_selector = cols[i % 3]
                default_val = auto_maps.get(canonical)
                options = ["-- Skip / Missing --"] + all_headers
                default_idx = 0
                if default_val in all_headers:
                    default_idx = options.index(default_val)
                with col_selector:
                    mapped_col = st.selectbox(
                        f"{LQC_CANONICAL_LABELS[canonical]}",
                        options=options,
                        index=default_idx,
                        key=f"lqc_map_{canonical}"
                    )
                    manual_mapping[canonical] = None if mapped_col == "-- Skip / Missing --" else mapped_col

            st.markdown("<br>", unsafe_allow_html=True)
            refs_missing = not (content_loaded and zecom_loaded)

            if refs_missing:
                st.warning("⚠️ Upload **Content File** and **zEcom File** in the sidebar to unlock the validation button.")
                st.button("🚀 Run QC Validation", type="primary", use_container_width=True, disabled=True, key="lqc_run_disabled")
            else:
                if st.button("🚀 Run QC Validation", type="primary", use_container_width=True, key="lqc_run_enabled_btn"):
                    with st.spinner("Loading references and running validations..."):
                        try:
                            content_df = lqc_load_content(lqc_content_file)
                            zecom_df = lqc_load_zecom(lqc_zecom_file, lqc_country)
                            
                            all_standardized = []
                            for fn, df in upload_dfs.items():
                                std_df = lqc_standardize_dataframe(df, manual_mapping, source_name=fn)
                                all_standardized.append(std_df)
                            combined_df = pd.concat(all_standardized, ignore_index=True)
                            
                            live_df = None
                            if lqc_qc_stage == "Post QC":
                                if not lqc_live_files:
                                    st.error("⚠️ Please upload at least one Live Store Marketplace Report in the sidebar first under 'Upload Live Reports'.")
                                    st.stop()
                                live_df = lqc_process_live_files(lqc_live_files, lqc_channel)
                                if live_df.empty:
                                    st.error("⚠️ Could not parse any valid listing data from the Live Marketplace Reports.")
                                    st.stop()
                            
                            exc_df, val_df, logs = lqc_validate_dataframe(
                                combined_df, 
                                qc_stage=lqc_qc_stage,
                                channel=lqc_channel,
                                content_df=content_df,
                                zecom_df=zecom_df,
                                check_live_images=lqc_check_live_images,
                                allowed_genders=lqc_custom_genders,
                                allowed_statuses=lqc_custom_statuses,
                                live_df=live_df
                            )
                            
                            st.session_state.lqc_val_df = val_df
                            st.session_state.lqc_exc_df = exc_df
                            st.session_state.lqc_logs = logs
                            st.session_state.lqc_ran_validation = True
                            st.session_state.lqc_ran_comparison = False
                            
                        except Exception as e:
                            st.error(f"Error executing validation run: {e}")
                            import traceback
                            st.error(traceback.format_exc())

            if st.session_state.lqc_ran_validation:
                st.markdown("---")
                st.subheader("📊 Validation Results Dashboard")
                
                val_df = st.session_state.lqc_val_df
                exc_df = st.session_state.lqc_exc_df
                logs = st.session_state.lqc_logs
                
                total_records = len(val_df)
                total_skus = val_df["sku"].nunique() if "sku" in val_df.columns else 0
                total_articles = val_df["article_number"].nunique() if "article_number" in val_df.columns else 0
                total_exceptions = len(exc_df) if not exc_df.empty else 0
                
                kpi_cols = st.columns(3)
                with kpi_cols[0]:
                    st.markdown(f'<div class="metric-card metric-total"><div class="metric-title">Total Rows Audited</div><div class="metric-value">{total_records}</div></div>', unsafe_allow_html=True)
                with kpi_cols[1]:
                    st.markdown(f'<div class="metric-card metric-passed" style="border-left-color: #38bdf8 !important;"><div class="metric-title" style="color: #38bdf8 !important;">Total Unique SKUs</div><div class="metric-value" style="color: #38bdf8 !important;">{total_skus}</div></div>', unsafe_allow_html=True)
                with kpi_cols[2]:
                    st.markdown(f'<div class="metric-card metric-warnings" style="border-left-color: #a78bfa !important;"><div class="metric-title" style="color: #a78bfa !important;">Total Unique Articles</div><div class="metric-value" style="color: #a78bfa !important;">{total_articles}</div></div>', unsafe_allow_html=True)
                    
                if lqc_qc_stage == "Post QC":
                    tab_list = st.tabs(["📊 Dashboard & Data View", "🔄 Live Listing Sync Audit"])
                    container_dashboard = tab_list[0]
                    container_live = tab_list[1]
                else:
                    container_dashboard = st.container()
                    container_live = None

                with container_dashboard:
                    child_df = val_df[val_df["sku"].fillna("").astype(str).str.strip().str.match(r'^\d{13}$')]
                    no_status_count = sum(child_df["Zeocm Status"] != "Yes")
                    status_ok = no_status_count == 0
                    status_badge = '<span class="qc-status-ok">OK</span>' if status_ok else '<span class="qc-status-mismatch">Mismatch</span>'
                    status_text = "Yes for all articles" if status_ok else f"{no_status_count} records are 'No' or 'Not Found'"
                    
                    launch_excs = exc_df[exc_df["Field"] == "Launch Date"] if not exc_df.empty else pd.DataFrame()
                    launch_ok = launch_excs.empty
                    launch_badge = '<span class="qc-status-ok">OK</span>' if launch_ok else '<span class="qc-status-mismatch">Mismatch</span>'
                    launch_rows = launch_excs.groupby(["Source File", "Row Number"]).ngroups if not launch_ok else 0
                    launch_text = "All launch dates are past/current" if launch_ok else f"{launch_rows} future launch dates flagged"
                    
                    gender_excs = exc_df[
                        (exc_df["Field"] == "Gender") | 
                        ((exc_df["Field"] == "Product Name") & exc_df["Message"].str.contains("gender", case=False, na=False))
                    ] if not exc_df.empty else pd.DataFrame()
                    gender_ok = gender_excs.empty
                    gender_badge = '<span class="qc-status-ok">OK</span>' if gender_ok else '<span class="qc-status-mismatch">Mismatch</span>'
                    gender_rows = gender_excs.groupby(["Source File", "Row Number"]).ngroups if not gender_ok else 0
                    gender_text = "All genders compatible" if gender_ok else f"{gender_rows} gender mismatches found"
                    
                    color_excs = exc_df[exc_df["Field"] == "Color Name"] if not exc_df.empty else pd.DataFrame()
                    color_ok = color_excs.empty
                    color_badge = '<span class="qc-status-ok">OK</span>' if color_ok else '<span class="qc-status-mismatch">Mismatch</span>'
                    color_rows = color_excs.groupby(["Source File", "Row Number"]).ngroups if not color_ok else 0
                    color_text = "All color names match Content file" if color_ok else f"{color_rows} color mismatches found"
                    
                    size_excs = exc_df[exc_df["Field"] == "Size"] if not exc_df.empty else pd.DataFrame()
                    size_ok = size_excs.empty
                    size_badge = '<span class="qc-status-ok">OK</span>' if size_ok else '<span class="qc-status-mismatch">Mismatch</span>'
                    size_rows = size_excs.groupby(["Source File", "Row Number"]).ngroups if not size_ok else 0
                    size_text = "All sizes match Content file references" if size_ok else f"{size_rows} size mismatches found"
                    
                    price_excs = exc_df[exc_df["Field"] == "Price"] if not exc_df.empty else pd.DataFrame()
                    price_ok = price_excs.empty
                    price_badge = '<span class="qc-status-ok">OK</span>' if price_ok else '<span class="qc-status-mismatch">Mismatch</span>'
                    price_rows = price_excs.groupby(["Source File", "Row Number"]).ngroups if not price_ok else 0
                    price_text = "All prices match zEcom RRP" if price_ok else f"{price_rows} price mismatches found"
                    
                    qty_excs = exc_df[exc_df["Field"] == "Quantity"] if not exc_df.empty else pd.DataFrame()
                    qty_ok = qty_excs.empty
                    qty_badge = '<span class="qc-status-ok">OK</span>' if qty_ok else '<span class="qc-status-mismatch">Mismatch</span>'
                    qty_rows = qty_excs.groupby(["Source File", "Row Number"]).ngroups if not qty_ok else 0
                    qty_text = "Quantity is 0 for all items" if qty_ok else f"{qty_rows} non-zero quantity items found"
                    
                    qc_table_html = f"""
                    <table class="qc-table">
                        <thead>
                            <tr>
                                <th>Check Name</th>
                                <th>Target Condition</th>
                                <th>Actual Status</th>
                                <th style="text-align: center; width: 120px;">Result</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td style="font-weight: 600;">zEcom Status Check</td>
                                <td>Should be 'Yes' for all articles</td>
                                <td>{status_text}</td>
                                <td style="text-align: center;">{status_badge}</td>
                            </tr>
                            <tr>
                                <td style="font-weight: 600;">Launch Date Check</td>
                                <td>Should not be in the future</td>
                                <td>{launch_text}</td>
                                <td style="text-align: center;">{launch_badge}</td>
                            </tr>
                            <tr>
                                <td style="font-weight: 600;">Gender Mismatch Check</td>
                                <td>Matches Content file gender reference</td>
                                <td>{gender_text}</td>
                                <td style="text-align: center;">{gender_badge}</td>
                            </tr>
                            <tr>
                                <td style="font-weight: 600;">Color Name Check</td>
                                <td>Matches Content file Color Name reference</td>
                                <td>{color_text}</td>
                                <td style="text-align: center;">{color_badge}</td>
                            </tr>
                            <tr>
                                <td style="font-weight: 600;">Size Check</td>
                                <td>Matches Content size (UK/US/Rus) reference</td>
                                <td>{size_text}</td>
                                <td style="text-align: center;">{size_badge}</td>
                            </tr>
                            <tr>
                                <td style="font-weight: 600;">Price Check</td>
                                <td>Matches zEcom RRP reference price</td>
                                <td>{price_text}</td>
                                <td style="text-align: center;">{price_badge}</td>
                            </tr>
                            <tr>
                                <td style="font-weight: 600;">Quantity Check</td>
                                <td>Quantity must be exactly 0 for all items</td>
                                <td>{qty_text}</td>
                                <td style="text-align: center;">{qty_badge}</td>
                            </tr>
                        </tbody>
                    </table>
                    """
                    
                    st.markdown("### 📋 QC Quality Checklist")
                    st.markdown(qc_table_html, unsafe_allow_html=True)
                    
                    st.markdown("### 🔍 Validated Dataset Preview")
                    preview_df = val_df.copy()
                    target_headers = {
                        "sku": "Seller SKU",
                        "article_number": "Article No",
                        "Zeocm Status": "Zeocm Status",
                        "launch_date": "Launch Date",
                        "gender": "Gender",
                        "product_name": "Product Name",
                        "Gender Check": "Gender Check",
                        "color_name": "Color Name",
                        "ref_color_name": "Reference Color Name",
                        "Color Check": "Color Check",
                        "size": "Size",
                        "ref_size": "Reference Size",
                        "Size Check": "Size Check",
                        "price": "RRP",
                        "ref_rrp": "Reference RRP",
                        "RRP Check": "RRP Check",
                        "quantity": "Quantity"
                    }
                    for col in target_headers.keys():
                        if col not in preview_df.columns:
                            preview_df[col] = ""
                    ordered_cols = list(target_headers.keys())
                    preview_df = preview_df[ordered_cols]
                    preview_df = preview_df.rename(columns=target_headers)
                    st.dataframe(preview_df.head(500), use_container_width=True, hide_index=True)
                    
                    st.markdown("#### 📥 Download Validation Reports")
                    excel_data = lqc_generate_qc_excel_report(val_df, exc_df, lqc_qc_stage)
                    
                    st.download_button(
                        label="📥 Download Detailed Excel QC Report",
                        data=excel_data,
                        file_name=f"Listing_QC_Report_{lqc_qc_stage}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key="lqc_download_qc_report_btn"
                    )

                if container_live is not None:
                    with container_live:
                        st.markdown("#### 🔄 Live Store Listing Sync Audit")
                        st.markdown("Compare your uploaded listing sheet against live store data.")
                        
                        if not lqc_live_files:
                            st.info("💡 Please upload Live marketplace files (Excel, CSV, or ZIP) in the sidebar to run the sync audit.")
                        else:
                            if st.button("🔄 Execute Comparison Audit", type="primary", key="lqc_btn_run_compare"):
                                with st.spinner("Consolidating live reports and running comparison..."):
                                    try:
                                        consolidated_live = lqc_process_live_files(lqc_live_files, lqc_channel)
                                        if consolidated_live.empty:
                                            st.error("Could not parse any valid listing data from the uploaded live files. Please verify the headers and formats.")
                                        else:
                                            st.success(f"✅ Successfully loaded and consolidated {len(consolidated_live)} live listing variants.")
                                            
                                            standardized_source = val_df.copy()
                                            
                                            comp_df, comp_metrics = lqc_compare_source_and_live(
                                                standardized_source,
                                                consolidated_live,
                                                match_column="sku"
                                            )
                                            
                                            st.session_state.lqc_comp_df = comp_df
                                            st.session_state.lqc_comp_metrics = comp_metrics
                                            st.session_state.lqc_ran_comparison = True
                                    except Exception as e:
                                        st.error(f"Comparison run failed: {e}")
                                        import traceback
                                        st.error(traceback.format_exc())
                                        
                            if st.session_state.lqc_ran_comparison:
                                st.markdown("---")
                                st.markdown("##### Comparison Summary")
                                
                                comp_df = st.session_state.lqc_comp_df
                                comp_metrics = st.session_state.lqc_comp_metrics
                                
                                c_kpis = st.columns(5)
                                labels = list(comp_metrics.keys())
                                vals = list(comp_metrics.values())
                                theme_colors = ["#00c5c8", "#34d399", "#f87171", "#fbbf24", "#a78bfa"]
                                
                                for idx in range(len(labels)):
                                    with c_kpis[idx]:
                                        st.markdown(f'<div class="metric-card" style="border-top: 4px solid {theme_colors[idx]};"><div class="metric-title">{labels[idx]}</div><div class="metric-value" style="color: {theme_colors[idx]};">{vals[idx]}</div></div>', unsafe_allow_html=True)
                                
                                st.markdown("##### Detailed Discrepancy Table")
                                mismatches_only = comp_df[comp_df["Match Status"] != "Passed"]
                                
                                if mismatches_only.empty:
                                    st.success("🎉 Perfect Sync! All compared attributes match perfectly between uploaded sheet and live store.")
                                else:
                                    st.markdown(f"Found **{len(mismatches_only)}** discrepancies between sheets:")
                                    st.dataframe(mismatches_only, use_container_width=True, hide_index=True)
                                
                                comp_excel_data = lqc_generate_comparison_excel_report(comp_df, comp_metrics)
                                st.download_button(
                                    label="📥 Download Live Listing Comparison Excel Report",
                                    data=comp_excel_data,
                                    file_name=f"Live_Listing_Sync_Audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    use_container_width=True,
                                    key="lqc_download_compare_report_btn"
                                )

