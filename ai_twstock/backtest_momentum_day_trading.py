#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
backtest_momentum_day_trading.py
聖盃模式 4.0 終極精準版 (含大盤防禦開關)
目標：在多頭環境下極大化獲利，超越 0050
"""

import json
import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict

# 嘗試設定輸出編碼
try:
    if sys.stdout.encoding != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

# =================================================================
# 載入外部設定 (確保預設值為 2026 年最強版本)
# =================================================================
sys.path.append(os.path.join(os.path.dirname(__file__), 'backtest_micro_simulate', 'v1', 'config'))

# 2026 年最強參數預設值
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
        'HOLD_DAYS': 20
    },
    'VOLATILITY': {'STOP_LOSS': -0.08, 'TAKE_PROFIT': 9.99, 'BREAK_EVEN_TRIGGER': 0.05, 'HOLD_DAYS': 10},
    'SCALPING': {'STOP_LOSS': -0.03, 'TAKE_PROFIT': 0.06, 'BREAK_EVEN_TRIGGER': 0.03, 'HOLD_DAYS': 1},
    'WASH_OUT_DIP': {'STOP_LOSS': -0.03, 'TAKE_PROFIT': 0.05, 'HOLD_DAYS': 2},
    'LOW_ENTRY': {'STOP_LOSS': -0.05, 'TAKE_PROFIT': 9.99, 'BREAK_EVEN_TRIGGER': 0.08, 'HOLD_DAYS': 40, 'MAX_MOMENTUM': 45}
}
BACKTEST_CONFIG = {'STARTING_CASH': 2000000, 'TOP_N': 8, 'MIN_TRADING_VALUE': 30000000}

try:
    from holy_grail_config import HOLY_GRAIL_PARAMS as HGP, STRATEGY_MODES as SM, BACKTEST_CONFIG as BC
    HOLY_GRAIL_PARAMS.update(HGP)
    STRATEGY_MODES.update(SM)
    BACKTEST_CONFIG.update(BC)
except ImportError:
    pass

DEFAULT_WEIGHTS = {
    'WEIGHT_GAIN': 40, 'WEIGHT_VOLUME': 10, 'WEIGHT_FOREIGN': 10,
    'WEIGHT_SITC': 10, 'WEIGHT_VCP': 10, 'WEIGHT_BREAKOUT': 10,
    'WEIGHT_HANDOVER': 40, 'MIN_SCORE_TO_PRINT': 60, 'MIN_TRADING_VALUE': BACKTEST_CONFIG['MIN_TRADING_VALUE'],
}

MICRO_FEATURE_FILE = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
DB_PATH = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"
RESULT_DIR = r"C:\jupyter_notebook\ai_twstock\backtest_micro_simulate\v1\result"

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

def calculate_day_trading_signal(sid, date, data, micro_features):
    stock_info = data.get(sid, {})
    report = stock_info.get('trading_daily_report', {}).get(date, {})
    buy_weighted = sell_weighted = buy_qty = sell_qty = 0.0
    has_data = False
    for key, is_buy in [('top_buyers', True), ('top_sellers', False)]:
        for t in report.get(key, []):
            bid = str(t.get('trader', '')).split('/')[-1].strip()
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

def calculate_day_trader_risk(sid, date, data, micro_features):
    top_buyers = data.get(sid, {}).get('trading_daily_report', {}).get(date, {}).get('top_buyers', [])
    if not top_buyers: return 0.0
    dt_vol = total_vol = 0
    for t in top_buyers[:10]:
        bid = str(t.get('trader', '')).split('/')[-1].strip()
        qty = abs(t.get('net', 0))
        total_vol += qty
        if bid in micro_features and micro_features[bid].get('穩重指數', 0) < -50: dt_vol += qty
    return dt_vol / total_vol if total_vol > 0 else 0

def decide_buy(momentum_score, dt_signal, risk_ratio, is_winner_buying, pv_alignment, mode='VOLATILITY', sid=None, date=None, data=None):
    """
    聖盃模式 4.0：贏家鎖籌回測版 (含大盤防禦開關)
    """
    if sid and date and data:
        # 0. 大盤防禦開關
        if HOLY_GRAIL_PARAMS.get('USE_MARKET_FILTER', False):
            if '0050' in data:
                p0050 = data['0050'].get('price', {})
                sorted_dates = sorted(p0050.keys())
                if date in sorted_dates:
                    idx = sorted_dates.index(date)
                    if idx >= 20:
                        def get_ma(n, end_idx):
                            return sum([p0050[sorted_dates[i]]['close'] for i in range(end_idx-n+1, end_idx+1)]) / n
                        ma10, ma20 = get_ma(10, idx), get_ma(20, idx)
                        # 強制要求大盤處於主升段 (10MA > 20MA 且 價格 > 10MA)
                        if not (p0050[date]['close'] > ma10 > ma20):
                            return False, None # 大盤非強勢多頭，強制空倉

        stock_info = data.get(sid, {})
        price_data = stock_info.get('price', {})
        sorted_dates = sorted(price_data.keys())
        if date not in sorted_dates: return False, None
        idx = sorted_dates.index(date)
        if idx < 1: return False, None
        
        prev_date = sorted_dates[idx-1]
        curr_p = price_data[date]
        prev_p = price_data[prev_date]
        
        # 1. 昨日特徵：大漲突破
        prev_gain = (prev_p['close'] - prev_p['open']) / prev_p['open'] if prev_p['open'] > 0 else 0
        
        # 2. 今日特徵：縮量回測
        curr_vol = curr_p.get('Trading_Volume', 0)
        prev_vol = prev_p.get('Trading_Volume', 0)
        is_vol_dry = curr_vol < (prev_vol * HOLY_GRAIL_PARAMS['VOL_DRY_RATIO'])
        
        # 3. 籌碼鎖定：昨日買一贏家今日沒跑
        prev_report = stock_info.get('trading_daily_report', {}).get(prev_date, {})
        curr_report = stock_info.get('trading_daily_report', {}).get(date, {})
        prev_top_b = prev_report.get('top_buyers', [])
        
        is_winner_locked = False
        if prev_top_b:
            winner_bid = str(prev_top_b[0].get('trader', '')).split('/')[-1].strip()
            curr_top_s = curr_report.get('top_sellers', [])
            winner_selling = 0
            for ts in curr_top_s[:5]:
                if winner_bid in str(ts.get('trader', '')):
                    winner_selling = abs(ts.get('net', 0))
            
            if winner_selling < (abs(prev_top_b[0].get('net', 0)) * HOLY_GRAIL_PARAMS['WINNER_LOCK_RATIO']):
                is_winner_locked = True

        # 4. 決策：昨日大漲 + 今日縮量 + 贏家鎖籌
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
        item = {'trader': f"{row['trader_name']}/{row['trader_id']}", 'net': row['net_qty'] if row['is_buy'] else -row['net_qty'], 'avg_p': row['avg_price']}
        if row['is_buy']: data[sid]['trading_daily_report'][date]['top_buyers'].append(item)
        else: data[sid]['trading_daily_report'][date]['top_sellers'].append(item)
    conn.close(); return data

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
    
    cash = BACKTEST_CONFIG['STARTING_CASH']
    portfolio = {}; transactions = []
    top_n = BACKTEST_CONFIG['TOP_N']
    
    print(f"開始回測: {all_dates[start_idx]} -> {all_dates[-1]}")
    for idx in range(start_idx, len(all_dates)):
        current_date = all_dates[idx]
        to_sell_list = []
        for sid, pos in list(portfolio.items()):
            if current_date not in data[sid]['price']: continue
            curr_p = data[sid]['price'][current_date]['close']
            gain = (curr_p - pos['avg_price']) / pos['avg_price']
            if 'max_gain' not in pos or gain > pos['max_gain']: pos['max_gain'] = gain
            
            mode = pos['mode']; params = STRATEGY_MODES.get(mode, STRATEGY_MODES['HOLY_GRAIL_BREAKOUT'])
            sell_reason = None; sell_ratio = 1.0
            
            if mode in ['VOLATILITY', 'LOW_ENTRY', 'HOLY_GRAIL_BREAKOUT'] and not pos.get('half_sold') and gain >= 0.10:
                sell_reason = f"分批減碼({mode}) (+10%)"; sell_ratio = 0.5; pos['half_sold'] = True
            
            if not sell_reason:
                trailing_limit = 0.08
                if gain > 0.30: trailing_limit = 0.05
                if gain > 0.50: trailing_limit = 0.03
                if gain < (pos['max_gain'] - trailing_limit): sell_reason = f"移動停損({mode})"
                elif gain <= params['STOP_LOSS']: sell_reason = f"停損({mode})"
                elif pos.get('max_gain', 0) > params.get('BREAK_EVEN_TRIGGER', 0.05) and gain < 0.02: sell_reason = f"保本({mode})"
            
            max_days = params.get('HOLD_DAYS', 10)
            if mode == 'VOLATILITY' and pos.get('half_sold'): max_days = 30
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
                vcp_ok, vcp_s = check_vcp_pattern(p_data, sorted_d, a_idx)
                hand_ok, hand_s = check_handover_consolidation(p_data, sorted_d, a_idx)
                inst = details['institutional'].get(analysis_date, {})
                f_net = inst.get('Foreign_Investor', {}).get('buy', 0)
                s_net = inst.get('Investment_Trust', {}).get('buy', 0)
                mom_details = {'gain': gain_20, 'vol_ratio': 1.5, 'foreign_days': 3 if f_net > 0 else 0, 'sitc_ratio': 1.2 if s_net > 0 else 0, 'vcp_ok': vcp_ok, 'vcp_score': vcp_s, 'handover_ok': hand_ok, 'handover_score': hand_s}
                score = calculate_momentum_score(mom_details)
                dt_sig = calculate_day_trading_signal(sid, analysis_date, data, micro_features)
                risk_ratio = calculate_day_trader_risk(sid, analysis_date, data, micro_features)
                pv_align = check_price_volume_alignment(sid, analysis_date, data)
                
                is_winner = False
                top_b_list = details['trading_daily_report'].get(analysis_date, {}).get('top_buyers', [])
                if top_b_list and str(top_b_list[0].get('trader','')).split('/')[-1] in micro_features:
                    if micro_features[str(top_b_list[0].get('trader','')).split('/')[-1]].get('穩重指數', 0) > 15: is_winner = True
                
                buy, strat = decide_buy(score, dt_sig, risk_ratio, is_winner, pv_align, mode='HOLY_GRAIL_BREAKOUT', sid=sid, date=analysis_date, data=data)
                if buy:
                    candidates.append({'sid': sid, 'score': score, 'mode': 'HOLY_GRAIL_BREAKOUT', 'price': p_data[current_date]['open'], 'strategy': strat})
            
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
    
    os.makedirs(RESULT_DIR, exist_ok=True)
    log_path = os.path.join(RESULT_DIR, "transaction_log.txt")
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f"=== 交易流水帳 (聖盃模式 4.0 終極精準版) ===\n")
        f.write(f"起始資金: {BACKTEST_CONFIG['STARTING_CASH']:,} | 最終價值: {final_v:,.0f}\n")
        f.write("-" * 80 + "\n")
        for t in transactions:
            gain_str = f"{t.get('gain', 0):.1%}" if t['action'] == 'SELL' else "-"
            f.write(f"{t['date']:<12} | {t['sid']:<6} | {t['action']:<4} | {t.get('price', 0):<8.2f} | {gain_str:<8} | {t.get('reason', ''):<20}\n")

if __name__ == "__main__":
    run_backtest()
