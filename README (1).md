# Status Validation Analyzer

A Streamlit application for validating marketplace product statuses across
**Lazada**, **Shopee**, **Zalora**, and **TikTok** for countries **SG**, **MY**, and **PH**.

---

## Project Structure

```
status_validator/
├── app.py                    # Main Streamlit entry point
├── requirements.txt
└── utils/
    ├── __init__.py
    ├── file_loaders.py       # All marketplace & reference file parsers
    ├── validators.py         # SKU-level & PID-level validation logic
    ├── report_generator.py   # Status report builder
    └── styles.py             # Custom CSS injection
```

---

## Setup & Run

```bash
# 1. Clone the repo
git clone https://github.com/<your-org>/status-validator.git
cd status-validator

# 2. Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Launch the app
streamlit run app.py
```

The app opens at `http://localhost:8501`.

---

## File Upload Guide

### Country selection
Pick **SG**, **MY**, or **PH** from the sidebar dropdown first.
TikTok uploads only appear when **MY** is selected.

### Marketplace files

| Marketplace | File(s) needed | Notes |
|---|---|---|
| Lazada SG/MY/PH | Single file | Row 1 = header, rows 2–4 skipped |
| Shopee SG/MY/PH | Stock file + Status file | Supports ZIP; rows 1–2 ignored, row 3 = header, rows 4–6 ignored; only 13-digit SKUs kept |
| Zalora SG/MY/PH | Stock file + Status file | Standard header on row 1 |
| TikTok MY | Stock file + Active status file + Inactive status file | MY only |

### Reference files

| File | Key columns used |
|---|---|
| Content File | EAN → SKU, Color_No → Article No |
| TC Inventory | Custom SKU, Item status, Max Quantity |
| zEcom File | PIM Article#, Launch Dates, Lazada/Shopee/Zalora/TikTok e-com columns |
| ALL File | sellerSKU, MyStock-YCH-SG/MY quantity, MyStock-PH quantity, reserved columns |

---

## Validation Logic Summary

### SKU Level (Lazada + Zalora)
1. Look up **Ecom Status** via SKU → Article No → zEcom.
2. Derive **Final Status**: Inactive if Ecom Inactive; Inactive if TC Stock = 0; else Active.
3. **Final Check**: MP Status = TC Status = Final Status → True / False.
4. **Stock Check**: MP Stock = TC Stock → True / False.
5. Generate **Action** and **Max Action** recommendations.
6. Flag **Push 0 Stock** if TC Stock ≤ 0 but MP Stock > 0.
7. Buffer stock −1 applied for **Lazada PH**.

### PID Level (Shopee + TikTok)
1. Group SKUs by Product ID.
2. Detect **Dual Status** (1 = all same ecom, 2 = mixed Active/Inactive).
3. Consolidate TC Stock by PID.
4. Derive Final Status using dual-status rules.
5. Apply same Final Check / Stock Check / Action / Max Action logic.
6. Buffer stock −1 applied for **TikTok MY**.

---

## Output

Three Excel sheets are exported:

- **Status Report** – full overview across all marketplaces
- **SKU Validation** – Lazada + Zalora row-level results with actions
- **PID Validation** – Shopee + TikTok PID-level results with actions

Row colours in the UI:
- 🟢 Dark green = Final Check True + Stock Check True (All Good)
- 🟡 Dark amber = Final Check True, Stock Check False
- 🔴 Dark red   = Final Check False (action required)

---

## Deploying to Streamlit Cloud

1. Push this repository to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**.
3. Select your repo, branch `main`, and set **Main file path** to `app.py`.
4. Click **Deploy**.

No secrets or environment variables are required.
