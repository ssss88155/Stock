import os
import json
import pandas as pd
import argparse
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import threading
import sys
import signal
from concurrent.futures import ThreadPoolExecutor, as_completed

# 將 lib 目錄加入 Python 路徑
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
from common_lib import load_independent_stock_data, get_script_dir, load_independent_stock_data_custom
from data.holidays_config import HOLIDAYS_DATA, get_all_holidays

# 全域控制變數
shutdown_event = threading.Event()
current_api_threads = 5 # 預設值，會被 args.threads 覆蓋，控制 API 併發
api_threads_lock = threading.Lock()
holiday_counter = {}
holiday_lock = threading.Lock()

def signal_handler(sig, frame):
    print("\n[INTERRUPT] 偵測到中斷訊號 (Ctrl+C)，正在安全結束並儲存已抓取資料...")
    shutdown_event.set()

# 註冊中斷訊號
signal.signal(signal.SIGINT, signal_handler)

def get_api_usage_safe(api):
    try:
        return api.api_usage, api.api_usage_limit
    except:
        return 0, 0

def check_usage_and_protection(api, name=""):
    while not shutdown_event.is_set():
        usage, limit = get_api_usage_safe(api)
        if limit <= 0: break
        ratio = usage / limit
        # 強制印出當前使用量
        print(f"\r      [Usage] {name}: {ratio:.1%} ({usage}/{limit})", end="")
        if ratio >= 0.96:
            print(f"\n[PROTECTION] {name} 流量達標 96%! Cooldown (60s)...")
            for _ in range(60):
                if shutdown_event.is_set(): break
                time.sleep(1)
        else:
            break
    return True

def save_json_robust(path, data):
    """穩健的儲存邏輯，修正微觀資料格式：不含 sid 根節點，最新日期在最上面"""
    if not data: return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    existing_data = {}
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except Exception as e:
            print(f"      [Warn] 讀取舊檔失敗 {os.path.basename(path)}: {e}")
    
    # 統一 micro 資料格式：不含 sid 根節點
    content = data
    for key, val in data.items():
        if key.isdigit() or (isinstance(key, str) and len(key) <= 6):
            content = val
            break
            
    if 'trading_daily_report' not in existing_data:
        existing_data['trading_daily_report'] = {}
        
    if 'trading_daily_report' in content:
        existing_data['trading_daily_report'].update(content['trading_daily_report'])
        
    if 'trading_daily_report' in existing_data:
        existing_data['trading_daily_report'] = dict(sorted(existing_data['trading_daily_report'].items(), reverse=True))

    temp_path = path + ".tmp"
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=4)
        if os.path.exists(path): os.remove(path)
        os.rename(temp_path, path)
        return True
    except Exception as e:
        print(f"      [Error] 儲存檔案失敗 {path}: {e}")
        if os.path.exists(temp_path): os.remove(temp_path)
        return False

def save_price_data(stock_id, data):
    """儲存價格、法人、持股資料到 data_independent 目錄"""
    target_dir = os.path.join(get_script_dir(__file__), 'data_independent_price')
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, f"{stock_id}.json")
    
    existing_data = {}
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                existing_data = raw.get(stock_id, raw)
        except: pass

    for category in ['price', 'institutional', 'shareholding']:
        if category in data and data[category]:
            if category not in existing_data: existing_data[category] = {}
            existing_data[category].update(data[category])
            existing_data[category] = dict(sorted(existing_data[category].items()))
    
    existing_data['last_updated'] = data.get('last_updated', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    temp_path = path + ".tmp"
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump({stock_id: existing_data}, f, ensure_ascii=False, indent=4)
        if os.path.exists(path): os.remove(path)
        os.rename(temp_path, path)
        print(f"      -> [{stock_id}] 價格資料儲存成功。")
    except Exception as e:
        print(f"      [Error] [{stock_id}] 價格資料儲存失敗: {e}")

def fetch_price_institutional_data(api, stock_id, start_date, end_date):
    if shutdown_event.is_set(): return None
    try:
        df_price = api.taiwan_stock_daily(stock_id=stock_id, start_date=start_date, end_date=end_date)
        df_inst = api.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start_date, end_date=end_date)
        df_hold = api.taiwan_stock_shareholding(stock_id=stock_id, start_date=start_date, end_date=end_date)
        
        price_dict = {}
        if df_price is not None and not df_price.empty:
            for record in df_price.to_dict(orient='records'):
                d = record.pop('date')
                record.pop('stock_id', None)
                price_dict[d] = record
        
        inst_dict = {}
        if df_inst is not None and not df_inst.empty:
            for record in df_inst.to_dict(orient='records'):
                d = record.pop('date')
                name = record.pop('name')
                record.pop('stock_id', None)
                if d not in inst_dict: inst_dict[d] = {}
                inst_dict[d][name] = record
                
        hold_dict = {}
        if df_hold is not None and not df_hold.empty:
            if 'EquityHoldingClass' in df_hold.columns:
                df_hold_total = df_hold[df_hold['EquityHoldingClass'] == 'Total']
                if not df_hold_total.empty: df_hold = df_hold_total
            for record in df_hold.to_dict(orient='records'):
                d = record.pop('date')
                record.pop('stock_id', None)
                record.pop('InternationalCode', None)
                record.pop('EquityHoldingClass', None)
                hold_dict[d] = record

        return {
            'price': price_dict,
            'institutional': inst_dict,
            'shareholding': hold_dict,
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    except: return None

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

def process_micro_day(api, sid, d_str):
    if shutdown_event.is_set(): return d_str, None
    res = get_stock_trading_report_cache(api, sid, d_str)
    return d_str, res

def update_holidays_file(h_path, new_dates):
    if not new_dates: return
    today_str = datetime.now().strftime('%Y-%m-%d')
    valid_new_dates = [d for d in new_dates if d != today_str]
    if not valid_new_dates: return

    global holiday_counter
    config_py_path = os.path.join(os.path.dirname(h_path), "holidays_config.py")
    
    with holiday_lock:
        changed = False
        for d in valid_new_dates:
            holiday_counter[d] = holiday_counter.get(d, 0) + 1
            if holiday_counter[d] >= 300:
                year_key = f"HOLIDAY_{d.split('-')[0]}"
                if year_key not in HOLIDAYS_DATA:
                    HOLIDAYS_DATA[year_key] = []
                if d not in HOLIDAYS_DATA[year_key]:
                    HOLIDAYS_DATA[year_key].append(d)
                    HOLIDAYS_DATA[year_key].sort()
                    changed = True
                holiday_counter.pop(d)

        if changed:
            try:
                content = "# 台灣股市國定假日定義\nHOLIDAYS_DATA = " + json.dumps(HOLIDAYS_DATA, indent=2) + "\n\n"
                content += "def get_all_holidays():\n    all_dates = []\n    for year_list in HOLIDAYS_DATA.values():\n        all_dates.extend(year_list)\n    return sorted(list(set(all_dates)))\n"
                with open(config_py_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"\n      -> [HOLIDAY] 已更新 holidays_config.py，新增假日資料。")
            except Exception as e:
                print(f"\n      [Error] 寫入 holidays_config.py 失敗: {e}")

def process_phase_price(acc, sid, start_date, end_date, last_target_date):
    if shutdown_event.is_set(): return
    
    # 如果連目標日期都沒有（例如連假期間），直接跳過
    if not last_target_date:
        return "SKIP"

    # 超前檢查：打開檔案確認是否有最新日期的資料
    path = os.path.join(get_script_dir(__file__), 'data_independent_price', f"{sid}.json")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                data = raw.get(sid, raw)
                price_entries = data.get('price', {})
                # 嚴格比對：目標日期是否已在檔案中
                if last_target_date in price_entries:
                    inst_entries = data.get('institutional', {})
                    if last_target_date in inst_entries:
                        return "SKIP"
        except: pass

    check_usage_and_protection(acc['api'], acc['name'])
    p_data = fetch_price_institutional_data(acc['api'], sid, start_date, end_date)
    if p_data:
        # 檢查抓到的資料是否為空
        if not p_data.get('price') and not p_data.get('institutional') and not p_data.get('shareholding'):
            print(f"      -> [{sid}] API 回傳資料為空，跳過儲存。")
            return "EMPTY"
        save_price_data(sid, p_data)
        return "DONE"
    else:
        print(f"      -> [{sid}] API 請求失敗。")
    return "FAIL"

def process_phase_micro(acc, sid, target_dates, threads, h_path):
    if shutdown_event.is_set(): return
    
    if not target_dates:
        return "SKIP"

    # 超前檢查：打開檔案確認日期是否齊全
    m_path = os.path.join(get_script_dir(__file__), "data_independent_microstructure", f"{sid}.json")
    existing_tdr = {}
    if os.path.exists(m_path):
        try:
            with open(m_path, 'r', encoding='utf-8') as f:
                existing_micro = json.load(f)
                # 支援兩種格式
                # 支援兩種格式
                if 'trading_daily_report' in existing_micro:
                    existing_tdr = existing_micro['trading_daily_report']
                elif sid in existing_micro and 'trading_daily_report' in existing_micro[sid]:
                    existing_tdr = existing_micro[sid]['trading_daily_report']
                else:
                    existing_tdr = existing_micro
        except: pass
    
    # 確保 existing_tdr 是字典且 key 是日期字串
    if not isinstance(existing_tdr, dict):
        existing_tdr = {}
        
    needed_dates = [d for d in target_dates if d not in existing_tdr]
    
    if not needed_dates:
        return "SKIP"

    # 進入抓取模式
    check_usage_and_protection(acc['api'], acc['name'])
    print(f"      -> [{sid}] 補抓微觀資料 ({len(needed_dates)} 天)...")
    
    new_tdr = {}
    no_data_dates = []
    with ThreadPoolExecutor(max_workers=threads) as executor:
        future_to_day = {executor.submit(process_micro_day, acc['api'], sid, d): d for d in needed_dates}
        for f in as_completed(future_to_day):
            if shutdown_event.is_set(): break
            d_str, day_res = f.result()
            if day_res: new_tdr[d_str] = day_res
            else: no_data_dates.append(d_str)
    
    if new_tdr:
        save_json_robust(m_path, {sid: {'trading_daily_report': new_tdr}})
    if no_data_dates:
        update_holidays_file(h_path, no_data_dates)
    return "DONE"

def main():
    global current_api_threads
    start_time = time.time()
    parser = argparse.ArgumentParser()
    parser.add_argument('--stock_id')
    parser.add_argument('--threads', type=int, default=5, help='API 並行抓取執行緒數 (初始衝刺值)')
    parser.add_argument('--workers', type=int, default=10, help='檔案檢查並行工作數 (IO 密集)')
    args = parser.parse_args()
    
    # 初始化全域 API 執行緒數為使用者輸入的值
    current_api_threads = args.threads

    config_path = os.path.join(get_script_dir(__file__), 'config', 'find_mind_config.json')
    if not os.path.exists(config_path):
        config_path = os.path.join(get_script_dir(__file__), 'config.json')
    if not os.path.exists(config_path):
        print(f"[ERROR] 找不到配置檔案！")
        print(f"  嘗試路徑 1: {os.path.join(get_script_dir(__file__), 'config', 'find_mind_config.json')}")
        print(f"  嘗試路徑 2: {os.path.join(get_script_dir(__file__), 'config.json')}")
        print(f"  請確認配置檔案存在並包含有效的 FinMind API token")
        return
    with open(config_path, 'r') as f: config = json.load(f)
    
    apis = []
    for k in sorted(config.keys()):
        if k.startswith('find_mind') and config[k].get('token') and "HERE" not in config[k]['token']:
            api = DataLoader()
            api.login_by_token(config[k]['token'])
            level = 2 if api.api_usage_limit > 600 else 1
            apis.append({'api': api, 'level': level, 'name': k})
    
    if not apis:
        print(f"[ERROR] 沒有找到有效的 FinMind API 配置！")
        print(f"  配置檔案: {config_path}")
        print(f"  請確認配置檔案中包含以 'find_mind' 開頭的有效 token")
        return
    primary_api = apis[0] # 使用第一個 (也是唯一的) 高額度帳號

    # 讀取國定假日
    h_path = os.path.join(get_script_dir(__file__), "data", "holidays.json")
    holidays = get_all_holidays()

    # 日期範圍與時間限制判斷
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    
    # 判斷是否為週末 (5=Saturday, 6=Sunday)
    is_weekend = now.weekday() >= 5

    # Price 資料限制：14:00 以前只能拿昨天以前的資料；週末則拿週五以前的資料
    # 注意：FinMind API 傳入 end_date=today 時，若資料未產出會回傳到昨天
    # 但我們的 Fast-Check 需要精確的目標日期
    if is_weekend:
        # 週末時，目標日期應為最後一個工作日 (週五)
        price_end_date = (now - timedelta(days=now.weekday() - 4)).strftime('%Y-%m-%d')
    elif now.hour < 14:
        price_end_date = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        price_end_date = today_str
        
    # Micro (券商) 資料限制：17:00 以前只能拿昨天以前的資料；週末則拿週五以前的資料
    if is_weekend:
        micro_end_date = (now - timedelta(days=now.weekday() - 4)).strftime('%Y-%m-%d')
    elif now.hour < 17:
        micro_end_date = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        micro_end_date = today_str

    # 如果今天是假日，則 end_date 應該自動回溯到最後一個交易日
    # 這裡透過 pd.date_range 的 freq='B' 配合 holidays 過濾來達成

    # 強制修正：如果 end_date 在假日檔中，必須回溯到前一個交易日，否則 Fast-Check 會失效
    temp_price_dates = pd.date_range(end=price_end_date, periods=10, freq='B').strftime('%Y-%m-%d').tolist()
    price_end_date = [d for d in temp_price_dates if d <= price_end_date and d not in holidays][-1]
    
    temp_micro_dates = pd.date_range(end=micro_end_date, periods=10, freq='B').strftime('%Y-%m-%d').tolist()
    micro_end_date = [d for d in temp_micro_dates if d <= micro_end_date and d not in holidays][-1]

    start_date_str = (now - timedelta(days=860)).strftime('%Y-%m-%d')
    
    # 修正：如果今天被誤植在假日檔中，先在記憶體中排除它，確保今天能被正確抓取
    if today_str in holidays:
        print(f"      [Notice] 偵測到今日 {today_str} 被誤植於假日檔，已在本次執行中暫時排除。")
        holidays = [d for d in holidays if d != today_str]

    # 產生 Price 的目標日期 (用於 Phase 1)
    price_b_days = pd.date_range(start=start_date_str, end=price_end_date, freq='B').strftime('%Y-%m-%d').tolist()
    price_target_dates = [d for d in price_b_days if d not in holidays]
    # 修正：如果 price_end_date 是假日，則真正的目標應該是 price_target_dates 的最後一天
    if price_target_dates:
        price_end_date = price_target_dates[-1]
    
    # 產生 Micro 的目標日期 (用於 Phase 2)
    micro_b_days = pd.date_range(start=start_date_str, end=micro_end_date, freq='B').strftime('%Y-%m-%d').tolist()
    micro_target_dates = [d for d in micro_b_days if d not in holidays]
    if micro_target_dates:
        micro_end_date = micro_target_dates[-1]

    # 最終同步 last_target_date 給 Phase 1 使用
    last_price_date = price_target_dates[-1] if price_target_dates else ""
    
    stocks_path = os.path.join(get_script_dir(__file__), 'taiwan_stocks.csv')
    stocks = [args.stock_id] if args.stock_id else (pd.read_csv(stocks_path).iloc[:,0].astype(str).tolist() if os.path.exists(stocks_path) else ['2330'])
    
    # --- PHASE 1: PRICE DATA (Multi-threaded by Stock) ---
    print(f"\n>>> PHASE 1: Fetching Price/Institutional/Shareholding Data (Workers: {args.workers}, API Threads: {current_api_threads})")
    print(f"      Target End Date: {price_end_date}")
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for sid in stocks:
            if shutdown_event.is_set(): break
            # API 併發控制
            while len([f for f in futures if not f.done()]) >= current_api_threads:
                time.sleep(0.05)
                if shutdown_event.is_set(): break
            futures[executor.submit(process_phase_price, primary_api, sid, start_date_str, price_end_date, last_price_date)] = sid
        
        for i, f in enumerate(as_completed(futures)):
            if shutdown_event.is_set(): break
            sid = futures[f]
            try:
                res = f.result()
                if (i + 1) % 10 == 0 or (i + 1) == len(stocks):
                    print(f"\r      Progress: {i+1}/{len(stocks)} stocks checked/processed. (Last: {sid})", end="")
            except Exception as e:
                print(f"\n      [Error] {sid}: {e}")
    print("\n      Phase 1 Completed.")
    
    # --- PHASE 2: MICRO DATA (Dynamic Multi-threaded) ---
    print(f"\n>>> PHASE 2: Fetching Micro Data (Workers: {args.workers}, API Threads: {current_api_threads}, Fast-Check Enabled)")
    print(f"      Target End Date: {micro_end_date}")
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for sid in stocks:
            if shutdown_event.is_set(): break
            if primary_api['level'] < 2: continue
            # API 併發控制
            while len([f for f in futures if not f.done()]) >= current_api_threads:
                time.sleep(0.05)
                if shutdown_event.is_set(): break
            futures[executor.submit(process_phase_micro, primary_api, sid, micro_target_dates, args.threads, h_path)] = sid
        
        for i, f in enumerate(as_completed(futures)):
            if shutdown_event.is_set(): break
            sid = futures[f]
            try:
                res = f.result()
                if (i + 1) % 10 == 0 or (i + 1) == len(stocks):
                    print(f"\r      Progress: {i+1}/{len(stocks)} stocks checked/processed. (Last: {sid})", end="")
            except Exception as e:
                print(f"\n      [Error] {sid}: {e}")
    
    end_time = time.time()
    duration = end_time - start_time
    hours, rem = divmod(duration, 3600)
    minutes, seconds = divmod(rem, 60)
    
    print(f"\n\n[FINISH] 任務結束。 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"      總歷時時間: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")

if __name__ == "__main__":
    main()
