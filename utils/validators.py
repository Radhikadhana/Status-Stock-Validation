import re
import pandas as pd
import numpy as np


def _safe_num(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _safe_str(val):
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip()


def _clean_sku(val):
    s = _safe_str(val)
    if re.fullmatch(r'\d+\.0', s):
        s = s[:-2]
    return s



def _normalise_status(status):
    s = _safe_str(status).lower()
    if s in ("active", "1", "enabled", "yes", "y", "live", "listed"):
        return "Active"
    if s in ("inactive", "0", "disabled", "no", "n", "delisted",
             "unlisted", "deleted", "removed"):
        return "Inactive"
    return _safe_str(status)


def _standardise_raw_ecom_series(ser):
    s = ser.fillna("").astype(str).str.strip().str.upper()
    yes_mask = s.isin(["YES", "Y", "ACTIVE"])
    no_mask = s.isin(["NO", "N", "INACTIVE"])
    off_mask = s == "OFF"
    na_mask = s.isin(["#N/A", ""])
    default_vals = ser.fillna("").astype(str).str.strip()
    return np.select(
        [yes_mask, no_mask, off_mask, na_mask],
        ["Yes", "No", "OFF", "#N/A"],
        default=default_vals
    )


def _is_valid_sku(sku):
    """Seller SKU must be exactly 13 digits."""
    return bool(re.fullmatch(r'\d{13}', _safe_str(sku)))


def _normalise_article_no(val):
    """
    Normalise Article No for cross-file matching.
    Strips all non-alphanumeric characters (spaces, hyphens, underscores)
    and converts to uppercase for absolute matching tolerance.
    """
    s = _safe_str(val)
    if not s:
        return ""
    s = s.strip().upper()
    if s.endswith(".0"):
        s = s[:-2]
    s = re.sub(r'[^A-Z0-9]+', '', s)
    return s


# ── Lookup builders ───────────────────────────────────────────────────────────

def _build_article_map(content):
    """SKU -> Article No (preserves original format). Tries multiple candidate columns."""
    article_map = {}
    if content.empty or "SKU" not in content.columns:
        return article_map
    art_col = next(
        (c for c in ["Article No", "ArticleNo", "Article Number",
                      "Color_No", "Color_No.1", "Style#", "STYLE#",
                      "Style #", "STYLE #"]
         if c in content.columns),
        next((c for c in content.columns
              if "article" in c.lower() or "color" in c.lower()
              or "style" in c.lower()), "")
    )
    if art_col:
        skus = content["SKU"].tolist()
        art_vals = content[art_col].tolist()
        for sku, art in zip(skus, art_vals):
            sku_s = _safe_str(sku)
            if sku_s:
                s_art = _safe_str(art).strip()
                if s_art.endswith(".0"):
                    s_art = s_art[:-2]
                article_map[sku_s] = s_art
    return article_map


def _build_ecom_map(zecom, mp_name):
    """Article No -> Ecom Status for the given marketplace."""
    ecom_map = {}
    if zecom.empty or "Article No" not in zecom.columns:
        return ecom_map
    mp_key = mp_name.split()[0].lower()
    ecom_col = next(
        (c for c in zecom.columns
         if c.startswith("Ecom_") and mp_key in c.lower()), ""
    )
    if not ecom_col:
        return ecom_map
    arts = zecom["Article No"].tolist()
    ecom_vals = zecom[ecom_col].tolist()
    for art, val in zip(arts, ecom_vals):
        art_norm = _normalise_article_no(art)
        if art_norm:
            ecom_map[art_norm] = _safe_str(val)
    return ecom_map


def _build_tc_map(tc_inv):
    if tc_inv.empty or "SKU" not in tc_inv.columns:
        return {}

    skus = tc_inv["SKU"].tolist()
    tc_skus = tc_inv["TC SKU"].tolist() if "TC SKU" in tc_inv.columns else skus
    tc_statuses = tc_inv["TC Status"].tolist() if "TC Status" in tc_inv.columns else ["Unknown"] * len(skus)
    max_0s = tc_inv["Max 0"].tolist() if "Max 0" in tc_inv.columns else ["No"] * len(skus)

    tc_map = {}
    parent_fallback = {}

    for sku, tc_sku_raw, tc_status, max_0 in zip(skus, tc_skus, tc_statuses, max_0s):
        if not sku:
            continue
        entry = {
            "TC SKU":    tc_sku_raw,
            "TC Status": tc_status,
            "Max 0":     max_0,
        }
        if "-" in sku:
            tc_map[sku] = entry
            parent_base = sku.rsplit("-", 1)[0]
            if parent_base not in tc_map:
                parent_fallback[parent_base] = entry
        else:
            if sku not in tc_map:
                tc_map[sku] = entry

    for parent, entry in parent_fallback.items():
        if parent not in tc_map:
            tc_map[parent] = entry

    return tc_map


def _build_stock_map(all_df, apply_buffer=False):
    if all_df.empty or "SKU" not in all_df.columns:
        return {}

    # Drop duplicate SKUs keeping the first, since the loop only adds when SKU is not in stock_map
    df_unique = all_df.drop_duplicates(subset=["SKU"], keep="first")
    
    # We already converted TC Stock and Reserved Stock during load_all_file, but let's make sure
    tc_stock = pd.to_numeric(df_unique["TC Stock"], errors="coerce").fillna(0.0).clip(lower=0.0)
    if apply_buffer:
        tc_stock = (tc_stock - 1.0).clip(lower=0.0)
        
    reserved_stock = pd.to_numeric(df_unique["Reserved Stock"], errors="coerce").fillna(0.0)
    
    skus = df_unique["SKU"].tolist()
    tc_stock_list = tc_stock.tolist()
    res_stock_list = reserved_stock.tolist()
    
    stock_map = {
        sku: {"TC Stock": tc, "Reserved Stock": res}
        for sku, tc, res in zip(skus, tc_stock_list, res_stock_list)
    }
    return stock_map


def _build_excl_map(exclusion):
    excl_map = {}
    if exclusion is None or exclusion.empty:
        return excl_map

    # Candidates for the Article/ALU/Color No column
    art_candidates = [
        "Article No", "ALU_No", "ALU", "Aricle No", "Article Number", "Color No", "Color_No"
    ]
    
    art_col = None
    for c in art_candidates:
        if c in exclusion.columns:
            art_col = c
            break
            
    if not art_col:
        # Fallback to case-insensitive and loose match
        for col in exclusion.columns:
            col_lower = col.lower().replace(" ", "").replace("_", "").replace("-", "")
            if col_lower in ["articleno", "aluno", "alu", "aricleno", "articlenumber", "colorno", "color_no"]:
                art_col = col
                break
                
    if not art_col:
        # Final fallback: look for any column containing "article", "style", "alu", or "color"
        for col in exclusion.columns:
            col_l = col.lower()
            if "article" in col_l or "style" in col_l or "alu" in col_l or "color" in col_l:
                art_col = col
                break

    if not art_col:
        return excl_map

    # Candidates for the Status column
    status_col = None
    for col in exclusion.columns:
        if col == "Exclusion Status":
            status_col = col
            break
    if not status_col:
        for col in exclusion.columns:
            col_l = col.lower()
            if "exclusion status" in col_l:
                status_col = col
                break
    if not status_col:
        for col in exclusion.columns:
            col_l = col.lower()
            if "status" in col_l:
                status_col = col
                break

    art_nos = exclusion[art_col].tolist()
    if status_col:
        statuses = exclusion[status_col].tolist()
    else:
        statuses = ["Inactive"] * len(art_nos)

    for raw_val, status in zip(art_nos, statuses):
        status_s = _safe_str(status)
        art = _normalise_article_no(raw_val)
        if art:
            excl_map[art] = status_s

        raw_clean = re.sub(r'\D', '', _safe_str(raw_val))
        if re.fullmatch(r'\d{13}', raw_clean):
            excl_map[raw_clean] = status_s

    return excl_map


def _build_launch_map(zecom, mp_name):
    if zecom.empty or "Article No" not in zecom.columns:
        return {}
        
    mp_lower = mp_name.lower()
    candidates = []
    if "lazada" in mp_lower or "shopee" in mp_lower:
        candidates = ["LAZ & SHP Launch Date", "Lazada & Shopee Launch Dates"]
    elif "zalora" in mp_lower:
        candidates = ["Tiktok & Zalora Launch Dates", "ZAL Launch Date", "ZAL & TK Launch Date", "ZAL & TK\nLaunch Date"]
    elif "tiktok" in mp_lower:
        candidates = ["Tiktok & Zalora Launch Dates", "ZAL & TK Launch Date", "ZAL & TK\nLaunch Date", "TKTK Launch Date"]
        
    col_name = None
    for c in candidates:
        if c in zecom.columns:
            col_name = c
            break
            
    if not col_name:
        for c in ["Launch Date", "LaunchDate", "Launch_Date"]:
            if c in zecom.columns:
                col_name = c
                break
                
    if not col_name:
        for c in zecom.columns:
            c_norm = c.lower().replace(" ", "").replace("_", "").replace("-", "")
            if "launchdate" in c_norm:
                col_name = c
                break
                
    if not col_name:
        return {}

    arts = zecom["Article No"].tolist()
    formatted_dates = pd.to_datetime(zecom[col_name], errors="coerce").dt.strftime("%Y-%m-%d").fillna("").tolist()

    launch_map = {}
    for art, formatted_ld in zip(arts, formatted_dates):
        art_norm = _normalise_article_no(art)
        if art_norm:
            launch_map[art_norm] = formatted_ld
    return launch_map


def _build_future_launch_map(zecom, mp_name):
    if zecom.empty or "Article No" not in zecom.columns:
        return {}
        
    launch_map = _build_launch_map(zecom, mp_name)
    if not launch_map:
        return {}
        
    today = pd.Timestamp.today().normalize()
    fl_map = {}
    for art, ld in launch_map.items():
        if ld:
            try:
                d = pd.to_datetime(ld)
                fl_map[art] = bool(pd.notna(d) and d > today)
            except Exception:
                fl_map[art] = False
        else:
            fl_map[art] = False
    return fl_map


def _needs_buffer(mp_name):
    """Buffer -1 stock only for Lazada PH, TikTok MY, and Zalora PH."""
    return mp_name in ("Lazada PH", "TikTok MY", "Zalora PH")


# ── Exclusion override ────────────────────────────────────────────────────────

def _apply_exclusion(article_no, tc_stock, excl_map, max_0, sku=None):
    """
    Check exclusion by Article No first, then by raw SKU (13-digit)
    as a fallback — so exclusion works even without a Content File
    bridging SKU -> Article No.
    """
    match_key = None
    if article_no and article_no in excl_map:
        match_key = article_no
    elif sku and sku in excl_map:
        match_key = sku

    if match_key is None:
        return None
    excl_status = excl_map[match_key]
    if excl_status == "Inactive":
        # If Max 0 is already Yes, no need to set max 0 again
        max_action = "" if max_0 == "Yes" else "Set max 0"
        return ("Inactive", "Inactive as per AM Request", max_action)
    if excl_status == "Active":
        if tc_stock >= 1:
            ma = "Remove max" if max_0 == "Yes" else ""
            return ("Active", "Active as per AM Request", ma)
        else:
            ma = "Remove max" if max_0 == "Yes" else ""
            return ("Inactive", "AM Request Active but 0 Stock", ma)
    return None


# ── SKU-level logic ───────────────────────────────────────────────────────────

def _sku_logic(mp_status, mp_stock, ecom_status, tc_status,
               tc_stock, reserved, max_0, article_no, excl_map, sku=None):
    """
    ecom_status here is the normalised value (Inactive for future launch too).
    """
    excl = _apply_exclusion(article_no, tc_stock, excl_map, max_0, sku=sku)
    if excl:
        final_status, comment, max_action = excl
    else:
        if ecom_status == "Inactive":
            final_status = "Inactive"
            comment      = "Due to Ecom No"
        elif tc_stock == 0:
            final_status = "Inactive"
            comment      = "Due to 0 Stock"
        else:
            final_status = "Active"
            comment      = "Ecom Yes with Stock"

        max_action = ""
        if comment == "Due to Ecom No" and max_0 == "No":
            max_action = "Set max 0"
        elif comment in ("Due to 0 Stock", "Ecom Yes with Stock") and max_0 == "Yes":
            max_action = "Remove max"

    mp_norm  = _normalise_status(mp_status)
    tc_norm  = _normalise_status(tc_status)
    fin_norm = final_status

    final_check = (mp_norm == tc_norm == fin_norm)
    stock_check = (mp_stock == tc_stock)

    if not final_check:
        remarks = "Change to Active" if final_status == "Active" else "Change to Inactive"
    elif not stock_check:
        if final_status == "Active":
            remarks = "Due to Reserved Stock" if reserved != 0 else "Make Impact"
        else:
            remarks = "Stock not pushed due to Inactive Status"
    else:
        remarks = "All Good"

    push_0 = "Yes" if (tc_stock <= 0 and mp_stock > 0) else ""

    return {
        "Final Status":  final_status,
        "Comments":      comment,
        "Final Check":   str(final_check),
        "Stock Check":   str(stock_check),
        "Remarks":       remarks,
        "Max Setup":     max_action,
        "Update 0":      push_0,
    }


# ── Vectorized status helper ───────────────────────────────────────────

def _normalise_status_series(ser):
    s = ser.fillna("").astype(str).str.strip().str.lower()
    active_mask = s.isin(["active", "1", "enabled", "yes", "y", "live", "listed"])
    inactive_mask = s.isin(["inactive", "0", "disabled", "no", "n", "delisted", "unlisted", "deleted", "removed"])
    default_vals = ser.fillna("").astype(str).str.strip()
    return np.select([active_mask, inactive_mask], ["Active", "Inactive"], default=default_vals)


# ── SKU-level validation (Lazada + Zalora) ────────────────────────────────────

def run_sku_validation(data, country):
    content   = data.get("content",   pd.DataFrame())
    tc_inv    = data.get("tc_inv",    pd.DataFrame())
    zecom     = data.get("zecom",     pd.DataFrame())
    all_df    = data.get("all_file",  pd.DataFrame())
    exclusion = data.get("exclusion", pd.DataFrame())

    excl_map    = _build_excl_map(exclusion)
    article_map = _build_article_map(content)
    tc_map      = _build_tc_map(tc_inv)

    mp_sources = {
        "Lazada " + country: data.get("lazada", pd.DataFrame()),
        "Zalora " + country: data.get("zalora", pd.DataFrame()),
    }

    frames = []
    for mp_name, df in mp_sources.items():
        if df is None or df.empty or "SKU" not in df.columns:
            continue

        apply_buffer = _needs_buffer(mp_name)
        ecom_map  = _build_ecom_map(zecom, mp_name)
        stock_map = _build_stock_map(all_df, apply_buffer)
        launch_map = _build_launch_map(zecom, mp_name)
        future_launch_map = _build_future_launch_map(zecom, mp_name)

        df = df.copy()
        df["SKU_orig"] = df["SKU"]
        df["SKU"] = df["SKU"].apply(_safe_str)
        df["SKU_clean"] = df["SKU"].apply(_clean_sku)

        # 1. Filter out SKUs longer than 13 characters
        df = df[df["SKU_clean"].str.len() <= 13]

        tc_df = pd.DataFrame.from_dict(tc_map, orient="index")
        stock_df = pd.DataFrame.from_dict(stock_map, orient="index")
        
        art_series = pd.Series(article_map, name="Article No")
        ecom_series = pd.Series(ecom_map, name="Ecom Status")
        
        df = df.join(art_series, on="SKU_clean")
        df["Article No"] = df["Article No"].fillna("")
        
        # Check if Future Launch is True
        df["Future Launch"] = df["Article No"].apply(_normalise_article_no).map(future_launch_map).fillna(False)

        # Map raw Ecom Status on the fly using normalised Article No
        df["Ecom Status"] = df["Article No"].apply(_normalise_article_no).map(ecom_map)
        
        # Resolve e-com (Yes/No) and ECOM Status columns
        ecom_raw = df["Ecom Status"]
        ecom_raw_clean = ecom_raw.fillna("").astype(str).str.strip()
        ecom_raw_val = np.where((ecom_raw_clean == "") | (ecom_raw.isna()) | (df["Article No"] == ""), "#N/A", ecom_raw_clean)
        ecom_raw_std = _standardise_raw_ecom_series(pd.Series(ecom_raw_val, index=df.index))
        
        df["e-com (Yes/No)"] = np.where(df["Future Launch"], "Future", ecom_raw_std)
        df["ECOM Status"] = np.where(df["e-com (Yes/No)"] == "Yes", "Active", "Inactive")
        
        df = df.join(tc_df, on="SKU_clean")
        df["TC SKU"] = df["TC SKU"].fillna("")
        df["TC Status"] = df["TC Status"].fillna("Unknown")
        df["Max 0"] = df["Max 0"].fillna("No")
        
        # Keep track if SKU was found in TC Inventory
        tc_found = df["SKU_clean"].isin(tc_df.index)
        
        df = df.join(stock_df, on="SKU_clean")
        df["TC Stock"] = df["TC Stock"].fillna(0.0)
        df["Reserved Stock"] = df["Reserved Stock"].fillna(0.0)
        
        df["Launch Date"] = df["Article No"].apply(_normalise_article_no).map(launch_map).fillna("")
        
        excl_art = df["Article No"].apply(_normalise_article_no).map(excl_map)
        excl_sku = df["SKU_clean"].map(excl_map)
        df["Exclusion"] = excl_art.fillna(excl_sku).fillna("")
        
        df["SKU Valid"] = df["SKU_clean"].apply(_is_valid_sku)
        
        if "MP Status" not in df.columns:
            df["MP Status"] = "Unknown"
        else:
            df["MP Status"] = df["MP Status"].apply(_safe_str)
            
        if "MP Stock" not in df.columns:
            df["MP Stock"] = 0.0
        else:
            df["MP Stock"] = pd.to_numeric(df["MP Stock"], errors="coerce").fillna(0.0)

        df["Final Status"] = ""
        df["Comments"] = ""
        df["Max Setup"] = ""

        excl_val = df["Exclusion"]
        has_excl = excl_val.notna() & (excl_val != "")

        # Exclusion = Inactive
        excl_inactive = has_excl & (excl_val == "Inactive")
        df.loc[excl_inactive, "Final Status"] = "Inactive"
        df.loc[excl_inactive, "Comments"] = "Inactive as per AM Request"
        df.loc[excl_inactive, "Max Setup"] = np.where(df.loc[excl_inactive, "Max 0"] == "Yes", "", "Set max 0")

        # Exclusion = Active
        excl_active = has_excl & (excl_val == "Active")
        df.loc[excl_active, "Final Status"] = np.where(df.loc[excl_active, "TC Stock"] >= 1, "Active", "Inactive")
        df.loc[excl_active, "Comments"] = np.where(df.loc[excl_active, "TC Stock"] >= 1, "Active as per AM Request", "AM Request Active but 0 Stock")
        df.loc[excl_active, "Max Setup"] = np.where(df.loc[excl_active, "Max 0"] == "Yes", "Remove max", "")

        no_excl = ~has_excl
        
        cond_ecom_no = no_excl & (df["ECOM Status"] == "Inactive")
        df.loc[cond_ecom_no, "Final Status"] = "Inactive"
        df.loc[cond_ecom_no, "Comments"] = "Due to Ecom No"
        
        cond_stock_0 = no_excl & (df["ECOM Status"] == "Active") & (df["TC Stock"] == 0)
        df.loc[cond_stock_0, "Final Status"] = "Inactive"
        df.loc[cond_stock_0, "Comments"] = "Due to 0 Stock"
        
        cond_active = no_excl & (df["ECOM Status"] == "Active") & (df["TC Stock"] != 0)
        df.loc[cond_active, "Final Status"] = "Active"
        df.loc[cond_active, "Comments"] = "Ecom Yes with Stock"
        
        comment_is_ecom_no = df["Comments"] == "Due to Ecom No"
        df.loc[no_excl & comment_is_ecom_no & (df["Max 0"] == "No"), "Max Setup"] = "Set max 0"
        
        comment_is_stock_or_ecom_active = df["Comments"].isin(["Due to 0 Stock", "Ecom Yes with Stock"])
        df.loc[no_excl & comment_is_stock_or_ecom_active & (df["Max 0"] == "Yes"), "Max Setup"] = "Remove max"

        mp_norm = _normalise_status_series(df["MP Status"])
        tc_norm = _normalise_status_series(df["TC Status"])
        fin_norm = df["Final Status"]

        final_check_bool = (mp_norm == tc_norm) & (tc_norm == fin_norm)
        df["Final Check"] = final_check_bool.astype(str)
        df["Stock Check"] = (df["MP Stock"] == df["TC Stock"]).astype(str)

        df["Remarks"] = "All Good"
        not_fc = ~final_check_bool
        df.loc[not_fc, "Remarks"] = np.where(df.loc[not_fc, "Final Status"] == "Active", "Change to Active", "Change to Inactive")

        fc_not_sc = final_check_bool & (df["MP Stock"] != df["TC Stock"])
        active_fc_not_sc = fc_not_sc & (df["Final Status"] == "Active")
        df.loc[active_fc_not_sc, "Remarks"] = np.where(df.loc[active_fc_not_sc, "Reserved Stock"] != 0, "Due to Reserved Stock", "Make Impact")

        inactive_fc_not_sc = fc_not_sc & (df["Final Status"] != "Active")
        df.loc[inactive_fc_not_sc, "Remarks"] = "Stock not pushed due to Inactive Status"

        df["Update 0"] = np.where((df["TC Stock"] <= 0) & (df["MP Stock"] > 0), "Yes", "")

        # Convert numeric columns to object type to allow string '#N/A' overwrites for invalid rows
        for col in ["TC Stock", "Reserved Stock"]:
            if col in df.columns:
                df[col] = df[col].astype(object)

        # Handle Invalid SKUs
        invalid_mask = ~df["SKU Valid"]
        df.loc[invalid_mask, "TC SKU"] = np.where(df.loc[invalid_mask, "TC SKU"] != "", df.loc[invalid_mask, "TC SKU"], "#N/A")
        df.loc[invalid_mask, "Article No"] = np.where(df.loc[invalid_mask, "Article No"] != "", df.loc[invalid_mask, "Article No"], "#N/A")
        df.loc[invalid_mask, "MP Status"] = np.where(df.loc[invalid_mask, "MP Status"] != "", df.loc[invalid_mask, "MP Status"], "#N/A")
        df.loc[invalid_mask, "TC Status"] = "#N/A"
        df.loc[invalid_mask, "e-com (Yes/No)"] = "#N/A"
        df.loc[invalid_mask, "Launch Date"] = np.where(df.loc[invalid_mask, "Launch Date"] != "", df.loc[invalid_mask, "Launch Date"], "#N/A")
        df.loc[invalid_mask, "Exclusion"] = np.where(df.loc[invalid_mask, "Exclusion"] != "", df.loc[invalid_mask, "Exclusion"], "#N/A")
        df.loc[invalid_mask, "ECOM Status"] = "#N/A"
        df.loc[invalid_mask, "Final Status"] = "Invalid"
        df.loc[invalid_mask, "Comments"] = "Invalid SKU"
        df.loc[invalid_mask, "Final Check"] = "False"
        df.loc[invalid_mask, "TC Stock"] = "#N/A"
        df.loc[invalid_mask, "Reserved Stock"] = "#N/A"
        df.loc[invalid_mask, "Max 0"] = "#N/A"
        df.loc[invalid_mask, "Stock Check"] = "False"
        df.loc[invalid_mask, "Remarks"] = "Invalid SKU"
        df.loc[invalid_mask, "Max Setup"] = "#N/A"
        df.loc[invalid_mask, "Update 0"] = "#N/A"

        # Apply TC Status and Remarks override for missing TC Status
        df.loc[~tc_found, "TC Status"] = "#N/A"
        df.loc[~tc_found, "Remarks"] = "Import"

        df["Marketplace"] = mp_name
        df["Seller SKU"] = df["SKU_orig"]

        out_cols = [
            "Marketplace", "Seller SKU", "TC SKU", "Article No", "MP Status",
            "TC Status", "e-com (Yes/No)", "Launch Date", "Exclusion", "ECOM Status",
            "MP Stock", "TC Stock", "Reserved Stock", "Max 0",
            "Final Status", "Comments", "Final Check", "Stock Check", "Remarks",
            "Max Setup", "Update 0"
        ]
        frames.append(df[out_cols])

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── PID-level validation (Shopee + TikTok) ────────────────────────────────────

def run_pid_validation(data, country):
    content   = data.get("content",   pd.DataFrame())
    tc_inv    = data.get("tc_inv",    pd.DataFrame())
    zecom     = data.get("zecom",     pd.DataFrame())
    all_df    = data.get("all_file",  pd.DataFrame())
    exclusion = data.get("exclusion", pd.DataFrame())

    excl_map    = _build_excl_map(exclusion)
    article_map = _build_article_map(content)
    tc_map      = _build_tc_map(tc_inv)

    mp_sources = {
        "Shopee " + country: data.get("shopee", pd.DataFrame()),
    }
    if country == "MY":
        mp_sources["TikTok MY"] = data.get("tiktok", pd.DataFrame())

    frames = []
    for mp_name, df in mp_sources.items():
        if df is None or df.empty or "SKU" not in df.columns:
            continue

        apply_buffer = _needs_buffer(mp_name)
        ecom_map  = _build_ecom_map(zecom, mp_name)
        stock_map = _build_stock_map(all_df, apply_buffer)
        launch_map = _build_launch_map(zecom, mp_name)
        future_launch_map = _build_future_launch_map(zecom, mp_name)

        df = df.copy()
        df["SKU_orig"] = df["SKU"]
        df["SKU"] = df["SKU"].apply(_safe_str)
        df["SKU_clean"] = df["SKU"].apply(_clean_sku)
        
        # 1. Filter out SKUs longer than 13 characters
        df = df[df["SKU_clean"].str.len() <= 13]

        df["Product ID"] = df.get("Product ID", df["SKU"]).apply(_safe_str)
        if "MP Status" not in df.columns:
            df["MP Status"] = "Unknown"
        else:
            df["MP Status"] = df["MP Status"].apply(_safe_str)
            
        if "MP Stock" not in df.columns:
            df["MP Stock"] = 0.0
        else:
            df["MP Stock"] = pd.to_numeric(df["MP Stock"], errors="coerce").fillna(0.0)

        tc_df = pd.DataFrame.from_dict(tc_map, orient="index")
        stock_df = pd.DataFrame.from_dict(stock_map, orient="index")
        art_series = pd.Series(article_map, name="Article No")
        ecom_series = pd.Series(ecom_map, name="Ecom Status")
        
        df = df.join(art_series, on="SKU_clean")
        df["Article No"] = df["Article No"].fillna("")
        
        # Check if Future Launch is True
        df["Future Launch"] = df["Article No"].apply(_normalise_article_no).map(future_launch_map).fillna(False)

        # Map raw Ecom Status on the fly using normalised Article No
        df["Ecom Status"] = df["Article No"].apply(_normalise_article_no).map(ecom_map)
        
        # Resolve e-com (Yes/No) and ECOM Status columns
        ecom_raw = df["Ecom Status"]
        ecom_raw_clean = ecom_raw.fillna("").astype(str).str.strip()
        ecom_raw_val = np.where((ecom_raw_clean == "") | (ecom_raw.isna()) | (df["Article No"] == ""), "#N/A", ecom_raw_clean)
        ecom_raw_std = _standardise_raw_ecom_series(pd.Series(ecom_raw_val, index=df.index))
        
        df["e-com (Yes/No)"] = np.where(df["Future Launch"], "Future", ecom_raw_std)
        df["ECOM Status"] = np.where(df["e-com (Yes/No)"] == "Yes", "Active", "Inactive")
        
        df = df.join(tc_df, on="SKU_clean")
        df["TC SKU"] = df["TC SKU"].fillna("")
        df["TC Status"] = df["TC Status"].fillna("Unknown")
        df["Max 0"] = df["Max 0"].fillna("No")
        
        # Keep track if SKU was found in TC Inventory
        tc_found = df["SKU_clean"].isin(tc_df.index)
        
        df = df.join(stock_df, on="SKU_clean")
        df["TC Stock"] = df["TC Stock"].fillna(0.0)
        df["Reserved Stock"] = df["Reserved Stock"].fillna(0.0)
        
        df["Launch Date"] = df["Article No"].apply(_normalise_article_no).map(launch_map).fillna("")
        
        excl_art = df["Article No"].apply(_normalise_article_no).map(excl_map)
        excl_sku = df["SKU_clean"].map(excl_map)
        df["Exclusion"] = excl_art.fillna(excl_sku).fillna("")
        
        df["SKU Valid"] = df["SKU_clean"].apply(_is_valid_sku)
        df["Ecom Logic"] = df["ECOM Status"]

        # Dual Status
        pid_active = df[df["Ecom Logic"] == "Active"]["Product ID"].unique()
        pid_inactive = df[df["Ecom Logic"] == "Inactive"]["Product ID"].unique()
        dual_pids = set(pid_active) & set(pid_inactive)
        df["Dual Status"] = np.where(df["Product ID"].isin(dual_pids), 2, 1)

        # Consolidated TC Stock
        df["Consolidated SUM QTY"] = df.groupby("Product ID")["TC Stock"].transform("sum")

        df["Final Status"] = ""
        df["Comments"] = ""
        df["Max Setup"] = ""

        excl_val = df["Exclusion"]
        has_excl = excl_val.notna() & (excl_val != "")

        # Exclusion = Inactive
        excl_inactive = has_excl & (excl_val == "Inactive")
        df.loc[excl_inactive, "Final Status"] = "Inactive"
        df.loc[excl_inactive, "Comments"] = "Inactive as per AM Request"
        df.loc[excl_inactive, "Max Setup"] = np.where(df.loc[excl_inactive, "Max 0"] == "Yes", "", "Set max 0")

        # Exclusion = Active
        excl_active = has_excl & (excl_val == "Active")
        df.loc[excl_active, "Final Status"] = np.where(df.loc[excl_active, "Consolidated SUM QTY"] >= 1, "Active", "Inactive")
        df.loc[excl_active, "Comments"] = np.where(df.loc[excl_active, "Consolidated SUM QTY"] >= 1, "Active as per AM Request", "AM Request Active but 0 Stock")
        df.loc[excl_active, "Max Setup"] = np.where(df.loc[excl_active, "Max 0"] == "Yes", "Remove max", "")

        no_excl = ~has_excl
        
        # Dual Status = 1
        ds1 = no_excl & (df["Dual Status"] == 1)
        
        cond_ds1_ecom_no = ds1 & (df["Ecom Logic"] == "Inactive")
        df.loc[cond_ds1_ecom_no, "Final Status"] = "Inactive"
        df.loc[cond_ds1_ecom_no, "Comments"] = "Due to Ecom No"
        
        cond_ds1_stock_0 = ds1 & (df["Ecom Logic"] != "Inactive") & (df["Consolidated SUM QTY"] == 0)
        df.loc[cond_ds1_stock_0, "Final Status"] = "Inactive"
        df.loc[cond_ds1_stock_0, "Comments"] = "Due to 0 Stock"
        
        cond_ds1_active = ds1 & (df["Ecom Logic"] != "Inactive") & (df["Consolidated SUM QTY"] != 0)
        df.loc[cond_ds1_active, "Final Status"] = "Active"
        df.loc[cond_ds1_active, "Comments"] = "Ecom Yes with Stock"
        
        # Dual Status = 2
        ds2 = no_excl & (df["Dual Status"] == 2)
        
        cond_ds2_stock_0 = ds2 & (df["Consolidated SUM QTY"] == 0)
        df.loc[cond_ds2_stock_0, "Final Status"] = "Inactive"
        df.loc[cond_ds2_stock_0, "Comments"] = "Due to 0 Stock"
        
        cond_ds2_active_ecom = ds2 & (df["Consolidated SUM QTY"] != 0) & (df["Ecom Logic"] == "Active")
        df.loc[cond_ds2_active_ecom, "Final Status"] = "Active"
        df.loc[cond_ds2_active_ecom, "Comments"] = "Ecom Yes with Stock"
        
        cond_ds2_set_max = ds2 & (df["Consolidated SUM QTY"] != 0) & (df["Ecom Logic"] != "Active")
        df.loc[cond_ds2_set_max, "Final Status"] = "Active"
        df.loc[cond_ds2_set_max, "Comments"] = "Set max"

        # Max Setup logic for no_excl
        comment_is_ecom_no_or_set_max = df["Comments"].isin(["Due to Ecom No", "Set max"])
        df.loc[no_excl & comment_is_ecom_no_or_set_max & (df["Max 0"] == "No"), "Max Setup"] = "Set max"
        
        comment_is_ecom_stock = df["Comments"] == "Ecom Yes with Stock"
        df.loc[no_excl & comment_is_ecom_stock & (df["Max 0"] == "Yes"), "Max Setup"] = "Remove max"
        
        comment_is_stock_0 = df["Comments"] == "Due to 0 Stock"
        ecom_yn_yes = df["ECOM Status"] == "Active"
        ecom_yn_no = df["ECOM Status"] == "Inactive"
        df.loc[no_excl & comment_is_stock_0 & ecom_yn_yes & (df["Max 0"] == "Yes"), "Max Setup"] = "Remove max"
        df.loc[no_excl & comment_is_stock_0 & ecom_yn_no & (df["Max 0"] == "No"), "Max Setup"] = "Set max"

        mp_norm = _normalise_status_series(df["MP Status"])
        tc_norm = _normalise_status_series(df["TC Status"])
        fin_norm = df["Final Status"]

        final_check_bool = (mp_norm == tc_norm) & (tc_norm == fin_norm)
        df["Final Check"] = final_check_bool.astype(str)
        df["Stock Check"] = (df["MP Stock"] == df["TC Stock"]).astype(str)

        # Remarks
        df["Remarks"] = "All Good"
        not_fc = ~final_check_bool
        df.loc[not_fc, "Remarks"] = "Update status to " + df.loc[not_fc, "Final Status"]

        fc_not_sc = final_check_bool & (df["MP Stock"] != df["TC Stock"])
        
        active_fc_not_sc = fc_not_sc & (df["Final Status"] == "Active")
        df.loc[active_fc_not_sc, "Remarks"] = np.select(
            [
                df.loc[active_fc_not_sc, "Comments"] == "Set max",
                df.loc[active_fc_not_sc, "Reserved Stock"] != 0
            ],
            [
                "Set max product",
                "Due to Reserved Stock"
            ],
            default="Make Impact"
        )

        inactive_fc_not_sc = fc_not_sc & (df["Final Status"] != "Active")
        df.loc[inactive_fc_not_sc, "Remarks"] = "Stock not pushed due to Inactive Status"

        # Convert numeric columns to object type to allow string '#N/A' overwrites for invalid rows
        for col in ["TC Stock", "Reserved Stock"]:
            if col in df.columns:
                df[col] = df[col].astype(object)

        # Handle Invalid SKUs
        invalid_mask = ~df["SKU Valid"]
        df.loc[invalid_mask, "TC SKU"] = np.where(df.loc[invalid_mask, "TC SKU"] != "", df.loc[invalid_mask, "TC SKU"], "#N/A")
        df.loc[invalid_mask, "Product ID"] = np.where(df.loc[invalid_mask, "Product ID"] != "", df.loc[invalid_mask, "Product ID"], "#N/A")
        df.loc[invalid_mask, "Article No"] = np.where(df.loc[invalid_mask, "Article No"] != "", df.loc[invalid_mask, "Article No"], "#N/A")
        df.loc[invalid_mask, "MP Status"] = np.where(df.loc[invalid_mask, "MP Status"] != "", df.loc[invalid_mask, "MP Status"], "#N/A")
        df.loc[invalid_mask, "TC Status"] = "#N/A"
        df.loc[invalid_mask, "e-com (Yes/No)"] = "#N/A"
        df.loc[invalid_mask, "Launch Date"] = np.where(df.loc[invalid_mask, "Launch Date"] != "", df.loc[invalid_mask, "Launch Date"], "#N/A")
        df.loc[invalid_mask, "Exclusion"] = np.where(df.loc[invalid_mask, "Exclusion"] != "", df.loc[invalid_mask, "Exclusion"], "#N/A")
        df.loc[invalid_mask, "ECOM Status"] = "#N/A"
        df.loc[invalid_mask, "Final Status"] = "Invalid"
        df.loc[invalid_mask, "Comments"] = "Invalid SKU"
        df.loc[invalid_mask, "Final Check"] = "False"
        df.loc[invalid_mask, "TC Stock"] = "#N/A"
        df.loc[invalid_mask, "Reserved Stock"] = "#N/A"
        df.loc[invalid_mask, "Max 0"] = "#N/A"
        df.loc[invalid_mask, "Stock Check"] = "False"
        df.loc[invalid_mask, "Remarks"] = "Invalid SKU"
        df.loc[invalid_mask, "Max Setup"] = "#N/A"
        df.loc[invalid_mask, "Update 0"] = "#N/A"

        # Apply TC Status and Remarks override for missing TC Status
        df.loc[~tc_found, "TC Status"] = "#N/A"
        df.loc[~tc_found, "Remarks"] = "Import"

        df["Marketplace"] = mp_name
        df["SellerSku"] = df["SKU_orig"]

        out_cols = [
            "Marketplace", "SellerSku", "TC SKU", "Product ID", "Article No", "MP Status",
            "TC Status", "e-com (Yes/No)", "Launch Date", "Exclusion", "ECOM Status",
            "Final Status", "Comments", "Final Check", "Dual Status", "Consolidated SUM QTY",
            "MP Stock", "TC Stock", "Reserved Stock", "Max 0", "Stock Check",
            "Remarks", "Max Setup", "Update 0"
        ]
        frames.append(df[out_cols])

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── Fast Excel Writer ──────────────────────────────────────────────────────────

def save_df_to_excel_fast(sheets, file_or_buffer):
    """
    Write DataFrames to Excel with auto-fitted column widths, center alignment,
    bold light blue headers, and a Summary sheet with side-by-side pivot tables
    for Remarks and Max Setup.
    """
    import xlsxwriter
    import pandas as pd
    import numpy as np
    from collections import Counter

    # 1. Generate Summary data
    all_remarks = []
    all_max_setup = []
    for df in sheets.values():
        if "Remarks" in df.columns:
            all_remarks.extend(df["Remarks"].fillna("").astype(str).str.strip().tolist())
        if "Max Setup" in df.columns:
            all_max_setup.extend(df["Max Setup"].fillna("").astype(str).str.strip().tolist())
    
    clean_remarks = [r for r in all_remarks if r and r not in ("", "#N/A", "nan", "None")]
    clean_max_setup = [m for m in all_max_setup if m and m not in ("", "#N/A", "nan", "None")]
    
    remarks_counts = Counter(clean_remarks).most_common()
    max_setup_counts = Counter(clean_max_setup).most_common()
    
    # 2. Re-order sheets so Summary is first
    ordered_sheets = {"Summary": pd.DataFrame()}
    for k, v in sheets.items():
        ordered_sheets[k] = v

    # 3. Create Workbook
    workbook = xlsxwriter.Workbook(file_or_buffer, {'nan_inf_to_errors': True})
    
    # Define formats
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#DBEAFE',      # Light Blue background
        'font_color': '#1E3A8A',    # Dark Blue text
        'align': 'center',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#93C5FD'
    })
    
    header_left_format = workbook.add_format({
        'bold': True,
        'bg_color': '#DBEAFE',
        'font_color': '#1E3A8A',
        'align': 'left',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#93C5FD'
    })
    
    header_right_format = workbook.add_format({
        'bold': True,
        'bg_color': '#DBEAFE',
        'font_color': '#1E3A8A',
        'align': 'right',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#93C5FD'
    })

    cell_format = workbook.add_format({
        'align': 'center',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#E5E7EB'
    })

    remarks_format = workbook.add_format({
        'align': 'left',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#E5E7EB'
    })

    right_format = workbook.add_format({
        'align': 'right',
        'valign': 'vcenter',
        'border': 1,
        'border_color': '#E5E7EB'
    })

    total_left_format = workbook.add_format({
        'bold': True,
        'border': 1,
        'border_color': '#E5E7EB',
        'bg_color': '#F3F4F6',
        'align': 'left'
    })
    
    total_right_format = workbook.add_format({
        'bold': True,
        'border': 1,
        'border_color': '#E5E7EB',
        'bg_color': '#F3F4F6',
        'align': 'right'
    })

    for sheet_name, df in ordered_sheets.items():
        worksheet = workbook.add_worksheet(sheet_name[:31])
        
        # ── Case A: Write custom Summary layout ──────────────────────────────────
        if sheet_name == "Summary":
            worksheet.set_row(0, 24) # Set header row height
            
            # Table 1: Remarks (Cols A and B)
            worksheet.write(0, 0, "Row Labels", header_left_format)
            worksheet.write(0, 1, "Count of Remarks", header_right_format)
            
            remarks_total = 0
            current_row = 1
            for label, cnt in remarks_counts:
                worksheet.set_row(current_row, 20)
                worksheet.write_string(current_row, 0, str(label), remarks_format)
                worksheet.write_number(current_row, 1, cnt, right_format)
                remarks_total += cnt
                current_row += 1
                
            worksheet.set_row(current_row, 20)
            worksheet.write_string(current_row, 0, "Grand Total", total_left_format)
            worksheet.write_number(current_row, 1, remarks_total, total_right_format)
            
            # Table 2: Max Setup (Cols D and E)
            worksheet.write(0, 3, "Row Labels", header_left_format)
            worksheet.write(0, 4, "Count of Max Setup", header_right_format)
            
            max_setup_total = 0
            current_row = 1
            for label, cnt in max_setup_counts:
                worksheet.set_row(current_row, 20)
                worksheet.write_string(current_row, 3, str(label), remarks_format)
                worksheet.write_number(current_row, 4, cnt, right_format)
                max_setup_total += cnt
                current_row += 1
                
            worksheet.set_row(current_row, 20)
            worksheet.write_string(current_row, 3, "Grand Total", total_left_format)
            worksheet.write_number(current_row, 4, max_setup_total, total_right_format)
            
            # Widths & Spacing
            worksheet.set_column(2, 2, 4) # Spacer column C
            
            max_a = max([len(str(x[0])) for x in remarks_counts] + [len("Row Labels"), len("Grand Total")]) + 3
            max_b = max([len(str(x[1])) for x in remarks_counts] + [len("Count of Remarks")]) + 3
            worksheet.set_column(0, 0, max(max_a, 12))
            worksheet.set_column(1, 1, max(max_b, 16))
            
            max_d = max([len(str(x[0])) for x in max_setup_counts] + [len("Row Labels"), len("Grand Total")]) + 3
            max_e = max([len(str(x[1])) for x in max_setup_counts] + [len("Count of Max Setup")]) + 3
            worksheet.set_column(3, 3, max(max_d, 12))
            worksheet.set_column(4, 4, max(max_e, 18))
            continue

        # ── Case B: Write standard validation sheet layout ──────────────────────
        if df.empty:
            continue
            
        worksheet.set_row(0, 24) # Set header row height
        worksheet.write_row(0, 0, list(df.columns), header_format)
        
        # Prepare clean data values
        df_clean = df.fillna("")
        data_list = df_clean.values.tolist()
        
        # Write data rows
        for row_idx, row in enumerate(data_list, start=1):
            worksheet.set_row(row_idx, 20) # Set data row height
            for col_idx, val in enumerate(row):
                fmt = cell_format
                if df.columns[col_idx] in ["Remarks", "Comments"]:
                    fmt = remarks_format
                
                # Write matching correct types
                if isinstance(val, (int, float)) and not pd.isna(val):
                    worksheet.write_number(row_idx, col_idx, val, fmt)
                else:
                    worksheet.write_string(row_idx, col_idx, str(val), fmt)
        
        # Auto-fit column widths (sample up to 2000 rows for speed)
        sample_size = min(len(df_clean), 2000)
        for col_idx, col_name in enumerate(df.columns):
            max_len = len(str(col_name))
            if sample_size > 0:
                max_len = max(max_len, df_clean.iloc[:sample_size, col_idx].astype(str).str.len().max())
            worksheet.set_column(col_idx, col_idx, max(max_len + 3, 10))
            
    workbook.close()

