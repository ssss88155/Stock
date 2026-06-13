#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
backtest_momentum_day_trading.py
三模式版：VOLATILITY, SCALPING, LOW_ENTRY (低位潛伏)
目標：超越 0050 漲幅 (25%+)
"""

import json
import os
import sys
import sqlite3
import pandas as pd
from datetime import datetime
from collections import defaultdict

# 嘗試設定輸出編碼
try:
    if sys.stdout.encoding != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

# =================================================================
# 策略參數與權重
# =================================================================
DEFAULT_WEIGHTS = {
    'WEIGHT_GAIN': 40, 'WEIGHT_VOLUME': 10, 'WEIGHT_FOREIGN': 10,
    'WEIGHT_SITC': 10, 'WEIGHT_VCP': 10, 'WEIGHT_BREAKOUT': 10,
    'WEIGHT_HANDOVER': 40, 'MIN_SCORE_TO_PRINT': 60, 'MIN_TRADING_VALUE': 20000000,
}

# 三模式設定
STRATEGY_MODES = {
    'VOLATILITY': {
        'RISK_LIMIT': 0.60,
        'MIN_CONCENTRATION': 0.01,
        'STOP_LOSS': -0.08,
        'TAKE_PROFIT': 9.99,
        'BREAK_EVEN_TRIGGER': 0.05
    },
    'SCALPING': {
        'RISK_LIMIT': 1.0,
        'MIN_CONCENTRATION': 0.05,
        'STOP_LOSS': -0.03,
        'TAKE_PROFIT': 0.06,
        'BREAK_EVEN_TRIGGER': 0.03,
        'MIN_RISK_RATIO': 0.40
    },
    'LOW_ENTRY': {
        'RISK_LIMIT': 0.30,
        'MIN_CONCENTRATION': 0.03,
        'STOP_LOSS': -0.05,
        'TAKE_PROFIT': 9.99,
        'BREAK_EVEN_TRIGGER': 0.08,
        'MAX_MOMENTUM': 45
    }
}

MICRO_FEATURE_FILE = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
DB_PATH = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"
RESULT_DIR = r"C:\jupyter_notebook\ai_twstock\backtest_micro_simulate\v1\result"

# =================================================================
# 核心動能邏輯
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

# =================================================================
# 券商分點邏輯
# =================================================================

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
    if not top_buyers or not price_info: return {'concentration': 0, 'is_aligned': False}
    total_vol = price_info.get('Trading_Volume', 0)
    if total_vol <= 0: return {'concentration': 0, 'is_aligned': False}
    concentration = sum([abs(t.get('net', 0)) for t in top_buyers[:5] if t.get('net', 0) > 0]) / total_vol
    open_p = price_info.get('open', 0)
    gain = (price_info.get('close', 0) - open_p) / open_p if open_p > 0 else 0
    is_aligned = not ((gain > 0.05 and concentration < 0.01) or (concentration > 0.20 and gain < -0.02))
    return {'concentration': concentration, 'is_aligned': is_aligned}

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

def decide_buy(momentum_score, dt_signal, risk_ratio, is_winner_buying, pv_alignment, mode='VOLATILITY'):
    concentration = pv_alignment['concentration'] if pv_alignment else 0
    
    if mode == 'LOW_ENTRY':
        if momentum_score < STRATEGY_MODES['LOW_ENTRY']['MAX_MOMENTUM'] and is_winner_buying and concentration > 0.04:
            return True, 'LOW_ENTRY_ACCUMULATION'
        return False, None

    if concentration < 0.01: return False, None
    if risk_ratio > 0.60: return False, None
    if is_winner_buying and momentum_score > 50: return True, 'BULL_CHARGE'
    if momentum_score >= 75: return True, 'MOMENTUM_FOLLOW'
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
        item = {'trader': f"{row['trader_name']}/{row['trader_id']}", 'net': row['net_qty'] if row['is_buy'] else -row['net_qty']}
        if row['is_buy']: data[sid]['trading_daily_report'][date]['top_buyers'].append(item)
        else: data[sid]['trading_daily_report'][date]['top_sellers'].append(item)
    conn.close(); return data

def run_backtest():
    start_date = "2026-03-01"
    data = load_all_data(DB_PATH, "2026-01-01")
    if not data: return
    with open(MICRO_FEATURE_FILE, 'r', encoding='utf-8') as f:
        micro_features = {str(item['id']).strip(): item for item in json.load(f)}
    
    stock_names, stock_industries = load_stock_info()
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    start_idx = all_dates.index(next(d for d in all_dates if d >= start_date))
    
    cash = 2000000; portfolio = {}; transactions = []; top_n = 15 # 擴大持股，全額參與牛市
    
    print(f"開始回測: {all_dates[start_idx]} -> {all_dates[-1]}")
    for idx in range(start_idx, len(all_dates)):
        current_date = all_dates[idx]
        to_sell_list = []
        for sid, pos in list(portfolio.items()):
            if current_date not in data[sid]['price']: continue
            curr_p = data[sid]['price'][current_date]['close']
            gain = (curr_p - pos['avg_price']) / pos['avg_price']
            if 'max_gain' not in pos or gain > pos['max_gain']: pos['max_gain'] = gain
            
            mode = pos['mode']; params = STRATEGY_MODES.get(mode, STRATEGY_MODES['VOLATILITY'])
            sell_reason = None; sell_ratio = 1.0
            
            # 1. 階梯式分批出場邏輯 (優化：取消 30% 全清，改為動態移動停損)
            if mode in ['VOLATILITY', 'LOW_ENTRY']:
                # 第一階段：10% 減碼一半，鎖定基本利潤
                if not pos.get('half_sold') and gain >= 0.10:
                    sell_reason = f"分批減碼({mode}) (+10%)"
                    sell_ratio = 0.5
                    pos['half_sold'] = True
            
            if not sell_reason:
                # 移動停損保護 (獲利越高，停損越緊，鎖住大波段)
                trailing_limit = 0.08
                if gain > 0.30: trailing_limit = 0.05 # 獲利超過 30%，回落 5% 就跑
                if gain > 0.50: trailing_limit = 0.03 # 獲利超過 50%，回落 3% 就跑
                
                if gain < (pos['max_gain'] - trailing_limit):
                    sell_reason = f"移動停損({mode})"
                elif gain <= -0.10:
                    sell_reason = "停損"
            
            if mode == 'SCALPING': max_days = 1
            elif mode == 'LOW_ENTRY': max_days = 40
            else: max_days = (30 if pos.get('half_sold') else 10)
            
            if not sell_reason and (idx - all_dates.index(pos['buy_date'])) >= max_days: sell_reason = "到期"
            
            if sell_reason:
                qty = int(pos['shares'] * sell_ratio)
                if qty < 1000 or sell_ratio == 1.0: qty = pos['shares']
                cash += qty * curr_p * 0.998
                transactions.append({'date': current_date, 'sid': sid, 'action': 'SELL', 'gain': gain, 'reason': sell_reason, 'price': curr_p})
                if qty >= pos['shares']: to_sell_list.append(sid)
                else: pos['shares'] -= qty
        for sid in to_sell_list: del portfolio[sid]

        if len(portfolio) < top_n:
            analysis_date = all_dates[idx-1]
            
            # 1. 找出當日熱門產業 (Top 3) - 讓市場決定
            sector_scores = defaultdict(list)
            for sid, details in data.items():
                if analysis_date not in details['price']: continue
                p_data = details['price']; sorted_d = sorted(p_data.keys()); a_idx = sorted_d.index(analysis_date)
                if a_idx < 20: continue
                start_p = p_data[sorted_d[a_idx-20]]['close']
                if start_p <= 0: continue
                gain_20 = (p_data[analysis_date]['close'] - start_p) / start_p
                ind = stock_industries.get(sid, "其他")
                if ind == "其他": continue
                sector_scores[ind].append(gain_20)
            
            # 計算產業平均漲幅並取 Top 5 (牛市中放寬產業限制，確保資金利用率)
            avg_sector_gain = {ind: sum(gains)/len(gains) for ind, gains in sector_scores.items() if len(gains) >= 3}
            top_sectors = sorted(avg_sector_gain.items(), key=lambda x: x[1], reverse=True)[:5]
            top_sector_names = [x[0] for x in top_sectors]
            
            candidates = []
            for sid, details in data.items():
                if sid in portfolio or analysis_date not in details['price'] or current_date not in details['price']: continue
                
                industry = stock_industries.get(sid, "")
                if industry not in top_sector_names: continue
                
                p_data = details['price']; sorted_d = sorted(p_data.keys()); a_idx = sorted_d.index(analysis_date)
                if a_idx < 20: continue
                
                start_p = p_data[sorted_d[a_idx-20]]['close']
                if start_p <= 0: continue
                gain_20 = (p_data[analysis_date]['close'] - start_p) / start_p
                
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
                top_b = details['trading_daily_report'].get(analysis_date, {}).get('top_buyers', [])
                if top_b and str(top_b[0].get('trader','')).split('/')[-1] in micro_features:
                    if micro_features[str(top_b[0].get('trader','')).split('/')[-1]].get('穩重指數', 0) > 15: is_winner = True
                
                if score < STRATEGY_MODES['LOW_ENTRY']['MAX_MOMENTUM'] and is_winner:
                    mode = 'LOW_ENTRY'
                else:
                    mode = 'SCALPING' if risk_ratio > 0.40 else 'VOLATILITY'
                
                buy, strat = decide_buy(score, dt_sig, risk_ratio, is_winner, pv_align, mode=mode)
                if buy: candidates.append({'sid': sid, 'score': score, 'mode': mode, 'price': p_data[current_date]['open']})
            
            candidates.sort(key=lambda x: x['score'], reverse=True)
            for cand in candidates[:top_n - len(portfolio)]:
                buy_price = cand['price']
                shares = int((cash / (top_n - len(portfolio)) * 0.95) / buy_price / 1000) * 1000
                if shares >= 1000:
                    cost = shares * buy_price * 1.002
                    if cash >= cost:
                        cash -= cost
                        portfolio[cand['sid']] = {'shares': shares, 'avg_price': buy_price, 'buy_date': current_date, 'mode': cand['mode']}
                        transactions.append({'date': current_date, 'sid': cand['sid'], 'action': 'BUY', 'price': buy_price})

    final_v = cash + sum(p['shares'] * data[s]['price'][all_dates[-1]]['close'] for s, p in portfolio.items() if all_dates[-1] in data[s]['price'])
    print(f"\n回測結束! 最終價值: {final_v:,.0f} (報酬率: {(final_v-2000000)/2000000:.1%})")
    
    os.makedirs(RESULT_DIR, exist_ok=True)
    log_path = os.path.join(RESULT_DIR, "transaction_log.txt")
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f"=== 交易流水帳 (3月至今 - 三模式版) ===\n")
        f.write(f"起始資金: 2,000,000 | 最終價值: {final_v:,.0f}\n")
        f.write("-" * 80 + "\n")
        f.write(f"{'日期':<12} | {'代號':<6} | {'動作':<4} | {'價格':<8} | {'獲利':<8} | {'原因':<20}\n")
        f.write("-" * 80 + "\n")
        for t in transactions:
            gain_str = f"{t.get('gain', 0):.1%}" if t['action'] == 'SELL' else "-"
            f.write(f"{t['date']:<12} | {t['sid']:<6} | {t['action']:<4} | {t.get('price', 0):<8.2f} | {gain_str:<8} | {t.get('reason', ''):<20}\n")
    print(f"交易流水帳已匯出至: {log_path}")

if __name__ == "__main__":
    run_backtest()
