#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
backtest_momentum_day_trading.py
聖盃模式 4.0 終極精準版 (含極速快取與分批出場)
目標：超越 0050 漲幅 (25%+)
"""

import json
import os
import sys
import sqlite3
import pandas as pd
import time
import pickle
try:
    import psutil
except ImportError:
    psutil = None
from datetime import datetime, timedelta
from collections import defaultdict

# 效能監控輔助函數
def get_ram_usage():
    if psutil:
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / 1024 / 1024  # MB
    return 0

# 嘗試設定輸出編碼
try:
    if sys.stdout.encoding != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

# =================================================================
# 載入外部設定
# =================================================================
sys.path.append(os.path.join(os.path.dirname(__file__), 'backtest_micro_simulate', 'v1', 'config'))

# =================================================================
# 全域開關與流程控制 (Pipeline Switches)
# =================================================================
PIPELINE_CONTROL = {
    # 階段開關
    'ENABLE_SECTOR_SCAN': True,      # 1. 產業動能掃描 (相依性: 影響個股篩選池)
    'ENABLE_FEATURE_EXTRACT': True,  # 2. 個股特徵提取 (相依性: 基礎資料流)
    'ENABLE_MOMENTUM_SCORE': True,   # 3. 綜合動能評分 (相依性: 影響順勢模式排序)
    'ENABLE_DIP_SCORE': True,        # 3. 抄底專用評分 (相依性: 影響逆勢模式排序)
    'ENABLE_SECONDARY_INDICATORS': True, # 4. 輔助指標計算 (當沖/風險/量價)
    
    # 買進策略開關 (相依性: 需在 decide_buy 中執行)
    'STRATEGY_SWITCH': {
        'HOLY_GRAIL_BREAKOUT': False, # 聖盃突破模式 (相依性: 需大多頭環境)
        'WASH_OUT_DIP': True,         # 洗盤抄底模式 (相依性: 具備大盤豁免權)
        'VOLATILITY': False,          # 波動率模式   (相依性: 需高動能評分)
        'SCALPING': False,            # 極短線模式   (相依性: 需當沖訊號)
        'LOW_ENTRY': False            # 低位階模式   (相依性: 需低動能評分)
    }
}

# 預設參數 (2026 年最強版本)
HOLY_GRAIL_PARAMS = {'PREV_GAIN_THRESHOLD': 0.05, 'VOL_DRY_RATIO': 0.65, 'WINNER_LOCK_RATIO': 0.15, 'PRICE_SUPPORT_LEVEL': 0.97, 'USE_MARKET_FILTER': True}
STRATEGY_MODES = {
    'HOLY_GRAIL_BREAKOUT': {'STOP_LOSS': -0.05, 'TAKE_PROFIT': 9.99, 'BREAK_EVEN_TRIGGER': 0.06, 'HOLD_DAYS': 20, 'PARTIAL_EXIT_GAIN': 0.10, 'TRAILING_STOP_NORMAL': 0.08},
    'VOLATILITY': {'STOP_LOSS': -0.08, 'TAKE_PROFIT': 9.99, 'BREAK_EVEN_TRIGGER': 0.05, 'HOLD_DAYS': 10},
    'SCALPING': {'STOP_LOSS': -0.03, 'TAKE_PROFIT': 0.06, 'BREAK_EVEN_TRIGGER': 0.03, 'HOLD_DAYS': 1},
    'WASH_OUT_DIP': {'STOP_LOSS': -0.03, 'TAKE_PROFIT': 0.05, 'HOLD_DAYS': 2},
    'LOW_ENTRY': {'STOP_LOSS': -0.05, 'TAKE_PROFIT': 9.99, 'BREAK_EVEN_TRIGGER': 0.08, 'HOLD_DAYS': 40, 'MAX_MOMENTUM': 45}
}
BACKTEST_CONFIG = {'STARTING_CASH': 2000000, 'TOP_N': 8, 'MIN_TRADING_VALUE': 30000000}

try:
    from holy_grail_config import HOLY_GRAIL_PARAMS as HGP, STRATEGY_MODES as SM, BACKTEST_CONFIG as BC
    HOLY_GRAIL_PARAMS.update(HGP); STRATEGY_MODES.update(SM); BACKTEST_CONFIG.update(BC)
except ImportError: pass

DEFAULT_WEIGHTS = {'WEIGHT_GAIN': 40, 'WEIGHT_VOLUME': 10, 'WEIGHT_FOREIGN': 10, 'WEIGHT_SITC': 10, 'WEIGHT_VCP': 10, 'WEIGHT_BREAKOUT': 10, 'WEIGHT_HANDOVER': 40, 'MIN_SCORE_TO_PRINT': 60, 'MIN_TRADING_VALUE': BACKTEST_CONFIG['MIN_TRADING_VALUE']}

MICRO_FEATURE_FILE = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
DB_PATH = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"
RESULT_DIR = r"C:\jupyter_notebook\ai_twstock\backtest_micro_simulate\v1\result"
CACHE_DIR = r"C:\jupyter_notebook\ai_twstock\backtest_micro_simulate\v1\cache"

# =================================================================
# 核心邏輯
# =================================================================

def check_vcp_pattern(price_data, sorted_dates, idx):
    if idx < 60: return False, 0
    lookback_dates = sorted_dates[idx - 60 : idx + 1]
    prices = [price_data[d]['close'] for d in lookback_dates]
    segment_size = len(prices) // 3
    if segment_size < 5: return False, 0
    v1, v2, v3 = prices[:segment_size], prices[segment_size:segment_size*2], prices[segment_size*2:]
    def get_range(v): return (max(v) - min(v)) / min(v) if min(v) > 0 else 0
    r1, r2, r3 = get_range(v1), get_range(v2), get_range(v3)
    is_tightening = r1 > r2 and r2 > r3
    tightness_score = max(0, 100 * (1 - (r3 / 0.15))) if r3 < 0.15 else 0
    return is_tightening or (r1 > r3 * 2), min(100, tightness_score)

def check_handover_consolidation(price_data, sorted_dates, idx):
    if idx < 30: return False, 0
    lookback_dates = sorted_dates[idx - 10 : idx + 1]
    prices = [price_data[d]['close'] for d in lookback_dates]
    vols = [price_data[d].get('Trading_Volume', 0) for d in lookback_dates]
    max_p, min_p = max(prices), min(prices)
    price_range = (max_p - min_p) / min_p if min_p > 0 else 1.0
    is_consolidating = price_range <= 0.15
    long_vols = [price_data[sorted_dates[i]].get('Trading_Volume', 0) for i in range(idx - 30, idx - 10)]
    avg_long_vol = sum(long_vols) / len(long_vols) if long_vols else 1
    avg_recent_vol = sum(vols) / len(vols) if vols else 0
    vol_ratio = avg_recent_vol / avg_long_vol if avg_long_vol > 0 else 0
    handover_score = 0
    if is_consolidating:
        handover_score += max(0, (1 - (price_range / 0.15)) * 50)
        handover_score += min(50, (vol_ratio / 0.8) * 50)
    return is_consolidating and vol_ratio >= 0.7, handover_score

def calculate_momentum_score(details, weights=DEFAULT_WEIGHTS):
    score = 0
    score += (min(100, (details['gain'] / 0.05) * 100) if details['gain'] > 0 else 0) * weights['WEIGHT_GAIN'] / 100
    score += (min(100, (details['vol_ratio'] / 2.0) * 100)) * weights['WEIGHT_VOLUME'] / 100
    score += (min(100, details['foreign_days'] * 20)) * weights['WEIGHT_FOREIGN'] / 100
    score += (min(100, (details['sitc_ratio'] / 1.5) * 100)) * weights['WEIGHT_SITC'] / 100
    score += (details['vcp_score'] if details['vcp_ok'] else 0) * weights['WEIGHT_VCP'] / 100
    score += (details['handover_score'] if details['handover_ok'] else 0) * weights['WEIGHT_HANDOVER'] / 100
    return score

def calculate_dip_score(details):
    """
    抄底專用評分系統 (與動能評分平行)
    維度：跌幅深度、縮量程度、價格止跌強度
    """
    score = 0
    # 1. 跌幅貢獻 (跌越多分越高，上限 40)
    score += min(40, abs(details['prev_gain']) * 400)
    # 2. 縮量貢獻 (量縮越厲害分越高，上限 30)
    score += max(0, (1 - details['vol_ratio']) * 30)
    # 3. 止跌強度 (今日收紅棒加分)
    if details['is_red_candle']: score += 30
    return score

def calculate_day_trading_signal(sid, date, data, micro_features):
    stock_info = data.get(sid, {})
    report = stock_info.get('trading_daily_report', {}).get(date, {})
    buy_weighted = sell_weighted = buy_qty = sell_qty = 0.0
    has_data = False
    for key, is_buy in [('top_buyers', True), ('top_sellers', False)]:
        for t in report.get(key, []):
            bid = str(t.get('trader_id', '')).strip()
            if bid in micro_features:
                has_data = True
                stability = micro_features[bid].get('穩重指數', 0)
                qty = abs(t.get('net', 0))
                if is_buy: buy_weighted += (qty * stability / 100.0); buy_qty += qty
                else: sell_weighted += (qty * stability / 100.0); sell_qty += qty
    if not has_data: return {'type': None, 'strength': 0.0}
    net_score = buy_weighted - sell_weighted
    buy_idx = (buy_weighted / buy_qty) if buy_qty > 0 else 0
    sell_idx = (sell_weighted / sell_qty) if sell_qty > 0 else 0
    bs_diff = buy_idx - sell_idx
    if net_score > 20 and bs_diff > 0.1: return {'type': 'REVERSAL', 'strength': min(100, bs_diff * 80)}
    elif net_score < -20 and bs_diff < -0.1: return {'type': 'FOLLOW', 'strength': min(100, abs(bs_diff) * 60)}
    return {'type': None, 'strength': 0.0}

def check_price_volume_alignment(sid, date, data):
    stock_info = data.get(sid, {})
    price_info = stock_info.get('price', {}).get(date, {})
    top_buyers = stock_info.get('trading_daily_report', {}).get(date, {}).get('top_buyers', [])
    if not top_buyers or not price_info: return {'concentration': 0, 'is_aligned': False, 'gain': 0}
    total_vol = price_info.get('Trading_Volume', 0)
    if total_vol <= 0: return {'concentration': 0, 'is_aligned': False, 'gain': 0}
    concentration = sum([abs(t.get('net', 0)) for t in top_buyers[:5] if t.get('net', 0) > 0]) / total_vol
    open_p = price_info.get('open', 0)
    gain = (price_info.get('close', 0) - open_p) / open_p if open_p > 0 else 0
    is_aligned = not ((gain > 0.05 and concentration < 0.01) or (concentration > 0.20 and gain < -0.02))
    return {'concentration': concentration, 'is_aligned': is_aligned, 'gain': gain}

def calculate_day_trader_risk(sid, date, data, micro_features):
    top_buyers = data.get(sid, {}).get('trading_daily_report', {}).get(date, {}).get('top_buyers', [])
    if not top_buyers: return 0.0
    dt_vol = total_vol = 0
    for t in top_buyers[:10]:
        bid = str(t.get('trader_id', '')).strip()
        qty = abs(t.get('net', 0))
        total_vol += qty
        if bid in micro_features and micro_features[bid].get('穩重指數', 0) < -50: dt_vol += qty
    return dt_vol / total_vol if total_vol > 0 else 0

def check_uptrend_and_support(sid, date, data):
    """
    確認個股是否處於上行趨勢，並找出最近的支撐點
    """
    stock_info = data.get(sid, {})
    price_data = stock_info.get('price', {})
    sorted_dates = sorted(price_data.keys())
    if date not in sorted_dates: return False, 0
    idx = sorted_dates.index(date)
    if idx < 20: return False, 0
    
    lookback_20 = sorted_dates[idx-20:idx]
    prices_20 = [price_data[d]['close'] for d in lookback_20]
    ma20 = sum(prices_20) / 20
    curr_p = price_data[date]['close']
    
    # 支撐點：過去 20 天的最低收盤價
    support_p = min(prices_20)
    
    # 判定是否在支撐區 (價格距離 20日最低點 7% 以內)
    is_near_support = curr_p <= support_p * 1.07
    
    # 上行趨勢定義：價格在 MA20 之上 (聖盃用)
    is_uptrend = curr_p > ma20
    return is_uptrend, support_p, is_near_support

def check_broker_dumping(sid, date, data, micro_features):
    """
    檢查是否有「隔日沖」或「短線券商」在大量倒貨
    1. 賣方前五名中，是否有穩重指數極低 (< -50) 的券商
    2. 這些券商的賣出量是否佔今日成交量顯著比例
    """
    stock_info = data.get(sid, {})
    report = stock_info.get('trading_daily_report', {}).get(date, {})
    price_info = stock_info.get('price', {}).get(date, {})
    total_vol = price_info.get('Trading_Volume', 0)
    if total_vol <= 0: return False
    
    top_sellers = report.get('top_sellers', [])
    dumping_vol = 0
    for t in top_sellers[:5]:
        bid = str(t.get('trader_id', '')).strip()
        if bid in micro_features and micro_features[bid].get('穩重指數', 0) < -50:
            dumping_vol += abs(t.get('net', 0))
            
    # 如果短線券商賣壓超過今日成交量 10%，視為倒貨風險
    return (dumping_vol / total_vol) > 0.10

def decide_buy(momentum_score, dt_signal, risk_ratio, is_winner_buying, pv_alignment, mode='VOLATILITY', sid=None, date=None, data=None, micro_features=None):
    if not (sid and date and data): return False, None
    
    # 1. 大盤環境判定
    is_bull_market = True
    if HOLY_GRAIL_PARAMS.get('USE_MARKET_FILTER', False) and '0050' in data:
        p0050 = data['0050'].get('price', {})
        sorted_0050 = sorted(p0050.keys())
        if date in sorted_0050:
            idx_0050 = sorted_0050.index(date)
            if idx_0050 >= 60:
                def get_ma_0050(n, end_idx): return sum([p0050[sorted_0050[i]]['close'] for i in range(end_idx-n+1, end_idx+1)]) / n
                ma20 = get_ma_0050(20, idx_0050)
                ma60 = get_ma_0050(60, idx_0050)
                is_bull_market = p0050[date]['close'] > ma20 and ma20 > ma60

    # 2. 取得個股量價
    stock_info = data.get(sid, {})
    price_data = stock_info.get('price', {})
    sorted_dates = sorted(price_data.keys())
    if date not in sorted_dates: return False, None
    idx = sorted_dates.index(date)
    if idx < 20: return False, None
    
    prev_date = sorted_dates[idx-1]
    curr_p, prev_p = price_data[date], price_data[prev_date]
    prev_gain = (prev_p['close'] - prev_p['open']) / prev_p['open'] if prev_p['open'] > 0 else 0
    curr_vol = curr_p.get('Trading_Volume', 0)
    prev_vol = prev_p.get('Trading_Volume', 0)
    
    # 3. 模式判定邏輯 (受 PIPELINE_CONTROL['STRATEGY_SWITCH'] 控制)
    switches = PIPELINE_CONTROL['STRATEGY_SWITCH']
    
    # A. WASH_OUT_DIP (抄底模式)
    if switches.get('WASH_OUT_DIP', False):
        is_wash_out_base = prev_gain < -0.03 and curr_vol < prev_vol * 0.8
        if is_wash_out_base:
            is_red = curr_p['close'] > curr_p['open']
            is_uptrend, support_p, is_near_support = check_uptrend_and_support(sid, date, data)
            is_dumping = check_broker_dumping(sid, date, data, micro_features)
            if is_red and is_near_support and not is_dumping:
                dip_score = 0
                if PIPELINE_CONTROL.get('ENABLE_DIP_SCORE', True):
                    dip_details = {'prev_gain': prev_gain, 'vol_ratio': curr_vol/prev_vol, 'is_red_candle': is_red}
                    dip_score = calculate_dip_score(dip_details)
                return True, ('WASH_OUT_DIP', dip_score)

    # B. HOLY_GRAIL_BREAKOUT (聖盃模式)
    if switches.get('HOLY_GRAIL_BREAKOUT', False) and is_bull_market:
        is_vol_dry = curr_vol < (prev_vol * HOLY_GRAIL_PARAMS['VOL_DRY_RATIO'])
        prev_report = stock_info.get('trading_daily_report', {}).get(prev_date, {})
        curr_report = stock_info.get('trading_daily_report', {}).get(date, {})
        prev_top_b = prev_report.get('top_buyers', [])
        is_winner_locked = False
        if prev_top_b:
            winner_bid = str(prev_top_b[0].get('trader_id', '')).strip()
            winner_selling = sum([abs(ts.get('net', 0)) for ts in curr_report.get('top_sellers', [])[:5] if winner_bid == str(ts.get('trader_id', ''))])
            if winner_selling < (abs(prev_top_b[0].get('net', 0)) * HOLY_GRAIL_PARAMS['WINNER_LOCK_RATIO']):
                is_winner_locked = True
        if (prev_gain > HOLY_GRAIL_PARAMS['PREV_GAIN_THRESHOLD'] and is_vol_dry and is_winner_locked and
            curr_p['close'] >= prev_p['close'] * HOLY_GRAIL_PARAMS['PRICE_SUPPORT_LEVEL']):
            return True, ('HOLY_GRAIL_BREAKOUT', momentum_score)

    # C. VOLATILITY (波動率模式)
    if switches.get('VOLATILITY', False) and is_bull_market:
        if momentum_score > 75 and curr_p['close'] > curr_p['open']:
            return True, ('VOLATILITY', momentum_score)

    # D. SCALPING (極短線模式)
    if switches.get('SCALPING', False):
        dt_sig = calculate_day_trading_signal(sid, date, data, micro_features)
        if dt_sig['type'] == 'REVERSAL' and dt_sig['strength'] > 50:
            return True, ('SCALPING', dt_sig['strength'])

    return False, None

# =================================================================
# 資料載入與回測引擎
# =================================================================

def load_stock_info():
    names, industries = {}, {}
    path = r"C:\jupyter_notebook\ai_twstock\taiwan_stocks.csv"
    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
            code_col, name_col = df.columns[0], df.columns[1]
            ind_col = 'industry' if 'industry' in df.columns else None
            for _, row in df.iterrows():
                sid = str(row[code_col]).strip()
                names[sid] = str(row[name_col])
                if ind_col: industries[sid] = str(row[ind_col])
        except: pass
    return names, industries

def load_all_data(db_path, start_date):
    # 優先尋找最接近且包含 start_date 的快取檔案
    cache_files = [f for f in os.listdir(CACHE_DIR) if f.startswith("data_cache_") and f.endswith(".pkl")]
    best_cache = None
    if cache_files:
        valid_caches = []
        for f in cache_files:
            try:
                c_date = f.replace("data_cache_", "").replace(".pkl", "")
                if c_date <= start_date: valid_caches.append((c_date, f))
            except: continue
        if valid_caches: best_cache = max(valid_caches, key=lambda x: x[0])[1]

    cache_file = os.path.join(CACHE_DIR, best_cache if best_cache else f"data_cache_{start_date}.pkl")
    if os.path.exists(cache_file):
        print(f"正在從快取載入資料: {cache_file}...")
        t_start = time.time()
        with open(cache_file, 'rb') as f: data = pickle.load(f)
        print(f"[DEBUG] 快取載入完成，耗時 {time.time()-t_start:.2f}s, RAM: {get_ram_usage():.1f} MB")
        return data

    t0 = time.time()
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row; cursor = conn.cursor(); data = {}
    print(f"正在從 SQL 載入全市場資料 (起始日: {start_date})...")
    cursor.execute("SELECT * FROM daily_prices WHERE date >= ?", (start_date,))
    for row in cursor.fetchall():
        sid, date = row['stock_id'], row['date']
        if sid not in data: data[sid] = {'price': {}, 'institutional': {}, 'trading_daily_report': {}}
        data[sid]['price'][date] = {'open': row['open'], 'max': row['high'], 'min': row['low'], 'close': row['close'], 'Trading_Volume': row['volume']}
        data[sid]['institutional'][date] = {'Foreign_Investor': {'buy': row['foreign_buy'], 'sell': 0}, 'Investment_Trust': {'buy': row['sitc_buy'], 'sell': 0}}
    cursor.execute("SELECT * FROM broker_details WHERE date >= ?", (start_date,))
    for row in cursor.fetchall():
        sid, date = row['stock_id'], row['date']
        if sid not in data: continue
        if date not in data[sid]['trading_daily_report']: data[sid]['trading_daily_report'][date] = {'top_buyers': [], 'top_sellers': []}
        item = {'trader_id': str(row['trader_id']), 'trader_name': row['trader_name'], 'net': row['net_qty'] if row['is_buy'] else -row['net_qty'], 'avg_p': row['avg_price']}
        if row['is_buy']: data[sid]['trading_daily_report'][date]['top_buyers'].append(item)
        else: data[sid]['trading_daily_report'][date]['top_sellers'].append(item)
    conn.close()
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_file, 'wb') as f: pickle.dump(data, f)
    print(f"[DEBUG] 資料載入與快取建立總耗時: {time.time()-t0:.2f}s, 目前 RAM: {get_ram_usage():.1f} MB")
    return data

def run_backtest():
    start_date = "2026-03-01"
    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    data_date_str = (start_date_obj - timedelta(days=90)).strftime("%Y-%m-%d")
    data = load_all_data(DB_PATH, data_date_str)
    if not data: return
    with open(MICRO_FEATURE_FILE, 'r', encoding='utf-8') as f:
        micro_features = {str(item['id']).strip(): item for item in json.load(f)}
    stock_names, stock_industries = load_stock_info()
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    start_idx = all_dates.index(next(d for d in all_dates if d >= start_date))
    cash = BACKTEST_CONFIG['STARTING_CASH']; portfolio = {}; transactions = []; top_n = BACKTEST_CONFIG['TOP_N']
    
    print(f"開始回測: {all_dates[start_idx]} -> {all_dates[-1]}")
    for idx in range(start_idx, len(all_dates)):
        t_day_start = time.time()
        current_date = all_dates[idx]
        to_sell_list = []
        for sid, pos in list(portfolio.items()):
            if current_date not in data[sid]['price']: continue
            curr_p = data[sid]['price'][current_date]['close']
            gain = (curr_p - pos['avg_price']) / pos['avg_price']
            if 'max_gain' not in pos or gain > pos['max_gain']: pos['max_gain'] = gain
            mode = pos['mode']; params = STRATEGY_MODES.get(mode, STRATEGY_MODES['HOLY_GRAIL_BREAKOUT'])
            sell_reason = None; sell_ratio = 1.0
            if mode in ['VOLATILITY', 'LOW_ENTRY', 'HOLY_GRAIL_BREAKOUT'] and not pos.get('half_sold') and gain >= params.get('PARTIAL_EXIT_GAIN', 0.10):
                sell_reason = f"分批減碼({mode}) (+{gain:.1%})"; sell_ratio = 0.5; pos['half_sold'] = True
            if not sell_reason:
                trailing_limit = params.get('TRAILING_STOP_NORMAL', 0.08)
                if gain > 0.30: trailing_limit = params.get('TRAILING_STOP_TIGHT', 0.04)
                if gain < (pos['max_gain'] - trailing_limit): sell_reason = f"移動停損({mode})"
                elif gain <= params['STOP_LOSS']: sell_reason = f"停損({mode})"
                elif pos.get('max_gain', 0) > params.get('BREAK_EVEN_TRIGGER', 0.05) and gain < 0.02: sell_reason = f"保本({mode})"
            max_days = params.get('HOLD_DAYS', 10)
            if mode == 'VOLATILITY' and pos.get('half_sold'): max_days = 30
            if not sell_reason and (idx - all_dates.index(pos['buy_date'])) >= max_days: sell_reason = f"到期({mode})"
            if sell_reason:
                qty = int(pos['shares'] * sell_ratio); cash += qty * curr_p * 0.998
                transactions.append({'date': current_date, 'sid': sid, 'action': 'SELL', 'gain': gain, 'reason': sell_reason, 'price': curr_p, 'mode': mode})
                if qty >= pos['shares']: to_sell_list.append(sid)
                else: pos['shares'] -= qty
        for sid in to_sell_list: del portfolio[sid]

        if len(portfolio) < top_n:
            analysis_date = all_dates[idx-1]
            sector_scores = defaultdict(list)
            for sid, details in data.items():
                if analysis_date not in details['price']: continue
                p_data = details['price']; sorted_d = sorted(p_data.keys()); a_idx = sorted_d.index(analysis_date)
                if a_idx < 20: continue
                start_p = p_data[sorted_d[a_idx-20]]['close']
                if start_p <= 0: continue
                gain_20 = (p_data[analysis_date]['close'] - start_p) / start_p
                ind = stock_industries.get(sid, "其他")
                if ind != "其他": sector_scores[ind].append(gain_20)
            avg_sector_gain = {ind: sum(gains)/len(gains) for ind, gains in sector_scores.items() if len(gains) >= 5}
            top_sector_names = [x[0] for x in sorted(avg_sector_gain.items(), key=lambda x: x[1], reverse=True)[:3]]
            candidates = []
            for sid, details in data.items():
                if sid in portfolio or analysis_date not in details['price'] or current_date not in details['price']: continue
                if stock_industries.get(sid) not in top_sector_names: continue
                
                p_data = details['price']; sorted_d = sorted(p_data.keys()); a_idx = sorted_d.index(analysis_date)
                start_p = p_data[sorted_d[a_idx-20]]['close']
                gain_20 = (p_data[analysis_date]['close'] - start_p) / start_p if start_p > 0 else 0
                vcp_ok, vcp_s = check_vcp_pattern(p_data, sorted_d, a_idx); hand_ok, hand_s = check_handover_consolidation(p_data, sorted_d, a_idx)
                inst = details['institutional'].get(analysis_date, {}); f_net = inst.get('Foreign_Investor', {}).get('buy', 0); s_net = inst.get('Investment_Trust', {}).get('buy', 0)
                mom_details = {'gain': gain_20, 'vol_ratio': 1.5, 'foreign_days': 3 if f_net > 0 else 0, 'sitc_ratio': 1.2 if s_net > 0 else 0, 'vcp_ok': vcp_ok, 'vcp_score': vcp_s, 'handover_ok': hand_ok, 'handover_score': hand_s}
                score = calculate_momentum_score(mom_details); dt_sig = calculate_day_trading_signal(sid, analysis_date, data, micro_features); risk_ratio = calculate_day_trader_risk(sid, analysis_date, data, micro_features); pv_align = check_price_volume_alignment(sid, analysis_date, data)
                is_winner = False; top_b_list = details['trading_daily_report'].get(analysis_date, {}).get('top_buyers', [])
                if top_b_list:
                    bid = str(top_b_list[0].get('trader_id','')).strip()
                    if bid in micro_features and micro_features[bid].get('穩重指數', 0) > 15: is_winner = True
                
                # 執行買入判定 (回傳格式改為 (True, (模式, 分數)))
                buy, res = decide_buy(score, dt_sig, risk_ratio, is_winner, pv_align, mode='HOLY_GRAIL_BREAKOUT', sid=sid, date=analysis_date, data=data, micro_features=micro_features)
                if buy:
                    strat, final_score = res
                    candidates.append({'sid': sid, 'score': final_score, 'mode': strat, 'price': p_data[current_date]['open'], 'strategy': strat})
            candidates.sort(key=lambda x: x['score'], reverse=True)
            for cand in candidates[:top_n - len(portfolio)]:
                buy_price = cand['price']
                if buy_price <= 0: continue
                num_to_buy = top_n - len(portfolio)
                shares = int((cash / num_to_buy * 0.95) / buy_price / 1000) * 1000
                if shares >= 1000:
                    cost = shares * buy_price * 1.002
                    if cash >= cost:
                        cash -= cost
                        portfolio[cand['sid']] = {'shares': shares, 'avg_price': buy_price, 'buy_date': current_date, 'mode': cand['mode'], 'strategy': cand.get('strategy', 'MOMENTUM')}
                        transactions.append({'date': current_date, 'sid': cand['sid'], 'action': 'BUY', 'price': buy_price, 'mode': cand['mode'], 'strategy': cand.get('strategy', 'MOMENTUM')})
        if idx % 20 == 0: print(f"[{current_date}] 每日演算耗時: {time.time()-t_day_start:.2f}s, RAM: {get_ram_usage():.1f} MB")

    final_v = cash + sum(p['shares'] * data[s]['price'][all_dates[-1]]['close'] for s, p in portfolio.items() if all_dates[-1] in data[s]['price'])
    all_sells = [t for t in transactions if t['action'] == 'SELL']
    mode_stats = {}
    for m in STRATEGY_MODES.keys():
        m_sells = [t for t in all_sells if t.get('mode') == m]
        m_gains = [t['gain'] for t in m_sells]
        mode_stats[m] = {'count': len(m_sells), 'win_rate': len([g for g in m_gains if g > 0]) / len(m_gains) if m_gains else 0, 'avg_return': sum(m_gains) / len(m_gains) if m_gains else 0}
    print(f"\n回測結束! 最終價值: {final_v:,.0f} (報酬率: {(final_v-BACKTEST_CONFIG['STARTING_CASH'])/BACKTEST_CONFIG['STARTING_CASH']:.1%})")
    print("\n" + "="*60); print(f"{'模式':<20} | {'交易次數':<8} | {'勝率':<8} | {'平均報酬':<10}"); print("-" * 60)
    for m, s in mode_stats.items(): print(f"{m:<20} | {s['count']:>8} | {s['win_rate']:>8.1%} | {s['avg_return']:>10.2%}")
    print("="*60)
    os.makedirs(RESULT_DIR, exist_ok=True); log_path = os.path.join(RESULT_DIR, "transaction_log.txt")
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f"=== 交易流水帳 (聖盃模式 4.0 終極精準版) ===\n"); f.write(f"起始資金: {BACKTEST_CONFIG['STARTING_CASH']:,} | 最終價值: {final_v:,.0f}\n"); f.write("-" * 80 + "\n")
        for t in transactions:
            gain_str = f"{t.get('gain', 0):.1%}" if t['action'] == 'SELL' else "-"
            f.write(f"{t['date']:<12} | {t['sid']:<6} | {t['action']:<4} | {t.get('price', 0):<8.2f} | {gain_str:<8} | {t.get('reason', ''):<20}\n")

if __name__ == "__main__":
    run_backtest()
