import json
import os
import sys

# 加入上層目錄以引用 backtest 邏輯
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest_momentum_day_trading as btest

def debug_stock_signals(stock_ids, start_date):
    # 改用剛抽取的 debug 資料
    STOCK_DATA = r"C:\jupyter_notebook\ai_twstock\stock_data_debug.json"
    MICRO_FEATURE = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
    
    print(f"載入資料中...")
    with open(STOCK_DATA, 'r', encoding='utf-8') as f:
        data = json.load(f)
    with open(MICRO_FEATURE, 'r', encoding='utf-8') as f:
        features = {item['id']: item for item in json.load(f)}
    
    for sid in stock_ids:
        print(f"\n{'='*60}")
        print(f"分析標的: {sid}")
        print(f"{'日期':<12} | {'淨分':>8} | {'買賣指數':>8} | {'集中度':>8} | {'訊號'}")
        print("-" * 60)
        
        stock_info = data.get(sid, {})
        all_dates = sorted([d for d in stock_info.get('price', {}).keys() if d >= start_date])
        
        for date in all_dates:
            # 1. 計算分點訊號
            dt_sig = btest.calculate_day_trading_signal(sid, date, data, features)
            
            # 2. 計算集中度
            conc = btest.calculate_broker_concentration(sid, date, data)
            
            # 3. 檢查量價配合 (異常買超)
            abnormal = btest.check_abnormal_broker_buy(sid, date, data)
            
            # 解析 dt_sig 中的數值 (從 debug print 中擷取或重新計算)
            # 這裡為了 debug 直接印出結果
            sig_type = dt_sig['type'] if dt_sig['type'] else "None"
            
            print(f"{date:<12} | {dt_sig.get('strength', 0):>8.1f} | {sig_type:<8} | {conc:>8.2%} | {'異常買超' if abnormal else ''}")

if __name__ == "__main__":
    debug_stock_signals(['2330', '6187'], '2026-04-01')
