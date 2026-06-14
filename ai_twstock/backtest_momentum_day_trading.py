#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
backtest_momentum_day_trading.py
聖盃模式 4.0 終極精準版 (效能監控與邏輯修復)
目標：恢復 60%+ 報酬率，並實現秒級載入
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

# 2026 年最強參數預設值 (60.6% 報酬率版本)
HOLY_GRAIL_PARAMS = {
    'PREV_GAIN_THRESHOLD': 0.05, 
    'VOL_DRY_RATIO': 0.65, 
    'WINNER_LOCK_RATIO': 0.15, 
    'PRICE_SUPPORT_LEVEL': 0.97,
    'USE_MARKET_FILTER': True
}
STRATEGY_MODES = {
    'HOLY_GRAIL_BREAKOUT': {
        'STOP_LOSS': -0.05, 
        'TAKE_PROFIT': 9.99, 
        'BREAK_EVEN_TRIGGER': 0.06, 
        'HOLD_DAYS': 20,
        'PARTIAL_EXIT_GAIN': 0.10,
        'TRAILING_STOP_NORMAL': 0.08
    }
}
BACKTEST_CONFIG = {'STARTING_CASH': 2000000, 'TOP_N': 5, 'MIN_TRADING_VALUE': 30000000}

try:
    from holy_grail_config import HOLY_GRAIL_PARAMS as HGP, STRATEGY_MODES as SM, BACKTEST_CONFIG as BC
    HOLY_GRAIL_PARAMS.update(HGP)
    STRATEGY_MODES.update(SM)
    BACKTEST_CONFIG.update(BC)
except ImportError:
    pass

MICRO_FEATURE_FILE = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
DB_PATH = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"
RESULT_DIR = r"C:\jupyter_notebook\ai_twstock\backtest_micro_simulate\v1\result"
CACHE_DIR = r"C:\jupyter_notebook\ai_twstock\backtest_micro_simulate\v1\cache"

# =================================================================
# 核心邏輯
# =================================================================

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
    if net_score > 20 and bs_diff > 0.1:
        return {'type': 'REVERSAL', 'strength': min(100, bs_diff * 80)}
    elif net_score < -20 and bs_diff < -0.1:
        return {'type': 'FOLLOW', 'strength': min(100, abs(bs_diff) * 60)}
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

def decide_buy(momentum_score, dt_signal, risk_ratio, is_winner_buying, pv_alignment, mode='VOLATILITY', sid=None, date=None, data=None):
    """
    聖盃模式 4.0：恢復最強獲利邏輯
    """
    if sid and date and data:
        # 0. 大盤防禦開關
        if HOLY_GRAIL_PARAMS.get('USE_MARKET_FILTER', False):
            if '0050' in data:
                p0050 = data['0050'].get('price', {})
                sorted_0050 = sorted(p0050.keys())
                if date in sorted_0050:
                    idx_0050 = sorted_0050.index(date)
                    if idx_0050 >= 20:
                        def get_ma_0050(n, end_idx):
                            return sum([p0050[sorted_0050[i]]['close'] for i in range(end_idx-n+1, end_idx+1)]) / n
                        ma20 = get_ma_0050(20, idx_0050)
                        if p0050[date]['close'] < ma20:
                            return False, None # 大盤轉弱，強制空倉

        stock_info = data.get(sid, {})
        price_data = stock_info.get('price', {})
        sorted_dates = sorted(price_data.keys())
        idx = sorted_dates.index(date)
        if idx < 1: return False, None
        
        prev_date = sorted_dates[idx-1]
        curr_p, prev_p = price_data[date], price_data[prev_date]
        
        # 1. 昨日特徵：大漲突破
        prev_gain = (prev_p['close'] - prev_p['open']) / prev_p['open'] if prev_p['open'] > 0 else 0
        
        # 2. 今日特徵：縮量回測
        is_vol_dry = curr_p.get('Trading_Volume', 0) < (prev_p.get('Trading_Volume', 0) * HOLY_GRAIL_PARAMS['VOL_DRY_RATIO'])
        
        # 3. 籌碼鎖定：昨日買一贏家今日沒跑
        prev_report = stock_info.get('trading_daily_report', {}).get(prev_date, {})
        curr_report = stock_info.get('trading_daily_report', {}).get(date, {})
        prev_top_b = prev_report.get('top_buyers', [])
        
        is_winner_locked = False
        if prev_top_b:
            winner_bid = str(prev_top_b[0].get('trader_id', '')).strip()
            curr_top_s = curr_report.get('top_sellers', [])
            winner_selling = sum([abs(ts.get('net', 0)) for ts in curr_top_s[:5] if winner_bid == str(ts.get('trader_id', ''))])
            
            if winner_selling < (abs(prev_top_b[0].get('net', 0)) * HOLY_GRAIL_PARAMS['WINNER_LOCK_RATIO']):
                is_winner_locked = True

        # 4. 決策
        if (prev_gain > HOLY_GRAIL_PARAMS['PREV_GAIN_THRESHOLD'] and 
            is_vol_dry and is_winner_locked and 
            curr_p['close'] >= prev_p['close'] * HOLY_GRAIL_PARAMS['PRICE_SUPPORT_LEVEL']):
            return True, 'HOLY_GRAIL_BREAKOUT'

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
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, f"data_cache_{start_date}.pkl")
    
    # 智慧快取檢查：如果 SQL 資料庫比快取檔新，則判定快取過期
    is_cache_valid = False
    if os.path.exists(cache_file) and os.path.exists(db_path):
        cache_time = os.path.getmtime(cache_file)
        db_time = os.path.getmtime(db_path)
        if cache_time > db_time:
            is_cache_valid = True
        else:
            print("[INFO] 偵測到資料庫已更新，將重新從 SQL 載入並建立新快取...")

    if is_cache_valid:
        print(f"正在從快取載入資料: {cache_file}...")
        t_start = time.time()
        with open(cache_file, 'rb') as f:
            data = pickle.load(f)
        print(f"[DEBUG] 快取載入完成，耗時 {time.time()-t_start:.2f}s, 目前 RAM: {get_ram_usage():.1f} MB")
        return data

    t_total_start = time.time()
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row; cursor = conn.cursor(); data = {}
    print(f"正在從 SQL 載入全市場資料 (起始日: {start_date})...")
    
    t0 = time.time()
    cursor.execute("SELECT * FROM daily_prices WHERE date >= ?", (start_date,))
    rows_price = cursor.fetchall()
    print(f"[DEBUG] SQL 價格讀取耗時: {time.time()-t0:.2f}s")
    
    for row in rows_price:
        sid, date = row['stock_id'], row['date']
        if sid not in data: data[sid] = {'price': {}, 'institutional': {}, 'trading_daily_report': {}}
        data[sid]['price'][date] = {'open': row['open'], 'max': row['high'], 'min': row['low'], 'close': row['close'], 'Trading_Volume': row['volume']}
        data[sid]['institutional'][date] = {'Foreign_Investor': {'buy': row['foreign_buy'], 'sell': 0}, 'Investment_Trust': {'buy': row['sitc_buy'], 'sell': 0}}
    
    t1 = time.time()
    cursor.execute("SELECT * FROM broker_details WHERE date >= ?", (start_date,))
    rows_broker = cursor.fetchall()
    print(f"[DEBUG] SQL 分點讀取耗時: {time.time()-t1:.2f}s")
    
    for row in rows_broker:
        sid, date = row['stock_id'], row['date']
        if sid not in data: continue
        if date not in data[sid]['trading_daily_report']: data[sid]['trading_daily_report'][date] = {'top_buyers': [], 'top_sellers': []}
        item = {'trader_id': str(row['trader_id']), 'trader_name': row['trader_name'], 'net': row['net_qty'] if row['is_buy'] else -row['net_qty'], 'avg_p': row['avg_price']}
        if row['is_buy']: data[sid]['trading_daily_report'][date]['top_buyers'].append(item)
        else: data[sid]['trading_daily_report'][date]['top_sellers'].append(item)
    conn.close()
    
    t_save = time.time()
    with open(cache_file, 'wb') as f: pickle.dump(data, f)
    print(f"[DEBUG] 快取建立耗時: {time.time()-t_save:.2f}s")
    print(f"[DEBUG] 總載入耗時: {time.time()-t_total_start:.2f}s, 目前 RAM: {get_ram_usage():.1f} MB")
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
    
    cash = BACKTEST_CONFIG['STARTING_CASH']; portfolio = {}; transactions = []
    top_n = BACKTEST_CONFIG['TOP_N']
    
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
            
            if not pos.get('half_sold') and gain >= params.get('PARTIAL_EXIT_GAIN', 0.10):
                sell_reason = f"分批減碼({mode}) (+{gain:.1%})"; sell_ratio = 0.5; pos['half_sold'] = True
            
            if not sell_reason:
                trailing_limit = params.get('TRAILING_STOP_NORMAL', 0.08)
                if gain < (pos['max_gain'] - trailing_limit): sell_reason = f"移動停損({mode})"
                elif gain <= params['STOP_LOSS']: sell_reason = f"停損({mode})"
                elif pos.get('max_gain', 0) > params.get('BREAK_EVEN_TRIGGER', 0.06) and gain < 0.02: sell_reason = f"保本({mode})"
            
            max_days = params.get('HOLD_DAYS', 20)
            if not sell_reason and (idx - all_dates.index(pos['buy_date'])) >= max_days: sell_reason = f"到期({mode})"
            
            if sell_reason:
                qty = int(pos['shares'] * sell_ratio)
                if qty < 1000 or sell_ratio == 1.0: qty = pos['shares']
                cash += qty * curr_p * 0.998
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
                pv_align = check_price_volume_alignment(sid, analysis_date, data)
                
                buy, strat = decide_buy(0, None, 0, True, pv_align, mode='HOLY_GRAIL_BREAKOUT', sid=sid, date=analysis_date, data=data)
                if buy:
                    candidates.append({'sid': sid, 'mode': 'HOLY_GRAIL_BREAKOUT', 'price': p_data[current_date]['open']})
            
            candidates.sort(key=lambda x: x.get('score', 0), reverse=True)
            for cand in candidates[:top_n - len(portfolio)]:
                buy_price = cand['price']
                if buy_price <= 0: continue
                num_to_buy = top_n - len(portfolio)
                shares = int((cash / num_to_buy * 0.95) / buy_price / 1000) * 1000
                if shares >= 1000:
                    cost = shares * buy_price * 1.002
                    if cash >= cost:
                        cash -= cost
                        portfolio[cand['sid']] = {'shares': shares, 'avg_price': buy_price, 'buy_date': current_date, 'mode': cand['mode']}
                        transactions.append({'date': current_date, 'sid': cand['sid'], 'action': 'BUY', 'price': buy_price, 'mode': cand['mode']})
        if idx % 20 == 0: print(f"[{current_date}] 每日演算耗時: {time.time()-t_day_start:.2f}s, RAM: {get_ram_usage():.1f} MB")

    final_v = cash + sum(p['shares'] * data[s]['price'][all_dates[-1]]['close'] for s, p in portfolio.items() if all_dates[-1] in data[s]['price'])
    all_sells = [t for t in transactions if t['action'] == 'SELL']
    mode_stats = {}
    for m in STRATEGY_MODES.keys():
        m_sells = [t for t in all_sells if t.get('mode') == m]
        m_gains = [t['gain'] for t in m_sells]
        mode_stats[m] = {'count': len(m_sells), 'win_rate': len([g for g in m_gains if g > 0]) / len(m_gains) if m_gains else 0, 'avg_return': sum(m_gains) / len(m_gains) if m_gains else 0}

    print(f"\n回測結束! 最終價值: {final_v:,.0f} (報酬率: {(final_v-BACKTEST_CONFIG['STARTING_CASH'])/BACKTEST_CONFIG['STARTING_CASH']:.1%})")
    print("\n" + "="*60)
    print(f"{'模式':<20} | {'交易次數':<8} | {'勝率':<8} | {'平均報酬':<10}")
    print("-" * 60)
    for m, s in mode_stats.items():
        print(f"{m:<20} | {s['count']:>8} | {s['win_rate']:>8.1%} | {s['avg_return']:>10.2%}")
    print("="*60)

if __name__ == "__main__":
    run_backtest()
