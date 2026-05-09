import os
import json
import pandas as pd
import argparse
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import time
import threading
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Global event for handling Ctrl+C
shutdown_event = threading.Event()
# Lock for file operations on individual files (usually not needed if 1 thread per stock, but safe to keep)
file_locks = {}
locks_lock = threading.Lock()

def get_script_dir():
    return os.path.dirname(os.path.abspath(__file__))

def get_stock_lock(stock_id):
    with locks_lock:
        if stock_id not in file_locks:
            file_locks[stock_id] = threading.Lock()
        return file_locks[stock_id]

def load_config():
    config_path = os.path.join(get_script_dir(), 'config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

def load_stock_data(stock_id):
    """Load data for a single stock from independent file."""
    path = os.path.join(get_script_dir(), 'data_independent', f"{stock_id}.json")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get(stock_id, {})
        except (json.JSONDecodeError, Exception):
            return {}
    return {}

def save_stock_data(stock_id, data):
    """Save data for a single stock to independent file."""
    target_dir = os.path.join(get_script_dir(), 'data_independent')
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
        
    path = os.path.join(target_dir, f"{stock_id}.json")
    
    with get_stock_lock(stock_id):
        existing_data = load_stock_data(stock_id)
        
        if existing_data:
            # Merge logic
            for category in ['price', 'institutional', 'shareholding']:
                if category in data:
                    if category not in existing_data:
                        existing_data[category] = {}
                    existing_data[category].update(data[category])
            existing_data['last_updated'] = data['last_updated']
        else:
            existing_data = data
        
        # Sorting logic within the stock entry
        for category in ['price', 'institutional', 'shareholding']:
            if category in existing_data and isinstance(existing_data[category], dict):
                existing_data[category] = dict(sorted(existing_data[category].items()))
        
        # Atomic write using rename
        temp_path = path + ".tmp"
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump({stock_id: existing_data}, f, ensure_ascii=False, indent=4)
        
        if os.path.exists(path):
            os.remove(path)
        os.rename(temp_path, path)

def fetch_stock_data(api, stock_id, start_date, end_date, account_name):
    if shutdown_event.is_set(): return None
    try:
        df_price = api.taiwan_stock_daily(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if shutdown_event.is_set(): return None
        df_inst = api.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if shutdown_event.is_set(): return None
        df_hold = api.taiwan_stock_shareholding(stock_id=stock_id, start_date=start_date, end_date=end_date)
        
        price_dict = {}
        if not df_price.empty:
            for record in df_price.to_dict(orient='records'):
                d = record.pop('date')
                record.pop('stock_id', None)
                price_dict[d] = record
        
        inst_dict = {}
        if not df_inst.empty:
            for record in df_inst.to_dict(orient='records'):
                d = record.pop('date')
                name = record.pop('name')
                record.pop('stock_id', None)
                if d not in inst_dict: inst_dict[d] = {}
                inst_dict[d][name] = record
                
        hold_dict = {}
        if not df_hold.empty:
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
    except Exception as e:
        err_msg = str(e)
        # Handle 402 (Session full / Upper limit), 403 (Forbidden/Rate limit), 429 (Too many requests)
        if any(x in err_msg for x in ["402", "403", "429"]) or "upper limit" in err_msg.lower() or "too many requests" in err_msg.lower():
            return "RATE_LIMIT"
        if "400" in err_msg or "illegal" in err_msg.lower():
            return "TOKEN_ERROR"
        return None

def check_momentum(price_data, lookback=2, threshold=0.05):
    if not price_data or len(price_data) < lookback + 1:
        return False, 0
    sorted_dates = sorted(price_data.keys())
    latest_date = sorted_dates[-1]
    base_date = sorted_dates[-(lookback + 1)]
    latest_close = price_data[latest_date]['close']
    base_close = price_data[base_date]['close']
    if base_close == 0: return False, 0
    gain = (latest_close - base_close) / base_close
    return gain >= threshold, gain

def process_single_stock(api, stock_id, start_date, end_date, target_dates, sleep_time, account_name, total_market_stocks, total_test_stocks, index, last_target_date, lookback, threshold):
    if shutdown_event.is_set(): return None
    
    # Load only this stock's data
    data = load_stock_data(stock_id)
    
    # Check if we already have the latest data
    has_data = last_target_date in data.get('price', {})
    
    if has_data:
        if 'price' in data:
            is_strong, gain = check_momentum(data['price'], lookback=lookback, threshold=threshold)
            if is_strong:
                print(f"!!! [{account_name}] [{stock_id}] STRONG MOMENTUM: {gain:.2%}")
                return (stock_id, gain)
        return None

    # If no data, proceed with fetching
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{account_name}] [{timestamp}] [{index+1}/{total_test_stocks}] Processing {stock_id}...")
    
    max_retries = 5
    fetch_start_time = time.time()
    for attempt in range(max_retries):
        if shutdown_event.is_set(): return None
        fetched_data = fetch_stock_data(api, stock_id, start_date, end_date, account_name)
        if fetched_data == "RATE_LIMIT":
            print(f"[{account_name}] API limit hit (402/403/429)! Waiting 10 minutes before retry {attempt+1}/{max_retries}...")
            for _ in range(600):
                if shutdown_event.is_set(): break
                time.sleep(1)
            continue
        if fetched_data == "TOKEN_ERROR":
            print(f"[{account_name}] ERROR: Token illegal for account {account_name}")
            return None
        if fetched_data:
            save_stock_data(stock_id, fetched_data)
            # Reload to get merged data
            data = load_stock_data(stock_id)
            
            elapsed = time.time() - fetch_start_time
            remaining_sleep = sleep_time - elapsed
            if remaining_sleep > 0:
                print(f"[{account_name}] Fetch & save took {elapsed:.1f}s. Sleeping remaining {remaining_sleep:.1f}s...")
                for _ in range(int(remaining_sleep)):
                    if shutdown_event.is_set(): break
                    time.sleep(1)
            break
        else:
            print(f"[{account_name}] Failed to fetch {stock_id}.")
            return None
    
    if data and 'price' in data:
        is_strong, gain = check_momentum(data['price'], lookback=lookback, threshold=threshold)
        if is_strong:
            print(f"!!! [{account_name}] [{stock_id}] STRONG MOMENTUM: {gain:.2%}")
            return (stock_id, gain)
        else:
            print(f"[{account_name}] [{stock_id}] Momentum: {gain:.2%}")
    return None

def get_sorted_stock_list(stocks_path):
    order_path = os.path.join(get_script_dir(), 'fetch_order.json')
    if os.path.exists(order_path):
        with open(order_path, 'r') as f:
            return json.load(f)
    
    print("Generating volume-based fetch order...")
    stocks_df = pd.read_csv(stocks_path, encoding='utf-8-sig')
    stock_ids = stocks_df.iloc[:, 0].astype(str).tolist()
    volumes = []
    
    for sid in stock_ids:
        vol = 0
        data = load_stock_data(sid)
        if 'price' in data:
            price_entries = data['price']
            if price_entries:
                latest_date = sorted(price_entries.keys())[-1]
                vol = price_entries[latest_date].get('Trading_Volume', 0)
        volumes.append((sid, vol))
        
    volumes.sort(key=lambda x: x[1], reverse=True)
    sorted_ids = [v[0] for v in volumes]
    with open(order_path, 'w') as f:
        json.dump(sorted_ids, f)
    return sorted_ids

def main():
    parser = argparse.ArgumentParser(description='FinMind 股票資料抓取工具')
    parser.add_argument('--stock_id', help='指定抓取單一股票代碼 (例如: 2330)')
    args = parser.parse_args()

    try:
        config = load_config()
        account_keys = sorted([k for k in config.keys() if k.startswith('find_mind')])
        apis = []
        for k in account_keys:
            token = config[k].get('token')
            if token and "HERE" not in token:
                api = DataLoader()
                api.login_by_token(token)
                apis.append((api, k))
                print(f"Logged in: {k}")
        
        if not apis:
            print("No valid FinMind tokens found!")
            return

        # Momentum Analysis Settings
        LOOKBACK_DAYS = 2
        GAIN_THRESHOLD = 0.05
        
        stocks_path = os.path.join(get_script_dir(), 'taiwan_stocks.csv')
        
        if args.stock_id:
            test_stocks = [args.stock_id]
            total_market_stocks = 1
            print(f"指定抓取模式: {args.stock_id}")
        elif os.path.exists(stocks_path):
            test_stocks = get_sorted_stock_list(stocks_path)
            total_market_stocks = len(pd.read_csv(stocks_path))
        else:
            test_stocks = ['2330', '2317']
            total_market_stocks = len(test_stocks)

        start_date = '2025-05-01'
        end_date = datetime.now().strftime('%Y-%m-%d')  #'2026-05-05'
        target_dates = pd.date_range(start=start_date, end=end_date, freq='B').strftime('%Y-%m-%d').tolist()
        last_target_date = target_dates[-1]
        
        num_workers = len(apis)
        SLEEP_PER_ACCOUNT_STOCK = 38
        momentum_list = []
        
        print(f"Starting fetch with {num_workers} accounts. Ctrl+C to stop.")
        
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = []
            for i, stock_id in enumerate(test_stocks):
                api_instance, account_name = apis[i % num_workers]
                futures.append(executor.submit(
                    process_single_stock, api_instance, stock_id, start_date, end_date, target_dates, 
                    SLEEP_PER_ACCOUNT_STOCK, account_name, total_market_stocks, len(test_stocks), 
                    i, last_target_date, LOOKBACK_DAYS, GAIN_THRESHOLD
                ))
            
            try:
                for future in as_completed(futures):
                    if shutdown_event.is_set(): break
                    res = future.result()
                    if res: momentum_list.append(res)
            except KeyboardInterrupt:
                print("\nStopping...")
                shutdown_event.set()
                for f in futures: f.cancel()
                executor.shutdown(wait=True)
                sys.exit(0)

        print("\n--- Summary ---")
        if momentum_list:
            momentum_list.sort(key=lambda x: x[1], reverse=True)
            print(f"Stocks with strong momentum:")
            for sid, g in momentum_list: print(f"- {sid}: {g:.2%}")
        else:
            print("No stocks met momentum criteria.")

    except KeyboardInterrupt:
        print("\nExiting.")
        shutdown_event.set()
        sys.exit(0)

if __name__ == "__main__":
    main()
