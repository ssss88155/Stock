import json
import os
import sys

# 加入上層目錄以引用邏輯
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest_momentum_day_trading as btest

def verify_logic():
    # 1. 載入價格資料 (1.5GB 那個)
    PRICE_DATA_PATH = r"C:\jupyter_notebook\ai_twstock\stock_data.json"
    # 2. 載入分點資料 (剛抽取的 debug 版)
    BROKER_DATA_PATH = r"C:\jupyter_notebook\ai_twstock\stock_data_debug.json"
    # 3. 載入微特徵
    MICRO_FEATURE = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
    
    print("載入資料中 (這可能需要一點時間)...")
    with open(PRICE_DATA_PATH, 'r', encoding='utf-8') as f:
        price_data_all = json.load(f)
    with open(BROKER_DATA_PATH, 'r', encoding='utf-8') as f:
        broker_data_all = json.load(f)
    with open(MICRO_FEATURE, 'r', encoding='utf-8') as f:
        features = {item['id']: item for item in json.load(f)}

    target_sids = ['2330', '6187']
    
    for sid in target_sids:
        print(f"\n{'='*80}")
        print(f"分析標的: {sid}")
        print(f"{'日期':<12} | {'淨分':>8} | {'買賣指數':>8} | {'集中度':>8} | {'訊號類型':<12} | {'原因'}")
        print("-" * 80)
        
        # 整合資料：以分點資料的日期為主
        report_dates = sorted(list(broker_data_all.get(sid, {}).get('trading_daily_report', {}).keys()))
        
        # 建立一個臨時的 data dict 供 function 使用
        temp_data = {
            sid: {
                'price': price_data_all.get(sid, {}).get('price', {}),
                'trading_daily_report': broker_data_all.get(sid, {}).get('trading_daily_report', {})
            }
        }
        
        for date in report_dates:
            if date < '2026-04-01': continue
            
            # 計算訊號
            dt_sig = btest.calculate_day_trading_signal(sid, date, temp_data, features)
            conc = btest.calculate_broker_concentration(sid, date, temp_data)
            
            # 擷取數值 (從 debug print 邏輯中模擬)
            sig_type = dt_sig['type'] if dt_sig['type'] else "None"
            
            # 只有當有訊號或集中度高時才印出，縮短輸出
            if sig_type != "None" or conc > 0.1:
                print(f"{date:<12} | {dt_sig.get('strength', 0):>8.1f} | {sig_type:<8} | {conc:>8.2%} | {dt_sig['reason']}")

if __name__ == "__main__":
    verify_logic()
