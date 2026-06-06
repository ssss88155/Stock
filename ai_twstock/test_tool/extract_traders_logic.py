import json
import os

def extract_traders():
    input_path = r'C:\jupyter_notebook\ai_twstock\stock_data_micro.json'
    output_dir = r'C:\jupyter_notebook\ai_twstock\data'
    os.makedirs(output_dir, exist_ok=True)
    
    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found")
        return

    print("Loading micro data...")
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    traders_map = {} # { "id": "name" }
    
    print("Extracting traders from trading_daily_report...")
    for sid, sid_data in data.items():
        report = sid_data.get('trading_daily_report', {})
        for date_str, day_data in report.items():
            # 遍歷買方與賣方
            for entry in day_data.get('top_buyers', []) + day_data.get('top_sellers', []):
                trader_raw = entry.get('trader', '') # "名稱/代號"
                if '/' in trader_raw:
                    name, tid = trader_raw.split('/')
                    if tid and tid not in traders_map:
                        traders_map[tid] = name
    
    # 建立空的 micro_feature 結構
    feature_list = []
    for tid in sorted(traders_map.keys()):
        feature_list.append({
            "id": tid,
            "name": traders_map[tid],
            "特性": "",
            "穩重指數": 0
        })
    
    print(f"Total unique traders found: {len(feature_list)}")
    
    # 儲存初版 (空的)
    first_path = os.path.join(output_dir, 'micro_feature_first.json')
    with open(first_path, 'w', encoding='utf-8') as f:
        json.dump(feature_list, f, ensure_ascii=False, indent=2)
    print(f"Saved {first_path}")
    
    # 分成 20 份
    chunk_size = (len(feature_list) + 19) // 20 # 向上取整
    for i in range(20):
        start = i * chunk_size
        end = start + chunk_size
        chunk = feature_list[start:end]
        if not chunk: break
        
        chunk_path = os.path.join(output_dir, f'micro_feature_{i+1:02d}.json')
        with open(chunk_path, 'w', encoding='utf-8') as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)
        print(f"Saved {chunk_path} (count: {len(chunk)})")

if __name__ == "__main__":
    extract_traders()
