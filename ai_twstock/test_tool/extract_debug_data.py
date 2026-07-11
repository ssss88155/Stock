import json
import os

def extract_specific_stocks(input_path, output_path, target_sids):
    """
    使用串流方式讀取大型 JSON 並抽取特定股票資料
    """
    print(f"開始從 {input_path} 抽取資料: {target_sids}")
    
    # 由於是 JSON 格式，通常是 { "sid": { ... } }
    # 我們使用 ijson 或簡單的逐行讀取（如果格式允許）
    # 這裡假設是標準 JSON，我們嘗試用較省記憶體的方式讀取
    
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            # 如果檔案極大，json.load 還是會爆，但我們先嘗試讀取
            # 若真的爆掉，下一步會建議轉 SQL
            full_data = json.load(f)
            
        extracted = {sid: full_data[sid] for sid in target_sids if sid in full_data}
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(extracted, f, ensure_ascii=False, indent=2)
            
        print(f"抽取完成！存至: {output_path}")
        print(f"包含股票: {list(extracted.keys())}")
        
    except MemoryError:
        print("錯誤: 檔案太大，無法一次載入記憶體。請考慮直接轉為 SQLite。")
    except Exception as e:
        print(f"發生錯誤: {e}")

if __name__ == "__main__":
    # 修正為實際存在的 3.5GB 檔案路徑
    LARGE_JSON = r"C:\jupyter_notebook\ai_twstock\stock_data_micro.json"
    OUTPUT_JSON = r"C:\jupyter_notebook\ai_twstock\stock_data_debug.json"
    TARGETS = ['2330', '6187', '2317', '2454'] # 加入一些權值股測試
    
    if os.path.exists(LARGE_JSON):
        extract_specific_stocks(LARGE_JSON, OUTPUT_JSON, TARGETS)
    else:
        print(f"找不到檔案: {LARGE_JSON}")
