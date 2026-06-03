import re
import pandas as pd


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


def _normalise_status(status):
    s = _safe_str(status).lower()
    if s in ("active", "1", "enabled", "yes", "y", "live", "listed"):
        return "Active"
    if s in ("inactive", "0", "disabled", "no", "n", "delisted",
             "unlisted", "deleted", "removed"):
        return "Inactive"
    return _safe_str(status)


def _is_valid_sku(sku):
    """Seller SKU must be exactly 13 digits."""
    return bool(re.fullmatch(r'\d{13}', _safe_str(sku)))


# ── Lookup builders ───────────────────────────────────────────────────────────

def _build_article_map(content):
    """barcode SKU -> Article No"""
    article_map = {}
    if content.empty or "SKU" not in content.columns:
        return article_map
    art_col = next(
        (c for c in ["Article No", "Color_No", "Color_No.1", "ArticleNo"]
         if c in content.columns),
        next((c for c in content.columns
              if "article" in c.lower() or "color" in c.lower()), "")
    )
    if art_col:
        for _, r in content.iterrows():
            sku = _safe_str(r.get("SKU", ""))
            if sku:
                article_map[sku] = _safe_str(r.get(art_col, ""))
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
    for _, r in zecom.iterrows():
        art = _safe_str(r.get("Article No", ""))
        if art:
            ecom_map[art] = _safe_str(r.get(ecom_col, "Inactive"))
    return ecom_map


def _build_tc_map(tc_inv):
    """
    barcode SKU -> {TC SKU, TC Status, Max 0}

    FIX V-1: child/parent priority is decided by the GED code (TC SKU column,
    e.g. GED4771311-01), NOT the barcode (SKU column).
    Barcodes are 13-digit numbers and never contain "-".
    """
    tc_map = {}
    parent_fallback = {}

    if tc_inv.empty or "SKU" not in tc_inv.columns:
        return tc_map

    for _, r in tc_inv.iterrows():
        sku = _safe_str(r.get("SKU", ""))              # barcode — lookup key
        if not sku:
            continue
        tc_sku_val = _safe_str(r.get("TC SKU", sku))  # GED code — child/parent check
        entry = {
            "TC SKU":    tc_sku_val,
            "TC Status": _safe_str(r.get("TC Status", "Unknown")),
            "Max 0":     _safe_str(r.get("Max 0", "No")),
        }
        # FIX V-1: use GED code (tc_sku_val) to determine child vs parent
        if "-" in tc_sku_val:
            tc_map[sku] = entry
            parent_base = tc_sku_val.rsplit("-", 1)[0]
            if parent_base not in parent_fallback:
                parent_fallback[parent_base] = entry
        else:
            if sku not in tc_map:
                tc_map[sku] = entry

    for parent, entry in parent_fallback.items():
        if parent not in tc_map:
            tc_map[parent] = entry

    return tc_map


def _build_stock_map(all_df, apply_buffer=False):
    """
    barcode SKU -> {TC Stock, Reserved Stock}
    Negative TC Stock clamped to 0. Buffer -1 for Lazada PH / TikTok MY.
    """
    stock_map = {}
    if all_df.empty or "SKU" not in all_df.columns:
        return stock_map
    for _, r in all_df.iterrows():
        sku = _safe_str(r.get("SKU", ""))
        if sku and sku not in stock_map:
            tc = _safe_num(r.get("TC Stock", 0))
            tc = max(tc, 0)
            if apply_buffer:
                tc = max(tc - 1, 0)
            stock_map[sku] = {
                "TC Stock":       tc,
                "Reserved Stock": _safe_num(r.get("Reserved Stock", 0)),
            }
    return stock_map


def _build_excl_map(exclusion):
    """Article No -> Exclusion Status"""
    excl_map = {}
    if exclusion is None or exclusion.empty:
        return excl_map
    if "Article No" not in exclusion.columns:
        return excl_map
    for _, r in exclusion.iterrows():
        art = _safe_str(r.get("Article No", ""))
        if art:
            excl_map[art] = _safe_str(r.get("Exclusion Status", "Inactive"))
    return excl_map


def _build_launch_map(zecom):
    """Article No -> Launch Date string"""
    launch_map = {}
    if zecom.empty or "Article No" not in zecom.columns:
        return launch_map
    if "Launch Date" not in zecom.columns:
        return launch_map
    for _, r in zecom.iterrows():
        art = _safe_str(r.get("Article No", ""))
        if art:
            ld = r.get("Launch Date", "")
            if pd.notna(ld) and str(ld).strip() not in ("", "NaT", "nan"):
                try:
                    launch_map[art] = str(pd.to_datetime(ld).date())
                except Exception:
                    launch_map[art] = _safe_str(ld)
            else:
                launch_map[art] = ""
    return launch_map


def _needs_buffer(mp_name):
    """Buffer -1 stock only for Lazada PH and TikTok MY."""
    return mp_name in ("Lazada PH", "TikTok MY")


# ── Exclusion override ────────────────────────────────────────────────────────

def _apply_exclusion(article_no, tc_stock, excl_map, max_0):
    if not article_no or article_no not in excl_map:
        return None
    excl_status = excl_map[article_no]
    if excl_status == "Inactive":
        return ("Inactive", "Inactive as per AM Request", "Set max 0")
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
               tc_stock, reserved, max_0, article_no, excl_map):
    excl = _apply_exclusion(article_no, tc_stock, excl_map, max_0)
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

    final_check = (mp_norm == tc_norm == final_status)
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
    launch_map  = _build_launch_map(zecom)

    mp_sources = {
        "Lazada " + country: data.get("lazada", pd.DataFrame()),
        "Zalora " + country: data.get("zalora", pd.DataFrame()),
    }

    rows = []
    for mp_name, df in mp_sources.items():
        if df is None or df.empty or "SKU" not in df.columns:
            continue

        apply_buffer = _needs_buffer(mp_name)
        ecom_map  = _build_ecom_map(zecom, mp_name)
        stock_map = _build_stock_map(all_df, apply_buffer)

        for _, r in df.iterrows():
            sku        = _safe_str(r.get("SKU", ""))
            mp_status  = _safe_str(r.get("MP Status", "Unknown"))
            mp_stock   = _safe_num(r.get("MP Stock", 0))
            article_no = article_map.get(sku, "")
            ecom_st    = ecom_map.get(article_no, "Inactive") if article_no else "Inactive"
            tc_data    = tc_map.get(sku, {"TC SKU": "", "TC Status": "Unknown", "Max 0": "No"})
            sd         = stock_map.get(sku, {"TC Stock": 0.0, "Reserved Stock": 0.0})
            excl_lbl   = excl_map.get(article_no, "") if article_no else ""
            launch_dt  = launch_map.get(article_no, "") if article_no else ""

            if not _is_valid_sku(sku):
                rows.append({
                    "Marketplace":    mp_name,
                    "Seller SKU":     sku,
                    "TC SKU":         tc_data["TC SKU"],
                    "Article No":     article_no,
                    "MP Status":      mp_status,
                    "TC Status":      "",
                    "e-com (Yes/No)": "",
                    "Launch Date":    launch_dt,
                    "Exclusion":      excl_lbl,
                    "ECOM Status":    "",
                    "MP Stock":       mp_stock,
                    "TC Stock":       "",
                    "Reserved Stock": "",
                    "Max 0":          "",
                    "Final Status":   "Invalid",
                    "Comments":       "Invalid SKU",
                    "Final Check":    "False",
                    "Stock Check":    "False",
                    "Remarks":        "Invalid SKU",
                    "Max Setup":      "",
                    "Update 0":       "",
                })
                continue

            ecom_for_logic = "Inactive" if ecom_st.startswith("Inactive") else ecom_st

            result = _sku_logic(
                mp_status=mp_status,
                mp_stock=mp_stock,
                ecom_status=ecom_for_logic,
                tc_status=tc_data["TC Status"],
                tc_stock=sd["TC Stock"],
                reserved=sd["Reserved Stock"],
                max_0=tc_data["Max 0"],
                article_no=article_no,
                excl_map=excl_map,
            )
            rows.append({
                "Marketplace":    mp_name,
                "Seller SKU":     sku,
                "TC SKU":         tc_data["TC SKU"],
                "Article No":     article_no,
                "MP Status":      mp_status,
                "TC Status":      _normalise_status(tc_data["TC Status"]),
                "e-com (Yes/No)": "Yes" if ecom_st == "Active" else "No",
                "Launch Date":    launch_dt,
                "Exclusion":      excl_lbl,
                "ECOM Status":    ecom_st,
                "MP Stock":       mp_stock,
                "TC Stock":       sd["TC Stock"],
                "Reserved Stock": sd["Reserved Stock"],
                "Max 0":          tc_data["Max 0"],
                **result,
            })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── PID-level validation (Shopee + TikTok) ───────────────────────────────────

def run_pid_validation(data, country):
    """
    Output columns:
    Marketplace, SellerSku, TC SKU, Product ID, Article No, MP Status,
    TC Status, e-com (Yes/No), Launch Date, Exclusion, ECOM Status,
    Final Status, Comments, Final Check, Dual Status, Consolidated SUM QTY,
    MP Stock, TC Stock, Reserved Stock, Max 0, Stock Check,
    Remarks, Max Setup, Update 0
    """
    content   = data.get("content",   pd.DataFrame())
    tc_inv    = data.get("tc_inv",    pd.DataFrame())
    zecom     = data.get("zecom",     pd.DataFrame())
    all_df    = data.get("all_file",  pd.DataFrame())
    exclusion = data.get("exclusion", pd.DataFrame())

    excl_map    = _build_excl_map(exclusion)
    article_map = _build_article_map(content)
    tc_map      = _build_tc_map(tc_inv)
    launch_map  = _build_launch_map(zecom)

    mp_sources = {
        "Shopee " + country: data.get("shopee", pd.DataFrame()),
    }
    if country == "MY":
        mp_sources["TikTok MY"] = data.get("tiktok", pd.DataFrame())

    rows = []

    for mp_name, df in mp_sources.items():
        if df is None or df.empty or "SKU" not in df.columns:
            continue

        apply_buffer = _needs_buffer(mp_name)
        ecom_map  = _build_ecom_map(zecom, mp_name)
        stock_map = _build_stock_map(all_df, apply_buffer)

        # ── Step 1: Enrich each SKU row ───────────────────────────────────
        enriched = []
        for _, r in df.iterrows():
            sku       = _safe_str(r.get("SKU", ""))
            # FIX V-3: always coerce Product ID to clean string; fall back to SKU
            raw_pid   = r.get("Product ID", "")
            pid       = _safe_str(raw_pid)
            if pid == "":
                pid = sku
            mp_status = _safe_str(r.get("MP Status", "Unknown"))
            mp_stock  = _safe_num(r.get("MP Stock", 0))
            art       = article_map.get(sku, "")
            ecom_st   = ecom_map.get(art, "Inactive") if art else "Inactive"
            ecom_logic = "Inactive" if ecom_st.startswith("Inactive") else ecom_st
            td        = tc_map.get(sku, {"TC SKU": "", "TC Status": "Unknown", "Max 0": "No"})
            sd        = stock_map.get(sku, {"TC Stock": 0.0, "Reserved Stock": 0.0})
            excl_lbl  = excl_map.get(art, "") if art else ""
            launch_dt = launch_map.get(art, "") if art else ""
            sku_valid = _is_valid_sku(sku)
            enriched.append({
                "SKU":            sku,
                "Product ID":     pid,         # always a clean string
                "MP Status":      mp_status,
                "MP Stock":       mp_stock,
                "Article No":     art,
                "Ecom Status":    ecom_st,
                "Ecom Logic":     ecom_logic,
                "TC SKU":         td["TC SKU"],
                "TC Status":      td["TC Status"],
                "Max 0":          td["Max 0"],
                "TC Stock":       sd["TC Stock"],
                "Reserved Stock": sd["Reserved Stock"],
                "Exclusion":      excl_lbl,
                "Launch Date":    launch_dt,
                "SKU Valid":      sku_valid,
            })

        enriched_df = pd.DataFrame(enriched)
        if enriched_df.empty:
            continue

        # ── Step 2: Dual Status per Product ID ───────────────────────────
        dual_map = {}
        for pid_key, grp in enriched_df.groupby("Product ID", dropna=False):
            pid_str = _safe_str(pid_key)
            statuses = set(grp["Ecom Logic"].unique())
            dual_map[pid_str] = (
                2 if ("Active" in statuses and "Inactive" in statuses) else 1
            )

        # ── Step 3: Consolidated TC Stock per Product ID ──────────────────
        # FIX V-2: use dropna=False so keys match dual_map exactly
        consolidated_map = {}
        for pid_key, grp in enriched_df.groupby("Product ID", dropna=False):
            pid_str = _safe_str(pid_key)
            consolidated_map[pid_str] = float(grp["TC Stock"].sum())

        # ── Step 4: Per-SKU output row ────────────────────────────────────
        for _, r in enriched_df.iterrows():
            sku         = r["SKU"]
            pid         = r["Product ID"]       # already a clean string
            mp_status   = r["MP Status"]
            mp_stock    = r["MP Stock"]
            article_no  = r["Article No"]
            ecom_st     = r["Ecom Status"]
            ecom_logic  = r["Ecom Logic"]
            tc_sku      = r["TC SKU"]
            tc_status   = r["TC Status"]
            max_0       = r["Max 0"]
            tc_stock    = r["TC Stock"]
            reserved    = r["Reserved Stock"]
            excl_lbl    = r["Exclusion"]
            launch_dt   = r["Launch Date"]
            sku_valid   = r["SKU Valid"]

            dual_status     = dual_map.get(pid, 1)
            consolidated_tc = consolidated_map.get(pid, 0.0)
            ecom_yn         = "Yes" if ecom_st == "Active" else "No"

            # Invalid SKU row
            if not sku_valid:
                rows.append({
                    "Marketplace":          mp_name,
                    "SellerSku":            sku,
                    "TC SKU":               tc_sku,
                    "Product ID":           pid,
                    "Article No":           article_no,
                    "MP Status":            mp_status,
                    "TC Status":            "",
                    "e-com (Yes/No)":       "",
                    "Launch Date":          launch_dt,
                    "Exclusion":            excl_lbl,
                    "ECOM Status":          "",
                    "Final Status":         "Invalid",
                    "Comments":             "Invalid SKU",
                    "Final Check":          "False",
                    "Dual Status":          dual_status,
                    "Consolidated SUM QTY": consolidated_tc,
                    "MP Stock":             mp_stock,
                    "TC Stock":             "",
                    "Reserved Stock":       "",
                    "Max 0":                "",
                    "Stock Check":          "False",
                    "Remarks":              "Invalid SKU",
                    "Max Setup":            "",
                    "Update 0":             "",
                })
                continue

            # ── Exclusion override ────────────────────────────────────────
            excl = _apply_exclusion(article_no, consolidated_tc, excl_map, max_0)
            if excl:
                final_status, comment, max_action = excl
            else:
                # ── Dual Status = 1 ───────────────────────────────────────
                if dual_status == 1:
                    if ecom_logic == "Inactive":
                        final_status = "Inactive"
                        comment      = "Due to Ecom No"
                    elif consolidated_tc == 0:
                        final_status = "Inactive"
                        comment      = "Due to 0 Stock"
                    else:
                        final_status = "Active"
                        comment      = "Ecom Yes with Stock"
                # ── Dual Status = 2 ───────────────────────────────────────
                else:
                    if consolidated_tc == 0:
                        final_status = "Inactive"
                        comment      = "Due to 0 Stock"
                    elif ecom_logic == "Active":
                        final_status = "Active"
                        comment      = "Ecom Yes with Stock"
                    else:
                        final_status = "Active"
                        comment      = "Set max"

                # ── Max Setup logic ───────────────────────────────────────
                max_action = ""
                if comment in ("Due to Ecom No", "Set max") and max_0 == "No":
                    max_action = "Set max"
                elif comment == "Ecom Yes with Stock" and max_0 == "Yes":
                    max_action = "Remove max"
                elif comment == "Due to 0 Stock":
                    if ecom_yn == "Yes" and max_0 == "Yes":
                        max_action = "Remove max"
                    elif ecom_yn in ("No", "") and max_0 == "No":
                        max_action = "Set max"

            # ── Final Check & Stock Check ─────────────────────────────────
            mp_norm  = _normalise_status(mp_status)
            tc_norm  = _normalise_status(tc_status)

            final_check = (mp_norm == tc_norm == final_status)
            stock_check = (mp_stock == tc_stock)

            # ── Remarks ───────────────────────────────────────────────────
            if not final_check:
                remarks = "Update status to " + final_status
            elif not stock_check:
                if final_status == "Active":
                    if comment == "Set max":
                        remarks = "Set max product"
                    elif reserved != 0:
                        remarks = "Due to Reserved Stock"
                    else:
                        remarks = "Make Impact"
                else:
                    remarks = "Stock not pushed due to Inactive Status"
            else:
                remarks = "All Good"

            push_0 = "Yes" if (tc_stock <= 0 and mp_stock > 0) else ""

            rows.append({
                "Marketplace":          mp_name,
                "SellerSku":            sku,
                "TC SKU":               tc_sku,
                "Product ID":           pid,
                "Article No":           article_no,
                "MP Status":            mp_status,
                "TC Status":            _normalise_status(tc_status),
                "e-com (Yes/No)":       ecom_yn,
                "Launch Date":          launch_dt,
                "Exclusion":            excl_lbl,
                "ECOM Status":          ecom_st,
                "Final Status":         final_status,
                "Comments":             comment,
                "Final Check":          str(final_check),
                "Dual Status":          dual_status,
                "Consolidated SUM QTY": consolidated_tc,
                "MP Stock":             mp_stock,
                "TC Stock":             tc_stock,
                "Reserved Stock":       reserved,
                "Max 0":                max_0,
                "Stock Check":          str(stock_check),
                "Remarks":              remarks,
                "Max Setup":            max_action,
                "Update 0":             push_0,
            })

    return pd.DataFrame(rows) if rows else pd.DataFrame()
