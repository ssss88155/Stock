import json
import os
import pandas as pd
from datetime import datetime

def analyze_broker_sync(stock_data_path, micro_feature_path, output_dir):
    """
    計算分點買賣同步率與隔日沖潛在賣壓
    """
    print(f"讀取微特徵資料: {micro_feature_path}")
    with open(micro_feature_path, 'r', encoding='utf-8') as f:
        micro_features = {item['id']: item for item in json.load(f)}

    # 這裡假設使用較小的 stock_data.json 進行示範，若是 1.2GB 檔案建議用 chunk
    print(f"讀取股票資料: {stock_data_path}")
    with open(stock_data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    sync_results = []
    
    # 取得最後一個交易日 (或可指定日期)
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    if not all_dates:
        return
    target_date = all_dates[-1]
    
    for sid, info in data.items():
        # 取得當日分點明細 (格式 B/C)
        report = info.get('trading_daily_report', {}).get(target_date, {})
        buyers = report.get('top_buyers', [])
        sellers = report.get('top_sellers', [])
        
        combined_traders = {}
        for t in buyers + sellers:
            trader_str = t.get('trader', '')
            if '/' not in trader_str: continue
            bid = trader_str.split('/')[-1]
            
            if bid not in combined_traders:
                combined_traders[bid] = {'buy': 0, 'sell': 0}
            
            # 根據欄位加總
            if 'buy_qty' in t: # 假設格式中有買賣量
                combined_traders[bid]['buy'] += t.get('buy_qty', 0)
                combined_traders[bid]['sell'] += t.get('sell_qty', 0)
            else:
                net = t.get('net', 0)
                if net > 0: combined_traders[bid]['buy'] += net
                else: combined_traders[bid]['sell'] += abs(net)

        for bid, volumes in combined_traders.items():
            total_vol = volumes['buy'] + volumes['sell']
            if total_vol == 0: continue
            
            sync_rate = abs(volumes['buy'] - volumes['sell']) / total_vol
            stability = micro_features.get(bid, {}).get('穩重指數', 0)
            
            # 隔日沖潛在賣壓判定
            is_potential_sell_pressure = (stability < 0 and sync_rate > 0.9 and (volumes['buy'] - volumes['sell']) > 0)
            
            sync_results.append({
                'date': target_date,
                'stock_id': sid,
                'broker_id': bid,
                'buy_vol': volumes['buy'],
                'sell_vol': volumes['sell'],
                'sync_rate': round(sync_rate, 3),
                'stability': stability,
                'is_potential_sell_pressure': is_potential_sell_pressure
            })

    # 存檔
    df = pd.DataFrame(sync_results)
    ts = datetime.now().strftime("%Y%m%d")
    output_path = os.path.join(output_dir, f"broker_sync_analysis_{ts}.csv")
    df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"分析完成，結果存至: {output_path}")
    return output_path

if __name__ == "__main__":
    STOCK_DATA = r"C:\jupyter_notebook\ai_twstock\stock_data.json"
    MICRO_FEATURE = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
    OUTPUT_DIR = r"C:\jupyter_notebook\ai_twstock\data"
    
    analyze_broker_sync(STOCK_DATA, MICRO_FEATURE, OUTPUT_DIR)
