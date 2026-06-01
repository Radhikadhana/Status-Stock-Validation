import io
import re
import zipfile
import pandas as pd


def _safe_str(val):
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip()


def _read_file(file, header_row=0, skiprows=None):
    if file is None:
        return pd.DataFrame()
    name = file.name.lower()
    raw  = file.read()
    file.seek(0)
    try:
        if name.endswith(".csv"):
            return pd.read_csv(io.BytesIO(raw), header=header_row,
                               skiprows=skiprows, dtype=str)
        return pd.read_excel(io.BytesIO(raw), header=header_row,
                             skiprows=skiprows, dtype=str)
    except Exception:
        return pd.DataFrame()


def _read_zip(file, header_row=0, skiprows=None):
    raw = file.read()
    file.seek(0)
    frames = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for name in zf.namelist():
            if name.lower().endswith((".xlsx", ".xls", ".csv")):
                with zf.open(name) as f:
                    data = f.read()
                    try:
                        if name.lower().endswith(".csv"):
                            df = pd.read_csv(io.BytesIO(data), header=header_row,
                                             skiprows=skiprows, dtype=str)
                        else:
                            df = pd.read_excel(io.BytesIO(data), header=header_row,
                                               skiprows=skiprows, dtype=str)
                        frames.append(df)
                    except Exception:
                        continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _normalise_cols(df):
    df.columns = [_safe_str(c) for c in df.columns]
    return df


def _clean_sku(val):
    s = _safe_str(val)
    if re.fullmatch(r'\d+\.0', s):
        s = s[:-2]
    return s


def _filter_13digit_skus(df, sku_col):
    if sku_col not in df.columns:
        return df
    parent_cols = [c for c in df.columns
                   if "parent" in c.lower() and "sku" in c.lower()]
    if parent_cols:
        df = df.copy()
        mask_blank = df[sku_col].apply(_clean_sku) == ""
        df.loc[mask_blank, sku_col] = df.loc[mask_blank, parent_cols[0]]
    df[sku_col] = df[sku_col].apply(_clean_sku)
    df = df[df[sku_col].str.fullmatch(r'\d{13}', na=False)].copy()
    return df


def _ecom_status_from_val(val, future_launch):
    """
    Yes -> Active
    Future launch date -> Inactive (No Future launch)
    No / OFF / #N/A / blank -> Inactive
    """
    if bool(future_launch):
        return "Inactive (No Future launch)"
    s = _safe_str(val).upper()
    if s in ("YES", "Y"):
        return "Active"
    return "Inactive"


# ── Lazada ────────────────────────────────────────────────────────────────────

def load_lazada(file, country):
    if file is None:
        return pd.DataFrame()
    df = _read_file(file, header_row=0)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
    df = df.iloc[3:].reset_index(drop=True)
    col_map = {"SellerSKU": "SKU", "Quantity": "MP Stock", "status": "MP Status"}
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    if "SKU" not in df.columns:
        return pd.DataFrame()
    df["Marketplace"] = "Lazada " + country
    df["SKU"] = df["SKU"].apply(_clean_sku)
    df = df[df["SKU"] != ""].copy()
    if "MP Stock" in df.columns:
        df["MP Stock"] = pd.to_numeric(
            df["MP Stock"].apply(_safe_str), errors="coerce"
        ).fillna(0)
    return df


# ── Shopee ────────────────────────────────────────────────────────────────────

def _find_sku_col(df):
    for c in ["SKU", "Parent SKU", "Seller SKU", "SellerSKU", "ParentSKU"]:
        if c in df.columns:
            return c
    for c in df.columns:
        if "sku" in c.lower():
            return c
    return None


def _find_pid_col(df):
    for c in ["Product ID", "ProductID", "product_id"]:
        if c in df.columns:
            return c
    for c in df.columns:
        if "product" in c.lower() and "id" in c.lower():
            return c
    return None


def _parse_shopee_single(raw_bytes, filename_lower):
    """
    Parse one Shopee file (bytes).
    Tries header rows 2, 1, 0 and skips rows 3-5 after header.
    Returns cleaned DataFrame or empty DataFrame.
    """
    for hr in [2, 1, 0]:
        try:
            if filename_lower.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(raw_bytes), header=hr, dtype=str)
            else:
                df = pd.read_excel(io.BytesIO(raw_bytes), header=hr, dtype=str)
            if df.empty:
                continue
            df = _normalise_cols(df)
            cols_lower = [c.lower() for c in df.columns]
            if any("sku" in c or "product" in c for c in cols_lower):
                # Skip rows 4 & 5 after header (indices 0,1,2 in data = original rows 4,5,6)
                if len(df) > 3:
                    df = df.iloc[3:].reset_index(drop=True)
                return df
        except Exception:
            continue
    return pd.DataFrame()


def _load_shopee_raw(file):
    """
    Load Shopee file — supports both ZIP and single Excel/CSV.
    For ZIP: reads ALL files inside and concatenates them.
    Returns a single consolidated DataFrame.
    """
    if file is None:
        return pd.DataFrame()

    name = file.name.lower()
    raw  = file.read()
    file.seek(0)

    if name.endswith(".zip"):
        # Read every file inside the ZIP and consolidate
        frames = []
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for entry in zf.namelist():
                    entry_lower = entry.lower()
                    if entry_lower.endswith((".xlsx", ".xls", ".csv")):
                        with zf.open(entry) as f:
                            entry_bytes = f.read()
                        df = _parse_shopee_single(entry_bytes, entry_lower)
                        if not df.empty:
                            frames.append(df)
        except Exception:
            return pd.DataFrame()
        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True)
        combined = _normalise_cols(combined)
        return combined
    else:
        return _parse_shopee_single(raw, name)


def load_shopee_stock(file, country):
    """
    Load Shopee stock file (ZIP or single file).
    SKU = Parent SKU / SKU column (13-digit filter applied).
    Product ID = Product ID column.
    MP Stock = Stock / Quantity column.
    """
    df = _load_shopee_raw(file)
    if df.empty:
        return pd.DataFrame()

    sku_col = _find_sku_col(df)
    if sku_col is None:
        return pd.DataFrame()
    if sku_col != "SKU":
        df = df.rename(columns={sku_col: "SKU"})

    pid_col = _find_pid_col(df)
    if pid_col and pid_col != "Product ID":
        df = df.rename(columns={pid_col: "Product ID"})

    stock_col = None
    for c in ["Stock", "MP Stock", "Available Stock", "Current Stock", "Quantity"]:
        if c in df.columns:
            stock_col = c
            break
    if stock_col is None:
        for c in df.columns:
            if "stock" in c.lower() or "qty" in c.lower() or "quantity" in c.lower():
                stock_col = c
                break
    if stock_col and stock_col != "MP Stock":
        df = df.rename(columns={stock_col: "MP Stock"})

    df = _filter_13digit_skus(df, "SKU")
    df["Marketplace"] = "Shopee " + country
    if "MP Stock" in df.columns:
        df["MP Stock"] = pd.to_numeric(
            df["MP Stock"].apply(_safe_str), errors="coerce"
        ).fillna(0)
    else:
        df["MP Stock"] = 0.0
    return df


def load_shopee_status(file, country):
    """
    Load Shopee status file (ZIP or single file).
    MP Status logic:
      - If Product ID is present (not blank/nan) -> Active
      - If Product ID is missing/blank          -> Inactive
    This applies whether or not an explicit MP Status column exists.
    """
    df = _load_shopee_raw(file)
    if df.empty:
        return pd.DataFrame()

    # Find and clean Product ID column
    pid_col = _find_pid_col(df)
    if pid_col:
        df["Product ID"] = df[pid_col].apply(_clean_sku)
    else:
        df["Product ID"] = ""

    # Derive MP Status from Product ID presence
    # Product ID present (non-empty, non-nan) -> Active, else -> Inactive
    df["MP Status"] = df["Product ID"].apply(
        lambda x: "Active" if _safe_str(x) not in ("", "nan", "none") else "Inactive"
    )

    sku_col = _find_sku_col(df)
    if sku_col and sku_col != "SKU":
        df = df.rename(columns={sku_col: "SKU"})
    if "SKU" in df.columns:
        df = _filter_13digit_skus(df, "SKU")

    df["Marketplace"] = "Shopee " + country
    return df


# ── Zalora ────────────────────────────────────────────────────────────────────

def load_zalora_stock(file, country):
    if file is None:
        return pd.DataFrame()
    df = _read_file(file)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
    sku_col = None
    for c in ["SellerSku", "SellerSKU", "Seller Sku", "Seller SKU", "SKU"]:
        if c in df.columns:
            sku_col = c
            break
    if sku_col is None:
        for c in df.columns:
            if "sku" in c.lower() or "seller" in c.lower():
                sku_col = c
                break
    if sku_col is None:
        return pd.DataFrame()
    if sku_col != "SKU":
        df = df.rename(columns={sku_col: "SKU"})
    qty_col = None
    for c in ["Quantity", "Stock", "MP Stock", "quantity", "stock"]:
        if c in df.columns:
            qty_col = c
            break
    if qty_col and qty_col != "MP Stock":
        df = df.rename(columns={qty_col: "MP Stock"})
    df["SKU"] = df["SKU"].apply(_clean_sku)
    df["Marketplace"] = "Zalora " + country
    df = df[df["SKU"] != ""].copy()
    if "MP Stock" in df.columns:
        df["MP Stock"] = pd.to_numeric(
            df["MP Stock"].apply(_safe_str), errors="coerce"
        ).fillna(0)
    else:
        df["MP Stock"] = 0.0
    return df


def load_zalora_status(file, country):
    if file is None:
        return pd.DataFrame()
    df = _read_file(file)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
    sku_col = None
    for c in ["SellerSku", "SellerSKU", "Seller Sku", "Seller SKU", "SKU"]:
        if c in df.columns:
            sku_col = c
            break
    if sku_col is None:
        for c in df.columns:
            if "sku" in c.lower() or "seller" in c.lower():
                sku_col = c
                break
    if sku_col is None:
        return pd.DataFrame()
    if sku_col != "SKU":
        df = df.rename(columns={sku_col: "SKU"})
    status_col = None
    for c in ["Status", "MP Status", "status", "mp_status"]:
        if c in df.columns:
            status_col = c
            break
    if status_col is None:
        for c in df.columns:
            if "status" in c.lower():
                status_col = c
                break
    if status_col and status_col != "MP Status":
        df = df.rename(columns={status_col: "MP Status"})
    if "MP Status" in df.columns:
        df["MP Status"] = df["MP Status"].apply(_safe_str).str.strip().str.capitalize()
    else:
        df["MP Status"] = "Unknown"
    df["SKU"] = df["SKU"].apply(_clean_sku)
    df["Marketplace"] = "Zalora " + country
    return df[df["SKU"] != ""].copy()


# ── TikTok MY ─────────────────────────────────────────────────────────────────
# First 2 rows ignored, row 3 = header (index 2), rows 4-5 ignored

def _load_tiktok_raw(file):
    if file is None:
        return pd.DataFrame()
    df = _read_file(file, header_row=2)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
    if len(df) > 2:
        df = df.iloc[2:].reset_index(drop=True)
    return df


def _load_tiktok_file(file, status_label):
    if file is None:
        return pd.DataFrame()
    df = _load_tiktok_raw(file)
    if df.empty:
        return pd.DataFrame()
    sku_col = None
    for c in ["Seller SKU", "SellerSKU", "SKU", "seller sku"]:
        if c in df.columns:
            sku_col = c
            break
    if sku_col is None:
        for c in df.columns:
            if "sku" in c.lower():
                sku_col = c
                break
    if sku_col is None:
        return pd.DataFrame()
    pid_col = None
    for c in ["Product ID", "ProductID", "product_id", "product id"]:
        if c in df.columns:
            pid_col = c
            break
    if pid_col is None:
        for c in df.columns:
            if "product" in c.lower() and "id" in c.lower():
                pid_col = c
                break
    qty_col = None
    for c in ["Quantity", "Stock", "quantity", "stock", "Available Stock"]:
        if c in df.columns:
            qty_col = c
            break
    if qty_col is None:
        for c in df.columns:
            if "qty" in c.lower() or "quantity" in c.lower() or "stock" in c.lower():
                qty_col = c
                break
    out = pd.DataFrame()
    out["SKU"] = df[sku_col].apply(_clean_sku)
    if pid_col:
        out["Product ID"] = df[pid_col].apply(_safe_str)
    else:
        out["Product ID"] = ""
    out["MP Stock"] = pd.to_numeric(
        df[qty_col].apply(_safe_str) if qty_col else pd.Series([0] * len(df)),
        errors="coerce"
    ).fillna(0)
    out["MP Status"]   = status_label
    out["Marketplace"] = "TikTok MY"
    return out[out["SKU"] != ""].copy()


def load_tiktok(active_file, inactive_file):
    active   = _load_tiktok_file(active_file,   "Active")
    inactive = _load_tiktok_file(inactive_file, "Inactive")
    if active.empty and inactive.empty:
        return pd.DataFrame()
    combined = pd.concat([active, inactive], ignore_index=True)
    combined = combined.sort_values(
        "MP Status",
        key=lambda x: x.map({"Active": 0, "Inactive": 1}),
    )
    combined = combined.drop_duplicates(subset=["SKU"], keep="first")
    return combined.reset_index(drop=True)


# ── Content ───────────────────────────────────────────────────────────────────

def load_content(file):
    if file is None:
        return pd.DataFrame()
    df = _read_file(file)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
    if "EAN" in df.columns and "SKU" not in df.columns:
        df = df.rename(columns={"EAN": "SKU"})
    art_col = None
    for c in ["Article No", "Color_No", "Color_No.1", "ArticleNo", "Article Number"]:
        if c in df.columns:
            art_col = c
            break
    if art_col is None:
        for c in df.columns:
            if "article" in c.lower() or "color" in c.lower():
                art_col = c
                break
    if art_col and art_col != "Article No":
        df = df.rename(columns={art_col: "Article No"})
    if "SKU" in df.columns:
        df["SKU"] = df["SKU"].apply(_clean_sku)
    if "Article No" in df.columns:
        df["Article No"] = df["Article No"].apply(_safe_str)
    return df


# ── TC Inventory ──────────────────────────────────────────────────────────────
# Child SKU (GED1708197-01) takes priority over Parent SKU (GED1708197)
# Also returns TC SKU column as-is for output report

def load_tc_inventory(file):
    """
    TC Inventory column layout (from screenshot):
      Column 1 = Custom SKU  (13-digit barcode e.g. 4067983507151) -> used as SKU key
      Column 2 = SKU         (GED code e.g. GED4771311-01)         -> TC SKU for output
      Other    = Item status, Max Quantity, etc.

    Child/Parent priority:
      Child  = SKU contains "-"  e.g. GED4771311-01
      Parent = SKU without  "-"  e.g. GED4771311
      If a Custom SKU maps to both a child and parent entry,
      the child entry is preferred.
    """
    if file is None:
        return pd.DataFrame()
    df = pd.DataFrame()
    raw  = file.read()
    name = file.name.lower()
    file.seek(0)
    for header_row in [0, 1, 2]:
        try:
            if name.endswith(".csv"):
                tmp = pd.read_csv(io.BytesIO(raw), header=header_row, dtype=str)
            else:
                tmp = pd.read_excel(io.BytesIO(raw), header=header_row, dtype=str)
            if len(tmp.columns) > 2:
                df = tmp
                break
        except Exception:
            continue
    if df.empty:
        return pd.DataFrame()
    df.columns = [_safe_str(c) for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()].copy()
    df = df.reset_index(drop=True)
    actual_cols = list(df.columns)

    # ── Column 1: Custom SKU (barcode) — used as the lookup key ──────────────
    # This is always the first column
    custom_sku_col = None
    for c in ["Custom SKU", "CustomSKU", "Barcode", "EAN"]:
        if c in actual_cols:
            custom_sku_col = c
            break
    if custom_sku_col is None:
        # Fall back to first column
        custom_sku_col = actual_cols[0] if actual_cols else None

    # ── Column 2: SKU (GED code) — shown in output as TC SKU ─────────────────
    # This is always the second column (the GED parent/child code)
    ged_sku_col = None
    for c in ["SKU", "Sku", "sku"]:
        if c in actual_cols and c != custom_sku_col:
            ged_sku_col = c
            break
    if ged_sku_col is None:
        # Fall back to second column
        if len(actual_cols) > 1:
            ged_sku_col = actual_cols[1]
        else:
            ged_sku_col = custom_sku_col

    # ── Status column ─────────────────────────────────────────────────────────
    status_col = None
    for c in ["Item status", "Item Status", "Status", "TC Status",
               "ItemStatus", "item status"]:
        if c in actual_cols:
            status_col = c
            break
    if status_col is None:
        for c in actual_cols:
            if "status" in c.lower() and c not in (custom_sku_col, ged_sku_col):
                status_col = c
                break

    # ── Max Quantity column ───────────────────────────────────────────────────
    max_col = None
    for c in ["Max Quantity", "MaxQuantity", "Max", "Maximum Quantity",
               "max_quantity", "max quantity"]:
        if c in actual_cols:
            max_col = c
            break
    if max_col is None:
        for c in actual_cols:
            if "max" in c.lower() and c not in (custom_sku_col, ged_sku_col, status_col):
                max_col = c
                break

    # ── Build output DataFrame ────────────────────────────────────────────────
    out = pd.DataFrame()
    # SKU = Custom SKU (barcode) used as join key with marketplace files
    out["SKU"]       = df[custom_sku_col].apply(_clean_sku) if custom_sku_col else ""
    # TC SKU = GED code from second column, shown in output report
    out["TC SKU"]    = df[ged_sku_col].apply(_safe_str) if ged_sku_col else ""
    out["TC Status"] = df[status_col].apply(_safe_str) if status_col else "Unknown"
    if max_col:
        out["Max Quantity"] = df[max_col].apply(_safe_str)
        out["Max 0"] = out["Max Quantity"].apply(
            lambda x: "Yes" if _safe_str(x) == "0" else "No"
        )
    else:
        out["Max Quantity"] = ""
        out["Max 0"]        = "No"

    out = out[out["SKU"] != ""].copy()

    # ── Child/Parent deduplication ────────────────────────────────────────────
    # If same Custom SKU (barcode) maps to both a child GED code (with "-")
    # and a parent GED code (without "-"), keep the child entry.
    out["_is_child"] = out["TC SKU"].str.contains("-", na=False).astype(int)
    out = out.sort_values("_is_child", ascending=False)  # child first
    out = out.drop_duplicates(subset=["SKU"], keep="first")
    out = out.drop(columns=["_is_child"])
    out = out.reset_index(drop=True)

    return out


# ── zEcom ─────────────────────────────────────────────────────────────────────
# PH  -> Article No column = "PIM Article#", header row 3 (index 2)
# MY  -> Article No column = "Style#",       header row 4 (index 3)
# SG  -> Article No column = "STYLE#",       header row 4 (index 3)

def load_zecom(file, country="PH"):
    if file is None:
        return pd.DataFrame()
    raw  = file.read()
    name = file.name.lower()
    file.seek(0)

    article_col_by_country = {
        "PH": ["PIM Article#", "PIM Article #", "Article No", "ArticleNo"],
        "MY": ["Style#", "STYLE#", "style#", "Article No", "PIM Article#"],
        "SG": ["STYLE#", "Style#", "style#", "Article No", "PIM Article#"],
    }
    preferred_article_cols = article_col_by_country.get(country, ["Article No"])
    preferred_rows = [2, 1, 0, 3] if country == "PH" else [3, 2, 1, 0]

    df = pd.DataFrame()
    for header_row in preferred_rows:
        try:
            if name.endswith(".csv"):
                tmp = pd.read_csv(io.BytesIO(raw), header=header_row, dtype=str)
            else:
                tmp = pd.read_excel(io.BytesIO(raw), header=header_row, dtype=str)
            tmp.columns = [_safe_str(c) for c in tmp.columns]
            col_lower = [c.lower() for c in tmp.columns]
            expected  = [c.lower() for c in preferred_article_cols]
            if any(e in col_lower for e in expected):
                df = tmp
                break
            if any("article" in c or "pim" in c or "style" in c for c in col_lower):
                df = tmp
                break
        except Exception:
            continue

    if df.empty:
        return pd.DataFrame()

    df = df.loc[:, ~df.columns.duplicated()].copy()
    df = df.reset_index(drop=True)
    first_col = df.columns[0]
    df = df[df[first_col].apply(_safe_str) != first_col].copy()
    df = df[df[first_col].apply(_safe_str) != ""].copy()
    df = df.reset_index(drop=True)

    # Rename Article No column
    article_col = None
    for c in preferred_article_cols:
        if c in df.columns:
            article_col = c
            break
    if article_col is None:
        for c in df.columns:
            if "style" in c.lower() or "article" in c.lower() or "pim" in c.lower():
                article_col = c
                break
    if article_col and article_col != "Article No":
        df = df.rename(columns={article_col: "Article No"})

    # Rename Launch Date column
    launch_col = None
    for c in ["Launch Dates", "Launch Date", "LaunchDate", "Launch"]:
        if c in df.columns:
            launch_col = c
            break
    if launch_col is None:
        for c in df.columns:
            if "launch" in c.lower():
                launch_col = c
                break
    if launch_col and launch_col != "Launch Date":
        df = df.rename(columns={launch_col: "Launch Date"})

    # Future launch flag
    today = pd.Timestamp.today().normalize()
    if "Launch Date" in df.columns:
        df["Launch Date"] = pd.to_datetime(df["Launch Date"], errors="coerce")
        df["Future Launch"] = df["Launch Date"].apply(
            lambda d: True if pd.notna(d) and d > today else False
        )
    else:
        df["Future Launch"] = False

    # Build standardised Ecom_ columns
    mp_keywords = {
        "lazada":  "Ecom_Lazada",
        "shopee":  "Ecom_Shopee",
        "zalora":  "Ecom_Zalora",
        "tiktok":  "Ecom_TikTok",
    }
    for col in df.columns:
        if col in ("Article No", "Launch Date", "Future Launch"):
            continue
        col_l = col.lower()
        for mp_key, ecom_name in mp_keywords.items():
            if mp_key in col_l and ecom_name not in df.columns:
                df[ecom_name] = df.apply(
                    lambda row, c=col: _ecom_status_from_val(
                        row[c], row["Future Launch"]
                    ),
                    axis=1,
                )
                break

    return df


# ── Exclusion List ────────────────────────────────────────────────────────────

def load_exclusion(file):
    if file is None:
        return pd.DataFrame()
    df = _read_file(file)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
    art_col = None
    for c in ["Article No", "ArticleNo", "Article Number", "STYLE#", "Style#"]:
        if c in df.columns:
            art_col = c
            break
    if art_col is None:
        for c in df.columns:
            if "article" in c.lower() or "style" in c.lower():
                art_col = c
                break
    status_col = None
    for c in ["Status", "status", "Exclusion Status", "AM Status"]:
        if c in df.columns:
            status_col = c
            break
    if status_col is None:
        for c in df.columns:
            if "status" in c.lower():
                status_col = c
                break
    if art_col is None:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["Article No"] = df[art_col].apply(_safe_str)
    out["Exclusion Status"] = (
        df[status_col].apply(_safe_str) if status_col else "Inactive"
    )
    return out[out["Article No"] != ""].reset_index(drop=True)


# ── ALL File ──────────────────────────────────────────────────────────────────

def load_all_file(file, country):
    if file is None:
        return pd.DataFrame()
    df = _read_file(file)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
    stock_col_map = {
        "SG": ("MyStock-YCH-SG quantity",  "MyStock-YCH-SG reservedQuantity"),
        "MY": ("MyStock-YCH-MY quantity",  "MyStock-YCH-MY reservedQuantity"),
        "PH": ("MyStock-PH quantity",      "MyStock-PH reservedQuantity"),
    }
    stock_col, reserved_col = stock_col_map.get(country, ("", ""))
    for c in ["sellerSKU", "SellerSKU", "SKU", "Seller SKU"]:
        if c in df.columns:
            df = df.rename(columns={c: "SKU"})
            break
    if stock_col and stock_col in df.columns and "TC Stock" not in df.columns:
        df = df.rename(columns={stock_col: "TC Stock"})
    elif "TC Stock" not in df.columns:
        for c in df.columns:
            if "quantity" in c.lower() and country.lower() in c.lower():
                df = df.rename(columns={c: "TC Stock"})
                break
    if reserved_col and reserved_col in df.columns and "Reserved Stock" not in df.columns:
        df = df.rename(columns={reserved_col: "Reserved Stock"})
    elif "Reserved Stock" not in df.columns:
        for c in df.columns:
            if "reserved" in c.lower():
                df = df.rename(columns={c: "Reserved Stock"})
                break
    if "SKU" not in df.columns:
        return pd.DataFrame()
    df["SKU"] = df["SKU"].apply(_clean_sku)
    for num_col in ["TC Stock", "Reserved Stock"]:
        if num_col in df.columns:
            df[num_col] = pd.to_numeric(
                df[num_col].apply(_safe_str), errors="coerce"
            ).fillna(0)
        else:
            df[num_col] = 0.0
    return df[df["SKU"] != ""].copy()


# ── Master loader ─────────────────────────────────────────────────────────────

def load_all_files(
    country,
    lazada_file, shopee_stock_file, shopee_status_file,
    zalora_stock_file, zalora_status_file,
    tiktok_active_file, tiktok_inactive_file,
    content_file, tc_inv_file, zecom_file, all_file,
    exclusion_file=None,
):
    data = {}
    data["lazada"] = load_lazada(lazada_file, country)

    shopee_stock  = load_shopee_stock(shopee_stock_file, country)
    shopee_status = load_shopee_status(shopee_status_file, country)
    if not shopee_stock.empty and not shopee_status.empty:
        merge_keys = [k for k in ["SKU", "Product ID"]
                      if k in shopee_stock.columns and k in shopee_status.columns]
        if merge_keys:
            shopee = pd.merge(
                shopee_stock,
                shopee_status[merge_keys + ["MP Status"]].drop_duplicates(merge_keys),
                on=merge_keys, how="left",
            )
        else:
            shopee = shopee_stock.copy()
            shopee["MP Status"] = "Unknown"
    elif not shopee_stock.empty:
        shopee = shopee_stock
        if "MP Status" not in shopee.columns:
            shopee["MP Status"] = "Unknown"
    else:
        shopee = shopee_status if not shopee_status.empty else pd.DataFrame()
    data["shopee"] = shopee

    zalora_stock  = load_zalora_stock(zalora_stock_file, country)
    zalora_status = load_zalora_status(zalora_status_file, country)
    if (not zalora_stock.empty and not zalora_status.empty
            and "SKU" in zalora_stock.columns
            and "SKU" in zalora_status.columns):
        zalora = pd.merge(
            zalora_stock,
            zalora_status[["SKU", "MP Status"]],
            on="SKU", how="left",
        )
    else:
        zalora = zalora_stock.copy() if not zalora_stock.empty else pd.DataFrame()
    data["zalora"] = zalora

    if country == "MY":
        data["tiktok"] = load_tiktok(tiktok_active_file, tiktok_inactive_file)
    else:
        data["tiktok"] = pd.DataFrame()

    data["content"]   = load_content(content_file)
    data["tc_inv"]    = load_tc_inventory(tc_inv_file)
    data["zecom"]     = load_zecom(zecom_file, country)
    data["all_file"]  = load_all_file(all_file, country)
    data["exclusion"] = load_exclusion(exclusion_file)
    return data
