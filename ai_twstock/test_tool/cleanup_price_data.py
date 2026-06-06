import os
import json
import glob

def get_script_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def cleanup_price_files():
    base_dir = get_script_dir()
    target_dir = os.path.join(base_dir, 'data_independent_price')
    
    if not os.path.exists(target_dir):
        print(f"[Error] Target directory not found: {target_dir}")
        return

    files = glob.glob(os.path.join(target_dir, "*.json"))
    print(f"Found {len(files)} files in {target_dir}")
    
    count = 0
    for path in files:
        filename = os.path.basename(path)
        stock_id = filename.replace(".json", "")
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                data = raw.get(stock_id, raw)
            
            # 移除 trading_daily_report
            if 'trading_daily_report' in data:
                del data['trading_daily_report']
                
                # 寫回檔案
                temp_path = path + ".tmp"
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump({stock_id: data}, f, ensure_ascii=False, indent=4)
                
                if os.path.exists(path):
                    os.remove(path)
                os.rename(temp_path, path)
                count += 1
                if count % 100 == 0:
                    print(f"  Processed {count} files...")
                
        except Exception as e:
            print(f"  [Error] Failed to process {stock_id}: {e}")

    print(f"\n[FINISH] Successfully cleaned up 'trading_daily_report' from {count} files in {target_dir}")

if __name__ == "__main__":
    cleanup_price_files()
