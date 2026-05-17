import json
import os
import unicodedata
import argparse
from datetime import datetime

# =================================================================
# 策略參數與權重設定 (您可以根據需求自行修改)
# =================================================================
# 1. 基本門檻與過濾
MIN_GAIN_REQUIRED = 0.00      # 至少要正報酬才顯示
MOMENTUM_DAYS = 4             # 幾天內...
MOMENTUM_THRESHOLD = 0.05     # ...漲幅超過幾% 會標記 !

# 2. 權重分配 (總和建議 100)
WEIGHT_GAIN = 15              # 當日/波段漲幅權重
WEIGHT_STREAK = 10            # 連續上漲天數權重
WEIGHT_VOLUME = 15            # 交易量突破權重 (量比)
WEIGHT_SITC = 25              # 投信挹注權重
WEIGHT_INSTITUTIONAL = 10     # 外資/自營商權重
WEIGHT_BREAKOUT = 10          # 壓力線突破權重
WEIGHT_VOLUME_MAGNITUDE = 15  # 交易量絕對級距權重 (避免低量股)

MIN_SCORE_TO_PRINT = 35       # 總分超過此值才印出

# 3. 各項機制變數
VOL_AVG_DAYS = 5
VOL_BREAKTHROUGH_RATIO = 2.0

# 交易量級距 (單位：股)
VOL_LEVELS = [100000, 500000, 1500000, 5000000] 

SITC_AVG_DAYS = 30
SITC_MULTI_RATIO = 1.5
SITC_MIN_BUY_SHARES = 100000

FOREIGN_STREAK_DAYS = 4
DEALER_INFLOW_THRESHOLD = 500000

# 4. 價格連漲係數
STREAK_COEFFICIENT = 20       # 每多連漲一天加幾分

# 5. 壓力線與 額外篩選
STRICT_BREAKOUT_FILTER = False # 如果設為 True，則只印出有「突破壓力」的標的
RESISTANCE_LOOKBACK = 180       # 找過去 N 天最高點作為壓力線
# =================================================================

def get_script_dir():
    return os.path.dirname(os.path.abspath(__file__))

# --- 全域快取 ---
_SORTED_DATES_CACHE = {}
_LOADED_DATA_CACHE = None

def load_data(filename='stock_data.json'):
    global _LOADED_DATA_CACHE
    if _LOADED_DATA_CACHE is not None:
        return _LOADED_DATA_CACHE
        
    # 自動執行增量合併
    sync_independent_data(filename)
    
    path = os.path.join(get_script_dir(), filename)
    print(f"[DEBUG] Attempting to load data from: {path}")
    if os.path.exists(path):
        print(f"[DEBUG] File exists. Size: {os.path.getsize(path)} bytes")
        with open(path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                print(f"[DEBUG] JSON loaded successfully. Type: {type(data)}")
                _LOADED_DATA_CACHE = data
                return data
            except json.JSONDecodeError as e:
                print(f"[DEBUG] JSON Decode Error: {e}")
                return {}
    else:
        print(f"[DEBUG] File does not exist at {path}")
    return {}

def sync_independent_data(target_file):
    """將 data_independent 中的更新同步到大 JSON 檔案"""
    source_dir = os.path.join(get_script_dir(), 'data_independent')
    target_path = os.path.join(get_script_dir(), target_file)
    
    if not os.path.exists(source_dir):
        return

    # 取得上次合併時間 (大檔最後修改時間)
    last_merge_time = 0
    if os.path.exists(target_path):
        last_merge_time = os.path.getmtime(target_path)
    
    # 使用 scandir 快速掃描，這不會讀取檔案內容
    changed_files = []
    with os.scandir(source_dir) as it:
        for entry in it:
            if entry.is_file() and entry.name.endswith('.json'):
                # 只有當小檔修改時間「新於」大檔，才加入待更新清單
                if entry.stat().st_mtime > last_merge_time:
                    changed_files.append(entry.path)
            
    if not changed_files:
        print("[INFO] No new data in data_independent to sync.")
        return

    print(f"[INFO] Syncing {len(changed_files)} updated stocks from data_independent...")
    
    merged_data = {}
    if os.path.exists(target_path):
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                merged_data = json.load(f)
        except Exception:
            merged_data = {}

    # 只有這裡會打開那幾個「有變動」的小 JSON 檔案
    for file_path in changed_files:
        # 增加重試機制，避免剛好碰到 fetch 正在改名 (Windows 下可能會有 PermissionError)
        for _ in range(3):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    merged_data.update(json.load(f))
                break # 成功則跳出重試
            except (PermissionError, json.JSONDecodeError):
                time.sleep(0.1) # 稍等一下再試
            except Exception:
                break

    # 排序並存回
    sorted_data = dict(sorted(merged_data.items()))
    temp_path = target_path + ".tmp"
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(sorted_data, f, ensure_ascii=False, indent=4)
    
    if os.path.exists(target_path):
        os.remove(target_path)
    os.rename(temp_path, target_path)
    print(f"[INFO] Sync complete. {target_file} is up to date.")

# --- 輔助函數：處理中英文字元對齊 ---

def get_display_width(s):
    """計算字串在終端機顯示的寬度 (中文字佔 2 單位)"""
    width = 0
    for char in s:
        if unicodedata.east_asian_width(char) in ('W', 'F', 'A'):
            width += 2
        else:
            width += 1
    return width

def pad_string(s, width):
    """手動補齊空白以對齊終端機顯示寬度"""
    s = str(s)
    cur_w = get_display_width(s)
    return s + " " * max(0, width - cur_w)

# --- 核心機制函數 ---

def check_volume_breakthrough(price_data, sorted_dates, idx):
    if idx < 1: return False, 0
    actual_lookback = min(idx, VOL_AVG_DAYS)
    current_vol = price_data[sorted_dates[idx]].get('Trading_Volume', 0)
    prev_vols = [price_data[sorted_dates[i]].get('Trading_Volume', 0) for i in range(idx - actual_lookback, idx)]
    avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0
    if avg_vol == 0: return False, 0
    ratio = current_vol / avg_vol
    return ratio >= VOL_BREAKTHROUGH_RATIO, ratio

def check_sitc_momentum(inst_data, sorted_dates, idx):
    if idx < 1: return False, 0
    actual_lookback = min(idx, SITC_AVG_DAYS)
    def get_net(i):
        d = inst_data.get(sorted_dates[i], {}).get('Investment_Trust', {})
        return d.get('buy', 0) - d.get('sell', 0)
    current_net = get_net(idx)
    if current_net < SITC_MIN_BUY_SHARES: return False, 0
    prev_nets = [abs(get_net(i)) for i in range(idx - actual_lookback, idx)]
    avg_net = sum(prev_nets) / len(prev_nets) if prev_nets else 0
    effective_avg = max(avg_net, SITC_MIN_BUY_SHARES / 2)
    ratio = current_net / effective_avg
    return ratio >= SITC_MULTI_RATIO, ratio

def check_price_streak(price_data, sorted_dates, idx):
    streak = 0
    for i in range(idx, 0, -1):
        cur = price_data[sorted_dates[i]]['close']
        prev = price_data[sorted_dates[i-1]]['close']
        if cur > prev: streak += 1
        else: break
    return streak

def check_foreign_streak(inst_data, sorted_dates, idx):
    streak = 0
    for i in range(idx, -1, -1):
        d = inst_data.get(sorted_dates[i], {}).get('Foreign_Investor', {})
        if (d.get('buy', 0) - d.get('sell', 0)) > 0: streak += 1
        else: break
    return streak >= FOREIGN_STREAK_DAYS, streak

def check_dealer_inflow(inst_data, sorted_dates, idx):
    d = inst_data.get(sorted_dates[idx], {}).get('Dealer_self', {})
    net = d.get('buy', 0) - d.get('sell', 0)
    return net >= DEALER_INFLOW_THRESHOLD, net

def check_resistance_breakout(price_data, sorted_dates, idx):
    if idx < 1: return False, 0
    actual_lookback = min(idx, RESISTANCE_LOOKBACK)
    current_close = price_data[sorted_dates[idx]]['close']
    lookback_prices = [price_data[sorted_dates[i]]['max'] for i in range(idx - actual_lookback, idx)]
    resistance = max(lookback_prices) if lookback_prices else 0
    is_breakout = current_close >= resistance and resistance > 0
    return is_breakout, resistance

def get_volume_level_score(volume):
    """根據交易量絕對值回傳級距分數 (0-100)"""
    if volume < VOL_LEVELS[0]: return 0
    if volume < VOL_LEVELS[1]: return 25
    if volume < VOL_LEVELS[2]: return 50
    if volume < VOL_LEVELS[3]: return 75
    return 100

def calculate_score(details):
    score = 0
    score += (min(100, (details['gain'] / 0.05) * 100) if details['gain'] > 0 else 0) * WEIGHT_GAIN / 100
    score += (min(100, details['price_streak'] * STREAK_COEFFICIENT)) * WEIGHT_STREAK / 100
    score += (min(100, (details['vol_ratio'] / 2.0) * 100)) * WEIGHT_VOLUME / 100
    score += (min(100, (details['sitc_ratio'] / 1.5) * 100)) * WEIGHT_SITC / 100
    inst_score = (50 if details['foreign_days'] >= FOREIGN_STREAK_DAYS else 0) + (50 if details['dealer_ok'] else 0)
    score += inst_score * WEIGHT_INSTITUTIONAL / 100
    if details['breakout_ok']: score += WEIGHT_BREAKOUT
    
    # 交易量級距評分
    vol_mag_score = get_volume_level_score(details['raw_volume'])
    score += vol_mag_score * WEIGHT_VOLUME_MAGNITUDE / 100
    
    return score

# --- 主分析函數 ---

def analyze_momentum(data, start_date, end_date):
    results = []
    filtered_counts = {
        'missing_dates': 0,
        'low_gain': 0,
        'breakout_filter': 0,
        'low_score': 0
    }
    
    for stock_id, details in data.items():
        price_data = details.get('price', {})
        inst_data = details.get('institutional', {})
        
        if start_date not in price_data or end_date not in price_data:
            filtered_counts['missing_dates'] += 1
            continue
            
        start_close = price_data[start_date]['close']
        if not start_close:
            filtered_counts['missing_dates'] += 1
            continue
            
        end_close = price_data[end_date]['close']
        gain = (end_close - start_close) / start_close
        if gain < MIN_GAIN_REQUIRED:
            filtered_counts['low_gain'] += 1
            continue
            
        # 使用快取避免重複排序
        if stock_id in _SORTED_DATES_CACHE:
            sorted_dates = _SORTED_DATES_CACHE[stock_id]
        else:
            sorted_dates = sorted(price_data.keys())
            _SORTED_DATES_CACHE[stock_id] = sorted_dates
            
        idx = sorted_dates.index(end_date)
        
        price_streak = check_price_streak(price_data, sorted_dates, idx)
        vol_ok, vol_ratio = check_volume_breakthrough(price_data, sorted_dates, idx)
        sitc_ok, sitc_ratio = check_sitc_momentum(inst_data, sorted_dates, idx)
        foreign_ok, foreign_days = check_foreign_streak(inst_data, sorted_dates, idx)
        dealer_ok, _ = check_dealer_inflow(inst_data, sorted_dates, idx)
        breakout_ok, res_level = check_resistance_breakout(price_data, sorted_dates, idx)
        
        if STRICT_BREAKOUT_FILTER and not breakout_ok:
            filtered_counts['breakout_filter'] += 1
            continue
            
        mom_gain = 0
        if idx >= MOMENTUM_DAYS:
            prev_p = price_data[sorted_dates[idx - MOMENTUM_DAYS]]['close']
            mom_gain = (end_close - prev_p) / prev_p if prev_p else 0

        res = {
            'stock_id': stock_id, 'close': end_close, 'gain': gain, 'mom_gain': mom_gain,
            'price_streak': price_streak, 'vol_ratio': vol_ratio,
            'sitc_ratio': sitc_ratio, 'foreign_days': foreign_days,
            'dealer_ok': dealer_ok, 'breakout_ok': breakout_ok,
            'resistance': res_level, 'raw_volume': price_data[end_date].get('Trading_Volume', 0)
        }
        res['score'] = calculate_score(res)
        
        if res['score'] >= MIN_SCORE_TO_PRINT:
            results.append(res)
        else:
            filtered_counts['low_score'] += 1
                
    results.sort(key=lambda x: (x['score'], x['gain']), reverse=True)
    return results

def main():
    parser = argparse.ArgumentParser(description='Analyze Taiwan stock momentum.')
    parser.add_argument('filename', nargs='?', default='stock_data.json', help='The JSON file to analyze (default: stock_data.json)')
    args = parser.parse_args()

    data = load_data(args.filename)
    if not data:
        print(f"[DEBUG] No data loaded from {args.filename}.")
        return
    
    print(f"[DEBUG] Loaded data for {len(data)} stocks.")
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    if len(all_dates) < 2:
        print(f"[DEBUG] Not enough dates found. Count: {len(all_dates)}. Dates: {all_dates}")
        return
    
    end_date = all_dates[-1]
    start_date = all_dates[-20]
    print(f"[DEBUG] Analyzing from {start_date} to {end_date}")
    
    print(f"\n--- 綜合加權評分動能報告 ({end_date}) ---")
    print(f"資料來源：{args.filename}")
    print(f"篩選門檻：總分 > {MIN_SCORE_TO_PRINT}, {MOMENTUM_DAYS}日漲幅 > {MOMENTUM_THRESHOLD:.0%}")
    print(f"權重分配：漲幅{WEIGHT_GAIN}%, 連漲{WEIGHT_STREAK}%, 投信{WEIGHT_SITC}%, 量比{WEIGHT_VOLUME}%, 突破{WEIGHT_BREAKOUT}%, 法人{WEIGHT_INSTITUTIONAL}%, 量級{WEIGHT_VOLUME_MAGNITUDE}%")
    
    # 欄位寬度設定 (中文字佔 2 單位)
    headers = ["代號", "現價", "總分", "漲幅", "成交量", "量比", "投信比", "壓力位", "備註"]
    widths = [8, 8, 6, 8, 12, 6, 8, 10, 30]
    
    separator = "-" * (sum(widths) + len(widths) * 3)
    print(separator)
    
    # 列印表頭
    header_line = " | ".join(pad_string(h, w) for h, w in zip(headers, widths))
    print(header_line)
    print(separator)
    
    results = analyze_momentum(data, start_date, end_date)
    for res in results:
        mom_tag = "!" if res['mom_gain'] >= MOMENTUM_THRESHOLD else ""
        note = ""
        if res['breakout_ok']: note += "突破壓力 "
        if res['sitc_ratio'] >= SITC_MULTI_RATIO: note += "投信強買 "
        if res['price_streak'] >= 3: note += f"強勢{res['price_streak']}連漲 "
        
        items = [
            res['stock_id'],
            f"{res['close']:.2f}",
            f"{res['score']:.0f}",
            f"{res['gain']:.1%}",
            f"{res['raw_volume']/10000:,.0f}萬",
            f"{res['vol_ratio']:.1f}",
            f"{res['sitc_ratio']:.1f}",
            f"{res['resistance']:.1f}",
            note
        ]
        line = " | ".join(pad_string(item, w) for item, w in zip(items, widths))
        print(line)

if __name__ == "__main__":
    main()
