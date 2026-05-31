import os
import json
import pandas as pd
import argparse
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import threading
import sys

# 將 lib 目錄加入 Python 路徑
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
from common_lib import load_independent_stock_data, get_script_dir, load_independent_stock_data_custom

shutdown_event = threading.Event()

def adaptive_sleep(call_start, target_interval, print_prefix=""):
    elapsed = time.time() - call_start
    sleep_needed = max(0, target_interval - elapsed)
    print(f"   {print_prefix}Cost: {elapsed:.2f}s, Sleep: {sleep_needed:.2f}s (Target: {target_interval:.2f}s)")
    if sleep_needed > 0:
        time.sleep(sleep_needed)
    return elapsed

def get_target_interval(api):
    """
    根據 API 限制計算目標平均間隔時間 (3600 / limit)
    """
    try:
        limit = api.api_usage_limit
        if limit <= 0: return 2.0
        return 3600.0 / limit
    except:
        return 2.0

def load_config():
    config_path = os.path.join(get_script_dir(__file__), 'config', 'find_mind_config.json')
    if not os.path.exists(config_path):
        old_path = os.path.join(get_script_dir(__file__), 'config.json')
        if os.path.exists(old_path): config_path = old_path
    with open(config_path, 'r') as f: return json.load(f)

def save_json_minimal(path, data):
    """超精簡儲存邏輯"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing_data = {}
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f: existing_data = json.load(f)
        except: pass
    
    for category, dates_data in data.items():
        if category not in existing_data:
            existing_data[category] = {}
        if isinstance(dates_data, dict):
            existing_data[category].update(dates_data)
            existing_data[category] = dict(sorted(existing_data[category].items()))
        else:
            existing_data[category] = dates_data

    temp_path = path + ".tmp"
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=4)
        if os.path.exists(path): os.remove(path)
        os.rename(temp_path, path)
        return True
    except: return False

def get_stock_trading_report_cache(api, stock_id, date_str):
    try:
        df = api.taiwan_stock_trading_daily_report(stock_id=stock_id, date=date_str)
        if df is not None and not df.empty:
            df['buy_v'] = df['buy'] * df['price']
            df['sell_v'] = df['sell'] * df['price']
            df['trader'] = df['securities_trader'] + "/" + df['securities_trader_id']
            summary = df.groupby('trader').agg({'buy':'sum','sell':'sum','buy_v':'sum','sell_v':'sum'}).reset_index()
            summary['net'] = summary['buy'] - summary['sell']
            top_b = summary.sort_values('net', ascending=False).head(15)
            top_b = top_b[top_b['net'] > 0].copy()
            top_b['avg_p'] = (top_b['buy_v'] / top_b['buy']).round(1) if not top_b.empty else 0
            top_s = summary.sort_values('net', ascending=True).head(15)
            top_s = top_s[top_s['net'] < 0].copy()
            top_s['net_s'] = abs(top_s['net'])
            top_s['avg_p'] = (top_s['sell_v'] / top_s['sell']).round(1) if not top_s.empty else 0
            return {
                "top_buyers": top_b[['trader', 'net', 'avg_p']].to_dict(orient='records'),
                "top_sellers": top_s[['trader', 'net_s', 'avg_p']].to_dict(orient='records')
            }
    except: pass
    return None

def fetch_stock_data(api, stock_id, start_date, end_date):
    try:
        print(f"      -> downloading daily..", end=" ")
        sys.stdout.flush()
        df_p = api.taiwan_stock_daily(stock_id=stock_id, start_date=start_date, end_date=end_date)
        print(f"done,", end=" ")
        print(f"institutional..", end=" ")
        sys.stdout.flush()
        df_i = api.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start_date, end_date=end_date)
        print(f"done,", end=" ")
        print(f"shareholding..", end=" ")
        sys.stdout.flush()
        df_h = api.taiwan_stock_shareholding(stock_id=stock_id, start_date=start_date, end_date=end_date)
        print(f"done")
        p = {r.pop('date'): r for r in df_p.to_dict(orient='records')} if not df_p.empty else {}
        inst = {}
        if not df_i.empty:
            for r in df_i.to_dict(orient='records'):
                d, n = r.pop('date'), r.pop('name')
                if d not in inst: inst[d] = {}
                inst[d][n] = r
        hold = {}
        if not df_h.empty:
            if 'EquityHoldingClass' in df_h.columns: df_h = df_h[df_h['EquityHoldingClass'] == 'Total']
            hold = {r.pop('date'): r for r in df_h.to_dict(orient='records')}
        return {'price': p, 'institutional': inst, 'shareholding': hold}
    except: return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stock_id')
    args = parser.parse_args()
    config = load_config()
    apis = []
    for k in sorted(config.keys()):
        if k.startswith('find_mind') and config[k].get('token') and "HERE" not in config[k]['token']:
            api = DataLoader()
            api.login_by_token(config[k]['token'])
            level = 2 if api.api_usage_limit > 600 else 1
            print(f"Logged in: {k} (Level: {level}, Usage: {api.api_usage}/{api.api_usage_limit})")
            apis.append({'api': api, 'level': level, 'name': k})
    if not apis: return

    # 動態一週日期
    start_date_range = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    target_dates = pd.date_range(start=start_date_range, end=datetime.now(), freq='B').strftime('%Y-%m-%d').tolist()
    
    stocks_path = os.path.join(get_script_dir(__file__), 'taiwan_stocks.csv')
    stocks = [args.stock_id] if args.stock_id else (pd.read_csv(stocks_path).iloc[:,0].astype(str).tolist() if os.path.exists(stocks_path) else ['2330'])

    for i, sid in enumerate(stocks):
        if shutdown_event.is_set(): break
        acc = apis[i % len(apis)]
        target_interval = get_target_interval(acc['api'])
        
        # 1. 價格
        print(f"[{i+1}/{len(stocks)}] Get {sid} price, checking cache...", end=" ")
        sys.stdout.flush()
        data_p = load_independent_stock_data_custom(sid, get_script_dir(__file__), "data_independent_price")
        if target_dates[-1] not in data_p.get('price', {}):
            print(f"miss (need {target_dates[-1]}), fetching 3 datasets from 2025-05-01...")
            call_start = time.time()
            res = fetch_stock_data(acc['api'], sid, '2025-05-01', target_dates[-1])
            if res: save_json_minimal(os.path.join(get_script_dir(__file__), 'data_independent_price', f"{sid}.json"), {sid: res})
            adaptive_sleep(call_start, target_interval)
        else:
            print(f"cached")

        # 2. 微觀 (僅分點)
        if acc['level'] >= 2:
            micro_path = os.path.join(get_script_dir(__file__), 'data_independent_microstructure', f"{sid}.json")
            
            # 讀取現有資料以進行精確判斷
            existing_micro = {}
            if os.path.exists(micro_path):
                try:
                    with open(micro_path, 'r', encoding='utf-8') as f: existing_micro = json.load(f)
                except: pass
            
            stock_report_cache = {}
            for d_str in target_dates:
                if shutdown_event.is_set(): break
                
                # 精確判斷：此日期是否已在本地 JSON 中?
                if d_str in existing_micro.get('trading_daily_report', {}):
                    continue
                
                print(f"[{i+1}/{len(stocks)}] Get Micro {sid} -> {d_str} ")
                call_start = time.time()
                day_res = get_stock_trading_report_cache(acc['api'], sid, d_str)
                if day_res:
                    stock_report_cache[d_str] = day_res
                
                adaptive_sleep(call_start, target_interval, f"Usage: {acc['api'].api_usage}/{acc['api'].api_usage_limit}, ")
                
                if acc['api'].api_usage >= acc['api'].api_usage_limit - 5: break
            
            if stock_report_cache:
                save_json_minimal(micro_path, {'trading_daily_report': stock_report_cache})

if __name__ == "__main__":
    main()
