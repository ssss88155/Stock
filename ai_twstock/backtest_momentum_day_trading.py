#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
backtest_momentum_day_trading.py
還原完整統計邏輯版本，並保持 SQL 優化對接
"""

import json
import os
import sys
import sqlite3
from datetime import datetime
from collections import OrderedDict, defaultdict

# 嘗試設定輸出編碼
try:
    if sys.stdout.encoding != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

# 引用現有動能分析
import analyze_momentum

# =================================================================
# 路徑與設定
# =================================================================
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config', 'backtest_config.json')
MICRO_FEATURE_FILE = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
RESULT_DIR = r"C:\jupyter_notebook\ai_twstock\backtest_micro_simulate\v1\result"

DEFAULT_WEIGHTS = {
    'WEIGHT_GAIN': 40, 'WEIGHT_VOLUME': 10, 'WEIGHT_FOREIGN': 10,
    'WEIGHT_SITC': 10, 'WEIGHT_VCP': 10, 'WEIGHT_BREAKOUT': 10,
    'WEIGHT_HANDOVER': 40, 'MIN_SCORE_TO_PRINT': 40, 'MIN_TRADING_VALUE': 10000000,
}

LOOSE_BUY_SCORE_THRESHOLD = 50
LOOSE_TOP_N = 15
LOOSE_START_DAYS_BACK = 60

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def load_micro_features() -> dict:
    if os.path.exists(MICRO_FEATURE_FILE):
        try:
            with open(MICRO_FEATURE_FILE, 'r', encoding='utf-8') as f:
                features = json.load(f)
                return {str(item['id']).strip(): item for item in features}
        except: pass
    return {}

def load_stock_names() -> dict:
    names = {}
    path = os.path.join(os.path.dirname(__file__), 'taiwan_stocks.csv')
    if os.path.exists(path):
        try:
            import pandas as pd
            df = pd.read_csv(path)
            for _, row in df.iterrows():
                names[str(row[df.columns[0]])] = str(row[df.columns[1]])
        except: pass
    return names

def calculate_momentum_scores(data: dict, start_date: str, end_date: str, weights: dict = None) -> list:
    if weights is None: weights = DEFAULT_WEIGHTS
    try:
        return analyze_momentum.analyze_momentum(data, start_date, end_date, weights=weights)
    except: return []

def calculate_day_trading_signal(sid: str, date: str, data: dict, micro_features: dict) -> dict:
    if not micro_features: return {'type': None, 'strength': 0.0, 'reason': '無券商特徵'}
    stock_info = data.get(sid, {})
    buy_total_weighted = sell_total_weighted = buy_total_qty = sell_total_qty = 0.0
    has_data = False
    report = stock_info.get('trading_daily_report', {}).get(date, {})
    for key, is_buy in [('top_buyers', True), ('top_sellers', False)]:
        for t in report.get(key, []):
            trader_str = str(t.get('trader', ''))
            bid = trader_str.split('/')[-1].strip()
            if bid in micro_features:
                has_data = True
                stability = micro_features[bid].get('穩重指數', 0)
                qty = abs(t.get('net', 0))
                if is_buy:
                    buy_total_weighted += (qty * stability / 100.0)
                    buy_total_qty += qty
                else:
                    sell_total_weighted += (qty * stability / 100.0)
                    sell_total_qty += qty
    if not has_data: return {'type': None, 'strength': 0.0, 'reason': '無券商明細數據'}
    net_score = buy_total_weighted - sell_total_weighted
    buy_idx = (buy_total_weighted / buy_total_qty) if buy_total_qty > 0 else 0
    sell_idx = (sell_total_weighted / sell_total_qty) if sell_total_qty > 0 else 0
    bs_diff_index = buy_idx - sell_idx
    print(f"[DT DEBUG] {date} {sid} | net_score={net_score:.1f} BS_Diff={bs_diff_index:.2f} (B_Idx:{buy_idx:.2f} S_Idx:{sell_idx:.2f})")
    if net_score > 20 and bs_diff_index > 0.1:
        return {'type': 'REVERSAL', 'strength': min(100, bs_diff_index * 80), 'reason': f'REVERSAL: 買賣指數正向({bs_diff_index:.2f})'}
    elif net_score < -20 and bs_diff_index < -0.1:
        return {'type': 'FOLLOW', 'strength': min(100, abs(bs_diff_index) * 60), 'reason': f'FOLLOW: 買賣指數負向({bs_diff_index:.2f})'}
    return {'type': None, 'strength': 0.0, 'reason': '訊號不明顯'}

def check_price_volume_alignment(sid: str, date: str, data: dict) -> dict:
    stock_info = data.get(sid, {})
    price_info = stock_info.get('price', {}).get(date, {})
    top_buyers = stock_info.get('trading_daily_report', {}).get(date, {}).get('top_buyers', [])
    if not top_buyers or not price_info: return {'concentration': 0, 'is_aligned': False}
    total_vol = price_info.get('Trading_Volume', 0)
    if total_vol <= 0: return {'concentration': 0, 'is_aligned': False}
    concentration = sum([abs(t.get('net', 0)) for t in top_buyers[:5] if t.get('net', 0) > 0]) / total_vol
    gain = (price_info.get('close', 0) - price_info.get('open', 0)) / price_info.get('open', 1)
    is_aligned = not ((gain > 0.04 and concentration < 0.05) or (concentration > 0.15 and gain < -0.01))
    return {'concentration': concentration, 'is_aligned': is_aligned}

def calculate_day_trader_risk(sid: str, date: str, data: dict, micro_features: dict) -> float:
    top_buyers = data.get(sid, {}).get('trading_daily_report', {}).get(date, {}).get('top_buyers', [])
    if not top_buyers: return 0.0
    dt_vol = total_vol = 0
    for t in top_buyers[:10]:
        bid = str(t.get('trader', '')).split('/')[-1].strip()
        qty = abs(t.get('net', 0))
        total_vol += qty
        if bid in micro_features and micro_features[bid].get('穩重指數', 0) < -50: dt_vol += qty
    return dt_vol / total_vol if total_vol > 0 else 0

def decide_buy(momentum_score: float, dt_signal: dict, risk_ratio: float, is_winner_buying: bool,
                pv_alignment: dict, mom_threshold: float, use_strict_reversal: bool) -> tuple:
    """
    期望值優化版本：
    1. 放寬集中度過濾，恢復勝率
    2. 強化贏家同步的爆發力判斷
    """
    concentration = pv_alignment['concentration'] if pv_alignment else 0
    
    # 1. 基礎過濾 (放寬至 1%，避免誤殺)
    if concentration < 0.01: return False, None, '主力參與度極低'
    if risk_ratio > 0.55: return False, None, f'隔日沖風險過高'
    if pv_alignment and not pv_alignment['is_aligned']: return False, None, f'量價背離'

    # 2. 動態門檻 (恢復靈敏度)
    eff_threshold = mom_threshold
    if is_winner_buying: eff_threshold *= 0.7
    if concentration > 0.08: eff_threshold *= 0.85

    # 3. 策略判斷
    if dt_signal['type'] == 'REVERSAL':
        if use_strict_reversal and '買賣指數正向' not in dt_signal['reason']: return False, None, ''
        # 反轉訊號只要強度夠且有基本買盤就進場
        if dt_signal['strength'] >= 20:
            return True, 'REVERSAL', dt_signal['reason']
            
    if dt_signal['type'] == 'FOLLOW' and dt_signal['strength'] >= 20:
        return True, 'FOLLOW', dt_signal['reason']
        
    if momentum_score >= eff_threshold:
        return True, 'MOMENTUM', f'動能分數 {momentum_score:.1f}'
    return False, None, ''

def load_data_from_sql(db_path: str, target_sids: list = None):
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row; cursor = conn.cursor(); data = {}
    q1 = "SELECT * FROM daily_prices"
    if target_sids: q1 += f" WHERE stock_id IN ({','.join(['?']*len(target_sids))})"; cursor.execute(q1, target_sids)
    else: cursor.execute(q1)
    for row in cursor.fetchall():
        sid, date = row['stock_id'], row['date']
        if sid not in data: data[sid] = {'price': {}, 'institutional': {}, 'trading_daily_report': {}}
        data[sid]['price'][date] = {'open': row['open'], 'max': row['high'], 'min': row['low'], 'close': row['close'], 'Trading_Volume': row['volume']}
        data[sid]['institutional'][date] = {'Foreign_Investor': {'buy': row['foreign_buy'], 'sell': 0}, 'Investment_Trust': {'buy': row['sitc_buy'], 'sell': 0}, 'Dealer': {'buy': row['dealer_buy'], 'sell': 0}}
    q2 = "SELECT * FROM broker_details"
    if target_sids: q2 += f" WHERE stock_id IN ({','.join(['?']*len(target_sids))})"; cursor.execute(q2, target_sids)
    else: cursor.execute(q2)
    for row in cursor.fetchall():
        sid, date = row['stock_id'], row['date']
        if sid not in data: continue
        if date not in data[sid]['trading_daily_report']: data[sid]['trading_daily_report'][date] = {'top_buyers': [], 'top_sellers': []}
        item = {'trader': f"{row['trader_name']}/{row['trader_id']}", 'net': row['net_qty'] if row['is_buy'] else -row['net_qty'], 'avg_p': row['avg_price']}
        if row['is_buy']: data[sid]['trading_daily_report'][date]['top_buyers'].append(item)
        else: data[sid]['trading_daily_report'][date]['top_sellers'].append(item)
    conn.close(); return data

def run_momentum_day_trading_backtest(override_config: dict = None, silent: bool = False) -> dict:
    db_path = override_config.get('DB_PATH', r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db")
    target_sids = override_config.get('TARGET_SIDS')
    data = load_data_from_sql(db_path, target_sids)
    if not data: return None
    stock_names = load_stock_names(); micro_features = load_micro_features(); _config = load_config()
    if override_config: _config.update(override_config)
    use_strict_reversal = _config.get('USE_STRICT_REVERSAL', True)
    starting_cash = _config.get('STARTING_CASH', 2000000)
    weights = _config.get('WEIGHTS', DEFAULT_WEIGHTS)
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    if not all_dates: return None
    start_idx = max(0, len(all_dates) - 1 - LOOSE_START_DAYS_BACK)
    cash = starting_cash; portfolio = {}; transactions = []
    for idx in range(start_idx, len(all_dates)):
        current_date = all_dates[idx]
        to_sell = []
        for sid, pos in list(portfolio.items()):
            if current_date not in data.get(sid, {}).get('price', {}): continue
            curr_price = data[sid]['price'][current_date]['close']
            gain = (curr_price - pos['avg_price']) / pos['avg_price']
            
            # 更新最高獲利紀錄
            if 'max_gain' not in pos or gain > pos['max_gain']:
                pos['max_gain'] = gain
                
            sell_reason = None
            # 出場邏輯修正：放寬停損至 6%，停利設為 10% 並加入保本概念
            if gain >= 0.10: sell_reason = f"獲利了結 (+{gain:.1%})"
            elif gain <= -0.06: sell_reason = f"停損 ({gain:.1%})"
            # 保本機制 (獲利曾達 5% 但回落至 2% 以下)
            elif pos.get('max_gain', 0) > 0.05 and gain < 0.02:
                sell_reason = f"保本出場 ({gain:.1%})"
            elif (idx - all_dates.index(pos['buy_date'])) >= 5: sell_reason = f"到期賣出 ({gain:.1%})"
            
            if sell_reason: to_sell.append((sid, sell_reason, curr_price, gain))
        for sid, reason, price, gain in to_sell:
            shares = portfolio[sid]['shares']; cash += shares * price * 0.998
            transactions.append({'date': current_date, 'action': 'SELL', 'stock_id': sid, 'gain': gain, 'strategy': portfolio[sid]['strategy']})
            del portfolio[sid]
        if len(portfolio) < _config.get('TOP_N', LOOSE_TOP_N):
            analysis_date = all_dates[idx-1] if idx > 0 else current_date
            mom_results = calculate_momentum_scores(data, all_dates[max(0, idx-21)], analysis_date, weights=weights)
            for r in mom_results[:50]:
                sid = r['stock_id']
                if sid in portfolio or current_date not in data.get(sid, {}).get('price', {}): continue
                price = data[sid]['price'][current_date]['close']
                dt_sig = calculate_day_trading_signal(sid, analysis_date, data, micro_features)
                risk_ratio = calculate_day_trader_risk(sid, analysis_date, data, micro_features)
                pv_alignment = check_price_volume_alignment(sid, analysis_date, data)
                is_winner_buying = False
                top_buyers = data.get(sid, {}).get('trading_daily_report', {}).get(analysis_date, {}).get('top_buyers', [])
                for tb in top_buyers[:2]:
                    bid = str(tb.get('trader', '')).split('/')[-1].strip()
                    if bid in micro_features and micro_features[bid].get('穩重指數', 0) > 15: is_winner_buying = True; break
                buy, strat, reason = decide_buy(r['score'], dt_sig, risk_ratio, is_winner_buying, pv_alignment, _config.get('BUY_SCORE_THRESHOLD', LOOSE_BUY_SCORE_THRESHOLD), use_strict_reversal)
                if buy:
                    buy_budget = cash / max(1, (_config.get('TOP_N', LOOSE_TOP_N) - len(portfolio)))
                    shares = int((buy_budget * 0.8) / price / 1000) * 1000
                    if shares >= 1000:
                        cost = shares * price * 1.002
                        if cash >= cost:
                            cash -= cost
                            portfolio[sid] = {'shares': shares, 'avg_price': price, 'buy_date': current_date, 'strategy': strat}
                            transactions.append({'date': current_date, 'action': 'BUY', 'stock_id': sid, 'strategy': strat})
    final_value = cash + sum(pos['shares'] * data[sid]['price'][all_dates[-1]]['close'] for sid, pos in portfolio.items() if all_dates[-1] in data.get(sid, {}).get('price', {}))
    
    # 完整統計
    all_sells = [t for t in transactions if t['action'] == 'SELL']
    all_gains = [t['gain'] for t in all_sells]
    rev_gains = [t['gain'] for t in all_sells if t['strategy'] == 'REVERSAL']
    return {
        'total_return': (final_value - starting_cash) / starting_cash,
        'overall_win_rate': len([g for g in all_gains if g > 0]) / len(all_gains) if all_gains else 0,
        'reversal_win_rate': len([g for g in rev_gains if g > 0]) / len(rev_gains) if rev_gains else 0,
        'transactions': transactions
    }

if __name__ == "__main__":
    print("=== 動能 + 隔日沖 整合回測 (小型資料庫測試) ===")
    TEST_DB = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_test_debug.db"
    test_config = {'DB_PATH': TEST_DB, 'TARGET_SIDS': ['3081', '6187'], 'STARTING_CASH': 10000000, 'TOP_N': 5}
    print("\n>>> 測試 1: 原始邏輯 (不強制買賣指數正向)")
    res_orig = run_momentum_day_trading_backtest(override_config={**test_config, 'USE_STRICT_REVERSAL': False}, silent=True)
    print("\n>>> 測試 2: 優化邏輯 (強制買賣指數正向)")
    res_strict = run_momentum_day_trading_backtest(override_config={**test_config, 'USE_STRICT_REVERSAL': True}, silent=True)
    if res_orig and res_strict:
        print("\n" + "="*50)
        print(f"{'指標':<15} | {'原始邏輯':<10} | {'優化邏輯':<10}")
        print("-" * 50)
        print(f"{'總報酬率':<15} | {res_orig['total_return']:>10.2%} | {res_strict['total_return']:>10.2%}")
        print(f"{'整體勝率':<15} | {res_orig['overall_win_rate']:>10.1%} | {res_strict['overall_win_rate']:>10.1%}")
        print(f"{'REVERSAL勝率':<15} | {res_orig['reversal_win_rate']:>10.1%} | {res_strict['reversal_win_rate']:>10.1%}")
        print("="*50)
