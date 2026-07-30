import os
import time
import pandas as pd
from datetime import datetime

# Import loaders and validators from current directory
from file_loaders import load_all_files
from validators import run_sku_validation, run_pid_validation, save_df_to_excel_fast

class LocalFileWrapper:
    def __init__(self, filepath):
        self.filepath = filepath
        self.name = os.path.basename(filepath)
        self.file_obj = open(filepath, 'rb')
        
    def read(self, size=-1):
        return self.file_obj.read(size)
        
    def seek(self, offset):
        self.file_obj.seek(offset)
        
    def close(self):
        self.file_obj.close()

def run_local_validation():
    input_dir = r"C:\Users\Yesuraja\.gemini\antigravity\scratch\Shopee PH Input files"
    output_dir = r"C:\Users\Yesuraja\.gemini\antigravity\scratch"
    country = "PH"
    
    print("\n" + "="*60)
    print("--- Starting PUMA Seller Inventory Validation (Local CLI) ---")
    print("="*60)
    start_time = time.time()
    
    # Map input files in the directory
    files = {
        "shopee_stock_file": os.path.join(input_dir, "Shopee Stock.zip"),
        "shopee_status_file": os.path.join(input_dir, "Shopee Status.zip"),
        "content_file": os.path.join(input_dir, "Content file 11.06.2026.xlsx"),
        "zecom_file": os.path.join(input_dir, "PH_MP_eCOM Tracking File_6.6_ updated 02June2026_final.xlsx"),
        "exclusion_file": os.path.join(input_dir, "Shopee PH Exclusion.xlsx"),
        "all_file": os.path.join(input_dir, "ALL (30).csv"),
        "tc_inv_file": os.path.join(input_dir, "shopee-PH (5).csv")
    }
    
    # Open all file wrappers
    wrappers = {}
    for key, path in files.items():
        if os.path.exists(path):
            print(f"[FOUND] {key}: {os.path.basename(path)} ({round(os.path.getsize(path)/(1024*1024), 2)} MB)")
            wrappers[key] = LocalFileWrapper(path)
        else:
            print(f"[MISSING] {key} not found at {path}")
            wrappers[key] = None
            
    try:
        # 1. Load data
        print("\nLoading files into memory...")
        load_start = time.time()
        data = load_all_files(
            country=country,
            lazada_file=None,
            shopee_stock_file=wrappers["shopee_stock_file"],
            shopee_status_file=wrappers["shopee_status_file"],
            zalora_stock_file=None,
            zalora_status_file=None,
            tiktok_active_file=None,
            tiktok_inactive_file=None,
            content_file=wrappers["content_file"],
            tc_inv_file=wrappers["tc_inv_file"],
            zecom_file=wrappers["zecom_file"],
            all_file=wrappers["all_file"],
            exclusion_file=wrappers["exclusion_file"],
        )
        print(f"-> Loading and parsing completed in {time.time() - load_start:.2f} seconds.")
        
        # 2. Run validations
        print("\nRunning matching validations...")
        val_start = time.time()
        sk = run_sku_validation(data, country)
        pi = run_pid_validation(data, country)
        print(f"-> Validation matching logic completed in {time.time() - val_start:.2f} seconds.")
        
        # 3. Save report
        print("\nWriting final validation Excel report...")
        save_start = time.time()
        today = datetime.today().strftime("%Y-%m-%d")
        fname = f"Shopee_PH_Status_Validation_Report_{today}_Local.xlsx"
        fpath = os.path.join(output_dir, fname)
        
        sheets = {}
        if not sk.empty:
            sheets["SKU Validation"] = sk
            print(f"   * Wrote {len(sk)} rows to 'SKU Validation' sheet.")
        if not pi.empty:
            sheets["PID Validation"] = pi
            print(f"   * Wrote {len(pi)} rows to 'PID Validation' sheet.")
        save_df_to_excel_fast(sheets, fpath)
                
        print(f"-> Excel report saved to: {fpath}")
        print(f"-> Saving completed in {time.time() - save_start:.2f} seconds.")
        
        print("\n" + "="*60)
        print("--- Validation Complete! ---")
        print(f"Total Execution Time: {time.time() - start_time:.2f} seconds.")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n[ERROR] An error occurred during validation: {str(e)}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Close all file wrappers
        for w in wrappers.values():
            if w is not None:
                w.close()

if __name__ == "__main__":
    run_local_validation()
