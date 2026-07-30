# VERSION: v14 - Shopee MP Status fix
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


def _read_file(file, header_row=0, skiprows=None, usecols=None):
    if file is None:
        return pd.DataFrame()
    name = file.name.lower()
    try:
        file.seek(0)
        raw_bytes = file.read()
        file.seek(0)
        bio = io.BytesIO(raw_bytes)
        if name.endswith(".csv"):
            return pd.read_csv(bio, header=header_row,
                             skiprows=skiprows, dtype=str, usecols=usecols)
        try:
            import python_calamine
            return pd.read_excel(bio, header=header_row,
                               skiprows=skiprows, dtype=str, engine="calamine", usecols=usecols)
        except ImportError:
            return pd.read_excel(bio, header=header_row,
                               skiprows=skiprows, dtype=str, usecols=usecols)
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
                             try:
                                 import python_calamine
                                 df = pd.read_excel(io.BytesIO(data), header=header_row,
                                                    skiprows=skiprows, dtype=str, engine="calamine")
                             except ImportError:
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
    
    import numpy as np
    def clean_ser(ser):
        s = ser.fillna("").astype(str).str.strip()
        float_mask = s.str.match(r'^\d+\.0$', na=False)
        return np.where(float_mask, s.str[:-2], s)

    parent_cols = [c for c in df.columns
                   if "parent" in c.lower() and "sku" in c.lower()]
    if parent_cols:
        df = df.copy()
        cleaned_sku = clean_ser(df[sku_col])
        mask_blank = cleaned_sku == ""
        df.loc[mask_blank, sku_col] = df.loc[mask_blank, parent_cols[0]]
        
    df[sku_col] = clean_ser(df[sku_col])
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
    
    # Read the header first to find the matching column names
    file.seek(0)
    if file.name.lower().endswith(".csv"):
        header_df = pd.read_csv(file, nrows=1)
    else:
        try:
            import python_calamine
            header_df = pd.read_excel(file, nrows=1, engine="calamine")
        except ImportError:
            header_df = pd.read_excel(file, nrows=1)
    file.seek(0)
    
    actual_cols = list(header_df.columns)
    usecols = []
    for c in ["SellerSKU", "Quantity", "status"]:
        if c in actual_cols:
            usecols.append(c)
            
    df = _read_file(file, header_row=0, usecols=usecols if usecols else None)
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
    # Slice only needed columns to keep memory low
    keep_cols = [c for c in ["SKU", "MP Stock", "MP Status", "Marketplace"] if c in df.columns]
    return df[keep_cols].copy()


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
    Parse one Shopee export file.

    Confirmed Shopee export structure (from real files):
      Row 0: internal keys  (et_title_product_id ...)
      Row 1: metadata
      Row 2: REAL HEADER    (Product ID, Parent SKU, SKU, Stock ...)
      Row 3: Mandatory instruction row  -> skip
      Row 4: blank                      -> skip
      Row 5: validation note            -> skip
      Row 6+: actual data

    Engine priority:
      1. calamine  (handles Shopee conditional formatting — install python-calamine)
      2. openpyxl  (fallback, may warn but usually works)
      3. xlrd      (last resort for older xlsx)
    """
    import warnings

    # Identify matching columns from header at row index 2
    usecols = None
    try:
        if filename_lower.endswith(".csv"):
            header_df = pd.read_csv(io.BytesIO(raw_bytes), header=2, nrows=1)
        else:
            try:
                import python_calamine
                header_df = pd.read_excel(io.BytesIO(raw_bytes), header=2, nrows=1, engine="calamine")
            except ImportError:
                header_df = pd.read_excel(io.BytesIO(raw_bytes), header=2, nrows=1)
        cols = list(header_df.columns)
        # Keep only columns containing relevant keywords to keep memory minimal
        usecols = [c for c in cols if any(kw in c.lower() for kw in ["sku", "product", "stock", "quantity", "qty", "available", "current", "parent", "status"])]
    except Exception:
        pass

    if filename_lower.endswith(".csv"):
        try:
            df = pd.read_csv(io.BytesIO(raw_bytes), header=2, dtype=str, usecols=usecols)
            df = _normalise_cols(df)
            df = df.iloc[3:].reset_index(drop=True)
            df = df.dropna(how="all").reset_index(drop=True)
            return df
        except Exception:
            return pd.DataFrame()

    # Build engine list — calamine first
    engines = []
    try:
        import python_calamine  # noqa
        engines.append("calamine")
    except ImportError:
        pass
    engines.append("openpyxl")

    for engine in engines:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df = pd.read_excel(
                    io.BytesIO(raw_bytes),
                    header=2,
                    dtype=str,
                    engine=engine,
                    usecols=usecols
                )
            if df is None or df.empty:
                continue
            df = _normalise_cols(df)
            # Skip first 3 rows after header (instruction/blank rows)
            if len(df) > 3:
                df = df.iloc[3:].reset_index(drop=True)
            df = df.dropna(how="all").reset_index(drop=True)
            # Must have at least SKU or Product columns to be valid
            cols_lower = [c.lower() for c in df.columns]
            if (any("sku" in c for c in cols_lower) or
                    any("product" in c for c in cols_lower)):
                if len(df) > 0:
                    return df
        except Exception:
            continue

    # Last resort: try reading with openpyxl ignoring all validation
    try:
        import openpyxl
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(
                io.BytesIO(raw_bytes), data_only=True, read_only=True
            )
            ws = wb.active
            rows_data = []
            for row in ws.iter_rows(values_only=True):
                rows_data.append(list(row))
            wb.close()
        if len(rows_data) < 7:
            return pd.DataFrame()
        # Row index 2 = header
        header = [str(v).strip() if v is not None else "" for v in rows_data[2]]
        data_rows = rows_data[6:]  # skip rows 3,4,5
        df = pd.DataFrame(data_rows, columns=header)
        df = df.astype(str)
        df = df.replace("None", "")
        df = _normalise_cols(df)
        
        # Apply the same usecols filter to the fallback dataframe to save memory
        if usecols:
            keep_cols = [c for c in df.columns if c in usecols]
            df = df[keep_cols].copy()
            
        df = df.dropna(how="all").reset_index(drop=True)
        cols_lower = [c.lower() for c in df.columns]
        if (any("sku" in c for c in cols_lower) or
                any("product" in c for c in cols_lower)):
            return df
    except Exception:
        pass

    return pd.DataFrame()


def _load_shopee_raw(file):
    """
    Load Shopee file — supports:
    - ZIP containing multiple xlsx files (reads ALL, consolidates)
    - Single xlsx or csv file
    Returns one consolidated DataFrame.
    """
    if file is None:
        return pd.DataFrame()

    name = file.name.lower()
    raw  = file.read()
    file.seek(0)

    if name.endswith(".zip"):
        frames = []
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for entry in sorted(zf.namelist()):
                    if entry.lower().endswith((".xlsx", ".xls", ".csv")):
                        with zf.open(entry) as f:
                            entry_bytes = f.read()
                        df = _parse_shopee_single(entry_bytes, entry.lower())
                        if not df.empty:
                            frames.append(df)
        except Exception:
            return pd.DataFrame()
        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True)
        return _normalise_cols(combined)
    else:
        return _parse_shopee_single(raw, name)


def load_shopee_stock(file, country):
    """
    Load Shopee stock file (ZIP containing multiple xlsx files, or single file).

    Column logic (confirmed from real Shopee export structure):
      Row 2 (index 2) = real header:
        Product ID  | Parent SKU   | SKU           | Stock
        58158713196 | 404620_07    | 4069161482557 | 10     <- child row
        58158713196 | (blank)      | 4069161482595 | 12     <- child row

    SKU resolution:
      1. Use "SKU" column (child 13-digit barcode) if present and non-blank
      2. If "SKU" is blank, fall back to "Parent SKU" column value
      3. Keep only rows where resolved SKU is exactly 13 digits
      4. Drop all other rows (non-13-digit = invalid)

    ZIP handling: all xlsx files inside ZIP are consolidated into one DataFrame.
    """
    df = _load_shopee_raw(file)
    if df.empty:
        return pd.DataFrame()

    # ── Find Product ID column ──────────────────────────────────────────────
    pid_col = _find_pid_col(df)
    if pid_col and pid_col != "Product ID":
        df = df.rename(columns={pid_col: "Product ID"})

    # ── Find SKU column (child barcode) ─────────────────────────────────────
    # Priority: "SKU" > "Variation SKU" > other sku-like columns
    # Do NOT use "Parent SKU" as the primary SKU column
    sku_col = None
    for c in ["SKU", "Variation SKU", "VariationSKU"]:
        if c in df.columns:
            sku_col = c
            break
    if sku_col is None:
        for c in df.columns:
            cl = c.lower()
            if "sku" in cl and "parent" not in cl:
                sku_col = c
                break

    # ── Find Parent SKU column ───────────────────────────────────────────────
    parent_col = None
    for c in ["Parent SKU", "ParentSKU", "parent_sku", "parent sku"]:
        if c in df.columns:
            parent_col = c
            break
    if parent_col is None:
        for c in df.columns:
            if "parent" in c.lower() and "sku" in c.lower():
                parent_col = c
                break

    # ── Find Stock column ────────────────────────────────────────────────────
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

    # ── Build effective SKU: child first, fallback to Parent SKU ─────────────
    if sku_col:
        df["SKU"] = df[sku_col].apply(_clean_sku)
    else:
        df["SKU"] = ""

    if parent_col:
        # Where SKU is blank, fill from Parent SKU
        mask_blank = df["SKU"] == ""
        df.loc[mask_blank, "SKU"] = (
            df.loc[mask_blank, parent_col].apply(_clean_sku)
        )

    # ── Keep only 13-digit SKUs ──────────────────────────────────────────────
    df = df[df["SKU"].str.fullmatch(r"\d{13}", na=False)].copy()
    df = df.reset_index(drop=True)

    if df.empty:
        return pd.DataFrame()

    # ── Rename stock column ───────────────────────────────────────────────────
    if stock_col and stock_col != "MP Stock":
        df = df.rename(columns={stock_col: "MP Stock"})

    df["Marketplace"] = "Shopee " + country
    if "MP Stock" in df.columns:
        df["MP Stock"] = pd.to_numeric(
            df["MP Stock"].apply(_safe_str), errors="coerce"
        ).fillna(0)
    else:
        df["MP Stock"] = 0.0

    # Slice only needed columns to keep memory low
    keep_cols = [c for c in ["SKU", "Product ID", "MP Stock", "Marketplace"] if c in df.columns]
    return df[keep_cols].copy()


def load_shopee_status(file, country):
    """
    Load Shopee status/basic_info file.
    Structure same as stock file:
      Row 0: internal keys
      Row 1: metadata
      Row 2: REAL HEADER (Product ID, Parent SKU, Product Name ...)
      Rows 3-5: skip
      Row 6+: actual data

    MP Status logic:
      Product ID present (non-empty) -> Active
      Product ID missing/blank       -> Inactive
    """
    df = _load_shopee_raw(file)
    if df.empty:
        return pd.DataFrame()

    # Find Product ID column
    pid_col = _find_pid_col(df)
    if pid_col:
        if pid_col != "Product ID":
            df = df.rename(columns={pid_col: "Product ID"})
        df["Product ID"] = df["Product ID"].apply(_safe_str)
    else:
        df["Product ID"] = ""

    # Derive MP Status from Product ID presence
    df["MP Status"] = df["Product ID"].apply(
        lambda x: "Active" if _safe_str(x) not in ("", "nan", "none") else "Inactive"
    )

    # Find SKU column (13-digit barcode) — may not exist in basic_info file
    sku_col = None
    for c in ["SKU", "Variation SKU", "Seller SKU"]:
        if c in df.columns:
            sku_col = c
            break
    if sku_col is None:
        for c in df.columns:
            if "sku" in c.lower() and "parent" not in c.lower():
                sku_col = c
                break

    if sku_col and sku_col != "SKU":
        df = df.rename(columns={sku_col: "SKU"})

    # Find Parent SKU column
    parent_col = None
    for c in ["Parent SKU", "ParentSKU", "parent_sku", "parent sku"]:
        if c in df.columns:
            parent_col = c
            break
    if parent_col is None:
        for c in df.columns:
            if "parent" in c.lower() and "sku" in c.lower():
                parent_col = c
                break

    # Only apply 13-digit filter if SKU column exists and has 13-digit values
    if "SKU" in df.columns:
        df["SKU"] = df["SKU"].apply(_clean_sku)
        
        # Fallback to Parent SKU where SKU is blank (same as stock loader logic)
        if parent_col:
            mask_blank = df["SKU"] == ""
            df.loc[mask_blank, "SKU"] = (
                df.loc[mask_blank, parent_col].apply(_clean_sku)
            )
            
        has_13 = df["SKU"].str.fullmatch(r'\d{13}', na=False).any()
        if has_13:
            df = df[df["SKU"].str.fullmatch(r'\d{13}', na=False)].copy()
    else:
        # No SKU column — use Product ID as identifier for status merge
        df["SKU"] = ""

    df["Marketplace"] = "Shopee " + country
    # Slice only needed columns to keep memory low
    keep_cols = [c for c in ["SKU", "Product ID", "MP Status", "Marketplace"] if c in df.columns]
    return df[keep_cols].copy()


def load_zalora_stock(file, country):
    if file is None:
        return pd.DataFrame()
    
    file.seek(0)
    if file.name.lower().endswith(".csv"):
        header_df = pd.read_csv(file, nrows=1)
    else:
        try:
            import python_calamine
            header_df = pd.read_excel(file, nrows=1, engine="calamine")
        except ImportError:
            header_df = pd.read_excel(file, nrows=1)
    file.seek(0)
    
    actual_cols = list(header_df.columns)
    usecols = []
    
    sku_col = None
    for c in ["SellerSku", "SellerSKU", "Seller Sku", "Seller SKU", "SKU"]:
        if c in actual_cols:
            sku_col = c
            break
    if sku_col is None:
        for c in actual_cols:
            if "sku" in c.lower() or "seller" in c.lower():
                sku_col = c
                break
                
    qty_col = None
    for c in ["Quantity", "Stock", "MP Stock", "quantity", "stock"]:
        if c in actual_cols:
            qty_col = c
            break
            
    if sku_col: usecols.append(sku_col)
    if qty_col: usecols.append(qty_col)
    
    df = _read_file(file, usecols=usecols if usecols else None)
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
    # Slice only needed columns to keep memory low
    keep_cols = [c for c in ["SKU", "MP Stock", "Marketplace"] if c in df.columns]
    return df[keep_cols].copy()


def load_zalora_status(file, country):
    if file is None:
        return pd.DataFrame()
        
    file.seek(0)
    if file.name.lower().endswith(".csv"):
        header_df = pd.read_csv(file, nrows=1)
    else:
        try:
            import python_calamine
            header_df = pd.read_excel(file, nrows=1, engine="calamine")
        except ImportError:
            header_df = pd.read_excel(file, nrows=1)
    file.seek(0)
    
    actual_cols = list(header_df.columns)
    usecols = []
    
    sku_col = None
    for c in ["SellerSku", "SellerSKU", "Seller Sku", "Seller SKU", "SKU"]:
        if c in actual_cols:
            sku_col = c
            break
    if sku_col is None:
        for c in actual_cols:
            if "sku" in c.lower() or "seller" in c.lower():
                sku_col = c
                break
                
    status_col = None
    for c in ["Status", "MP Status", "status", "mp_status"]:
        if c in actual_cols:
            status_col = c
            break
    if status_col is None:
        for c in actual_cols:
            if "status" in c.lower():
                status_col = c
                break
                
    if sku_col: usecols.append(sku_col)
    if status_col: usecols.append(status_col)
    
    df = _read_file(file, usecols=usecols if usecols else None)
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
    df = df[df["SKU"] != ""].copy()
    # Slice only needed columns to keep memory low
    keep_cols = [c for c in ["SKU", "MP Status", "Marketplace"] if c in df.columns]
    return df[keep_cols].copy()


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
        
    file.seek(0)
    if file.name.lower().endswith(".csv"):
        header_df = pd.read_csv(file, nrows=1)
    else:
        try:
            import python_calamine
            header_df = pd.read_excel(file, nrows=1, engine="calamine")
        except ImportError:
            header_df = pd.read_excel(file, nrows=1)
    file.seek(0)
    
    actual_cols = list(header_df.columns)
    
    sku_col = None
    if "SKU" in actual_cols:
        sku_col = "SKU"
    elif "EAN" in actual_cols:
        sku_col = "EAN"
        
    art_col = None
    for c in ["Article No", "Color_No", "Color_No.1", "ArticleNo", "Article Number"]:
        if c in actual_cols:
            art_col = c
            break
    if art_col is None:
        for c in actual_cols:
            if "article" in c.lower() or "color" in c.lower():
                art_col = c
                break
                
    usecols = []
    if sku_col: usecols.append(sku_col)
    if art_col: usecols.append(art_col)
    
    df = _read_file(file, usecols=usecols if usecols else None)
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
    # Slice only needed columns to keep memory low
    keep_cols = [c for c in ["SKU", "Article No"] if c in df.columns]
    return df[keep_cols].copy()


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
    raw = file.read()
    name = file.name.lower()
    file.seek(0)
    try:
        if name.endswith(".csv"):
            raw_df = pd.read_csv(io.BytesIO(raw), header=None, nrows=10, dtype=str)
        else:
            try:
                import python_calamine
                raw_df = pd.read_excel(io.BytesIO(raw), header=None, nrows=10, dtype=str, engine="calamine")
            except ImportError:
                raw_df = pd.read_excel(io.BytesIO(raw), header=None, nrows=10, dtype=str)
    except Exception:
        return pd.DataFrame()

    if raw_df.empty:
        return pd.DataFrame()

    header_idx = 0
    for i in range(min(5, len(raw_df))):
        row_vals = [_safe_str(x) for x in raw_df.iloc[i]]
        row_lower = [v.lower() for v in row_vals]
        if any(h in row_lower for h in ["custom sku", "customsku", "barcode", "ean", "sku", "item status", "status"]):
            header_idx = i
            break
        non_empty = sum(1 for v in row_vals if v != "")
        if non_empty > 2 and header_idx == 0:
            header_idx = i

    header_row_vals = [_safe_str(x) for x in raw_df.iloc[header_idx]]
    
    custom_sku_col_idx = 0
    for idx, c in enumerate(header_row_vals):
        if c in ["Custom SKU", "CustomSKU", "Barcode", "EAN"]:
            custom_sku_col_idx = idx
            break
            
    ged_sku_col_idx = 1 if len(header_row_vals) > 1 else 0
    for idx, c in enumerate(header_row_vals):
        if c in ["SKU", "Sku", "sku"] and idx != custom_sku_col_idx:
            ged_sku_col_idx = idx
            break
            
    status_col_idx = None
    for idx, c in enumerate(header_row_vals):
        if c in ["Item status", "Item Status", "Status", "TC Status", "ItemStatus", "item status"]:
            status_col_idx = idx
            break
    if status_col_idx is None:
        for idx, c in enumerate(header_row_vals):
            if "status" in c.lower() and idx not in (custom_sku_col_idx, ged_sku_col_idx):
                status_col_idx = idx
                break
                
    max_col_idx = None
    for idx, c in enumerate(header_row_vals):
        if c in ["Max Quantity", "MaxQuantity", "Max", "Maximum Quantity", "max_quantity", "max quantity"]:
            max_col_idx = idx
            break
    if max_col_idx is None:
        for idx, c in enumerate(header_row_vals):
            if "max" in c.lower() and idx not in (custom_sku_col_idx, ged_sku_col_idx, status_col_idx):
                max_col_idx = idx
                break
                
    usecols_indices = [custom_sku_col_idx, ged_sku_col_idx]
    if status_col_idx is not None:
        usecols_indices.append(status_col_idx)
    if max_col_idx is not None:
        usecols_indices.append(max_col_idx)
    usecols_indices = sorted(list(set(usecols_indices)))
    
    try:
        if name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(raw), header=None, skiprows=header_idx + 1, usecols=usecols_indices, dtype=str)
        else:
            try:
                import python_calamine
                df = pd.read_excel(io.BytesIO(raw), header=None, skiprows=header_idx + 1, usecols=usecols_indices, dtype=str, engine="calamine")
            except ImportError:
                df = pd.read_excel(io.BytesIO(raw), header=None, skiprows=header_idx + 1, usecols=usecols_indices, dtype=str)
    except Exception:
        return pd.DataFrame()
        
    if df.empty:
        return pd.DataFrame()

    col_mapping = {}
    for idx in usecols_indices:
        col_mapping[idx] = header_row_vals[idx]
    df = df.rename(columns=col_mapping)
    df = df.loc[:, ~df.columns.duplicated()].copy()
    df = df.reset_index(drop=True)
    
    custom_sku_col = header_row_vals[custom_sku_col_idx]
    ged_sku_col = header_row_vals[ged_sku_col_idx]
    status_col = header_row_vals[status_col_idx] if status_col_idx is not None else None
    max_col = header_row_vals[max_col_idx] if max_col_idx is not None else None

    # Build output DataFrame
    import numpy as np
    out = pd.DataFrame()
    if custom_sku_col in df.columns:
        s_sku = df[custom_sku_col].fillna("").astype(str).str.strip()
        float_mask = s_sku.str.match(r'^\d+\.0$', na=False)
        out["SKU"] = np.where(float_mask, s_sku.str[:-2], s_sku)
    else:
        out["SKU"] = ""
        
    out["TC SKU"] = df[ged_sku_col].fillna("").astype(str).str.strip() if ged_sku_col in df.columns else ""
    out["TC Status"] = df[status_col].fillna("").astype(str).str.strip() if (status_col and status_col in df.columns) else "Unknown"
    
    if max_col and max_col in df.columns:
        out["Max Quantity"] = df[max_col].fillna("").astype(str).str.strip()
        out["Max 0"] = np.where(out["Max Quantity"] == "0", "Yes", "No")
    else:
        out["Max Quantity"] = ""
        out["Max 0"]        = "No"

    out = out[out["SKU"] != ""].copy()

    # Child/Parent deduplication
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

    try:
        if name.endswith(".csv"):
            raw_df = pd.read_csv(io.BytesIO(raw), header=None, nrows=10, dtype=str)
        else:
            try:
                import python_calamine
                xl = pd.ExcelFile(io.BytesIO(raw), engine="calamine")
            except ImportError:
                xl = pd.ExcelFile(io.BytesIO(raw))
            
            sheet_names = xl.sheet_names
            target_sheet = sheet_names[0]
            
            country_lower = country.lower().strip()
            country_keywords = {
                "my": ["my", "malaysia"],
                "sg": ["sg", "singapore"],
                "ph": ["ph", "phil", "philippines"]
            }
            keywords = country_keywords.get(country_lower, [country_lower])
            
            matched_sheet = None
            for s_name in sheet_names:
                s_name_lower = s_name.lower().strip()
                if s_name_lower in keywords:
                    matched_sheet = s_name
                    break
            
            if not matched_sheet:
                for s_name in sheet_names:
                    s_name_lower = s_name.lower().strip()
                    cleaned_s_name = re.sub(r'[^a-z0-9]', ' ', s_name_lower)
                    for kw in keywords:
                        if re.search(r'\b' + re.escape(kw) + r'\b', cleaned_s_name):
                            matched_sheet = s_name
                            break
                    if matched_sheet:
                        break
            
            if not matched_sheet:
                for s_name in sheet_names:
                    s_name_lower = s_name.lower().strip()
                    if any(kw in s_name_lower for kw in keywords):
                        matched_sheet = s_name
                        break
            
            if matched_sheet:
                target_sheet = matched_sheet
                
            raw_df = xl.parse(target_sheet, header=None, nrows=10, dtype=str)
    except Exception:
        return pd.DataFrame()

    if raw_df.empty:
        return pd.DataFrame()

    # Re-apply attrs metadata
    if not hasattr(raw_df, "attrs"):
        raw_df.attrs = {}
    raw_df.attrs["selected_sheet"] = target_sheet
    raw_df.attrs["sheet_names"] = sheet_names if 'sheet_names' in locals() else [name]
    raw_df.attrs["passed_country"] = country

    header_idx = None
    for r_idx in preferred_rows:
        if r_idx < len(raw_df):
            row_vals = [_safe_str(x) for x in raw_df.iloc[r_idx]]
            row_lower = [v.lower() for v in row_vals]
            expected  = [c.lower() for c in preferred_article_cols]
            if any(e in row_lower for e in expected) or any("article" in c or "pim" in c or "style" in c for c in row_lower):
                header_idx = r_idx
                break

    if header_idx is None:
        for r_idx in range(min(6, len(raw_df))):
            row_vals = [_safe_str(x) for x in raw_df.iloc[r_idx]]
            row_lower = [v.lower() for v in row_vals]
            expected  = [c.lower() for c in preferred_article_cols]
            if any(e in row_lower for e in expected) or any("article" in c or "pim" in c or "style" in c for c in row_lower):
                header_idx = r_idx
                break

    if header_idx is None:
        header_idx = preferred_rows[0] if preferred_rows[0] < len(raw_df) else 0

    header_row_vals = [_safe_str(x) for x in raw_df.iloc[header_idx]]
    
    usecols_indices = []
    for idx, c in enumerate(header_row_vals):
        c_lower = c.lower()
        if (any(x in c_lower for x in ["style", "article", "pim"]) or
            any(x in c_lower for x in ["launch"]) or
            any(mp in c_lower for mp in ["lazada", "shopee", "zalora", "tiktok"])):
            usecols_indices.append(idx)
            
    if 0 not in usecols_indices:
        usecols_indices.append(0)
    usecols_indices = sorted(list(set(usecols_indices)))
    
    try:
        if name.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(raw), header=None, skiprows=header_idx + 1, usecols=usecols_indices, dtype=str)
        else:
            df = xl.parse(target_sheet, header=None, skiprows=header_idx + 1, usecols=usecols_indices, dtype=str)
    except Exception:
        return pd.DataFrame()
        
    if df.empty:
        return pd.DataFrame()
        
    col_mapping = {}
    for idx in usecols_indices:
        col_mapping[idx] = header_row_vals[idx]
    df = df.rename(columns=col_mapping)
    df = df.loc[:, ~df.columns.duplicated()].copy()
    df = df.reset_index(drop=True)
    
    df.attrs = raw_df.attrs
    
    first_col = header_row_vals[0]
    df = df[df[first_col].apply(_safe_str) != first_col].copy()
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

    if "Article No" in df.columns:
        df = df[df["Article No"].apply(_safe_str) != ""].copy()
        df = df.reset_index(drop=True)

    # Build standardised Ecom_ columns
    mp_keywords = {
        "lazada":  "Ecom_Lazada",
        "shopee":  "Ecom_Shopee",
        "zalora":  "Ecom_Zalora",
        "tiktok":  "Ecom_TikTok",
    }
    for col in df.columns:
        if col == "Article No" or "launch" in col.lower():
            continue
        col_l = col.lower()
        for mp_key, ecom_name in mp_keywords.items():
            if mp_key in col_l and ecom_name not in df.columns:
                df[ecom_name] = df[col].apply(_safe_str)
                break

    # Keep all columns containing "launch", "Article No", and standard Ecom_ columns
    launch_cols = [c for c in df.columns if "launch" in c.lower()]
    ecom_cols = [c for c in df.columns if c.startswith("Ecom_")]
    keep_cols = ["Article No"] + launch_cols + ecom_cols
    keep_cols = [c for c in keep_cols if c in df.columns]
    return df[keep_cols].copy()


# ── Exclusion List ────────────────────────────────────────────────────────────

def _normalise_article_no(val):
    """
    Normalise Article No for matching across files.
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


def load_exclusion(file):
    """
    Load Exclusion list.

    Supports two layouts:
    1. Standard layout: a dedicated "Article No"/"Style#"/etc column
       plus a separate "Status"/"Exclusion Status" column.
    2. Combined layout (e.g. "Lazada Inactive", "Lazada Active",
       "Shopee Inactive", "<Channel> <Status>"): the column header
       itself encodes the status (Active/Inactive), and the column
       values are the Article Nos for that status.

    Article No is normalised for matching against zecom/content article numbers.
    """
    if file is None:
        return pd.DataFrame()
    df = _read_file(file)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)

    # ── Try standard layout first: explicit Article No + Status columns ──────
    art_col = None
    for c in ["Article No", "ArticleNo", "Article_No", "Article", "Style", "Style_No",
              "STYLE#", "Style#", "style#", "Style #", "STYLE #",
              "Article Number", "ALU_No", "ALU", "Aricle No", "Color No", "Color_No"]:
        if c in df.columns:
            art_col = c
            break
    if art_col is None:
        for c in df.columns:
            cl = c.lower()
            if cl in ("article no", "articleno", "article number",
                      "style#", "style #") or (
                "article" in cl and "status" not in cl
            ):
                art_col = c
                break

    status_col = None
    for c in ["Exclusion Status", "Status", "status", "AM Status",
              "AM Request", "Action"]:
        if c in df.columns:
            status_col = c
            break
    if status_col is None:
        for c in df.columns:
            if "status" in c.lower() and c != art_col:
                status_col = c
                break

    def _map_status(s):
        s = _safe_str(s).strip().lower()
        if s in ("active", "1", "yes", "y", "enable", "enabled"):
            return "Active"
        if s in ("inactive", "0", "no", "n", "disable", "disabled"):
            return "Inactive"
        return s.capitalize() if s else "Inactive"

    rows = []

    if art_col is not None and status_col is not None:
        # ── Standard layout ────────────────────────────────────────────────
        for _, r in df.iterrows():
            art = _normalise_article_no(r.get(art_col, ""))
            if art:
                rows.append({
                    "Article No": art,
                    "Exclusion Status": _map_status(r.get(status_col, "")),
                })
    else:
        # ── Combined layout: column header encodes the status ────────────────
        # e.g. "Lazada Inactive", "Shopee Active", "Inactive", "Active"
        for col in df.columns:
            col_l = col.lower().strip()
            inferred_status = None
            if "inactive" in col_l:
                inferred_status = "Inactive"
            elif "active" in col_l:
                inferred_status = "Active"

            if inferred_status is None:
                continue

            for val in df[col]:
                art = _normalise_article_no(val)
                if art:
                    rows.append({
                        "Article No": art,
                        "Exclusion Status": inferred_status,
                    })

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    out = out[out["Article No"] != ""].reset_index(drop=True)
    # If duplicates, keep the last entry (most recent override)
    out = out.drop_duplicates(subset=["Article No"], keep="last").reset_index(drop=True)
    return out


# ── ALL File ──────────────────────────────────────────────────────────────────

def load_all_file(file, country):
    if file is None:
        return pd.DataFrame()
        
    file.seek(0)
    if file.name.lower().endswith(".csv"):
        header_df = pd.read_csv(file, nrows=1)
    else:
        try:
            import python_calamine
            header_df = pd.read_excel(file, nrows=1, engine="calamine")
        except ImportError:
            header_df = pd.read_excel(file, nrows=1)
    file.seek(0)
    
    actual_cols = list(header_df.columns)
    
    # 1. SKU column
    sku_col = None
    for c in ["sellerSKU", "SellerSKU", "SKU", "Seller SKU"]:
        if c in actual_cols:
            sku_col = c
            break
            
    # 2. Stock and Reserved Columns
    stock_col_map = {
        "SG": ("MyStock-YCH-SG quantity",  "MyStock-YCH-SG reservedQuantity"),
        "MY": ("MyStock-YCH-MY quantity",  "MyStock-YCH-MY reservedQuantity"),
        "PH": ("MyStock-PH quantity",      "MyStock-PH reservedQuantity"),
    }
    target_stock, target_reserved = stock_col_map.get(country, ("", ""))
    
    stock_col = None
    if target_stock in actual_cols:
        stock_col = target_stock
    else:
        for c in actual_cols:
            if "quantity" in c.lower() and country.lower() in c.lower():
                stock_col = c
                break
                
    reserved_col = None
    if target_reserved in actual_cols:
        reserved_col = target_reserved
    else:
        for c in actual_cols:
            if "reserved" in c.lower():
                reserved_col = c
                break
                
    usecols = []
    if sku_col: usecols.append(sku_col)
    if stock_col: usecols.append(stock_col)
    if reserved_col: usecols.append(reserved_col)
    
    df = _read_file(file, usecols=usecols if usecols else None)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
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
    import numpy as np
    s_sku = df["SKU"].fillna("").astype(str).str.strip()
    float_mask = s_sku.str.match(r'^\d+\.0$', na=False)
    df["SKU"] = np.where(float_mask, s_sku.str[:-2], s_sku)
    for num_col in ["TC Stock", "Reserved Stock"]:
        if num_col in df.columns:
            df[num_col] = pd.to_numeric(
                df[num_col].fillna("").astype(str).str.strip(), errors="coerce"
            ).fillna(0)
        else:
            df[num_col] = 0.0
    df = df[df["SKU"] != ""].copy()
    # Slice only needed columns to keep memory low
    keep_cols = [c for c in ["SKU", "TC Stock", "Reserved Stock"] if c in df.columns]
    return df[keep_cols].copy()


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

    # MP Status logic:
    # The status file contains the list of active Product IDs (one row per PID).
    # If a Product ID from the stock file appears in the status file -> Active
    # If a Product ID is NOT in the status file -> Inactive
    # If Product ID is blank in stock file -> Inactive
    # This is more reliable than merging since Product IDs may differ across files.

    if not shopee_stock.empty:
        shopee = shopee_stock.copy()

        # Build set of active Product IDs from status file
        active_pids = set()
        if not shopee_status.empty and "Product ID" in shopee_status.columns:
            active_pids = set(
                shopee_status["Product ID"]
                .apply(_safe_str)
                .str.strip()
                .replace("", pd.NA)
                .dropna()
                .unique()
            )

        if "Product ID" in shopee.columns:
            if active_pids and len(active_pids & set(shopee["Product ID"].apply(_safe_str).str.strip())) > 0:
                # Status file PIDs overlap with stock file PIDs
                # Use status file as authoritative Active PID list
                shopee["MP Status"] = shopee["Product ID"].apply(
                    lambda x: "Active" if _safe_str(x).strip() in active_pids else "Inactive"
                )
            else:
                # No overlap between status file PIDs and stock file PIDs
                # (different shops, or no status file uploaded)
                # Rule: Active if this row's own Product ID is non-blank, else Inactive
                shopee["MP Status"] = shopee["Product ID"].apply(
                    lambda x: "Active" if _safe_str(x).strip() not in ("", "nan", "none") else "Inactive"
                )
        else:
            shopee["MP Status"] = "Inactive"
    else:
        shopee = pd.DataFrame()
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
