import os
import json
import glob
from datetime import datetime

def get_script_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def merge_price_data():
    base_dir = get_script_dir()
    src_dir = os.path.join(base_dir, 'data_independent')
    dst_dir = os.path.join(base_dir, 'data_independent_price')
    
    if not os.path.exists(src_dir):
        print(f"[Error] Source directory not found: {src_dir}")
        return

    os.makedirs(dst_dir, exist_ok=True)
    
    src_files = glob.glob(os.path.join(src_dir, "*.json"))
    print(f"Found {len(src_files)} files in {src_dir}")
    
    count = 0
    for src_path in src_files:
        filename = os.path.basename(src_path)
        stock_id = filename.replace(".json", "")
        dst_path = os.path.join(dst_dir, filename)
        
        try:
            # 讀取來源資料
            with open(src_path, 'r', encoding='utf-8') as f:
                src_raw = json.load(f)
                src_data = src_raw.get(stock_id, src_raw)
            
            # 讀取目標資料 (如果存在)
            dst_data = {}
            if os.path.exists(dst_path):
                with open(dst_path, 'r', encoding='utf-8') as f:
                    dst_raw = json.load(f)
                    dst_data = dst_raw.get(stock_id, dst_raw)
            
            # 合併資料類別
            changed = False
            for category in ['price', 'institutional', 'shareholding']:
                if category in src_data and src_data[category]:
                    if category not in dst_data:
                        dst_data[category] = {}
                    
                    # 檢查是否有新資料要合併
                    before_count = len(dst_data[category])
                    dst_data[category].update(src_data[category])
                    
                    # 排序
                    dst_data[category] = dict(sorted(dst_data[category].items()))
                    
                    if len(dst_data[category]) > before_count:
                        changed = True
            
            if changed or not os.path.exists(dst_path):
                # 更新最後更新時間
                dst_data['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # 寫入目標檔案
                temp_path = dst_path + ".tmp"
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump({stock_id: dst_data}, f, ensure_ascii=False, indent=4)
                
                if os.path.exists(dst_path):
                    os.remove(dst_path)
                os.rename(temp_path, dst_path)
                count += 1
                print(f"  [{count}] Merged {stock_id}")
                
        except Exception as e:
            print(f"  [Error] Failed to process {stock_id}: {e}")

    print(f"\n[FINISH] Successfully merged {count} files to {dst_dir}")

if __name__ == "__main__":
    merge_price_data()
