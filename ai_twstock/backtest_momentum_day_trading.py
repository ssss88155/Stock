#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
backtest_momentum_day_trading.py
基於 analyze_momentum.py 的原始動能權重 + 隔日沖券商訊號 (micro_feature_all.json 穩重指數)
第一版：先讓 base 能動的 (loose filters)，每個機制獨立成 function。
策略類型: MOMENTUM (純動能), REVERSAL (負分券商倒貨後反彈), FOLLOW (正分/隔日沖跟進)
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
# 路徑與設定 (第一版使用寬鬆參數讓交易能發生)
# =================================================================
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config', 'backtest_config.json')
MICRO_FEATURE_FILE = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
RESULT_DIR = r"C:\jupyter_notebook\ai_twstock\backtest_micro_simulate\v1\result"

# 原始動能權重 (來自 analyze_momentum.py 預設，總和約 100)
DEFAULT_WEIGHTS = {
    'WEIGHT_GAIN': 40,
    'WEIGHT_VOLUME': 10,
    'WEIGHT_FOREIGN': 10,
    'WEIGHT_SITC': 10,
    'WEIGHT_VCP': 10,
    'WEIGHT_BREAKOUT': 10,
    'WEIGHT_HANDOVER': 40,
    'MIN_SCORE_TO_PRINT': 40,   # 第一版放寬，讓更多候選
    'MIN_TRADING_VALUE': 10000000,  # 放寬成交金額門檻
}

# 回測寬鬆參數 (先讓能動的)
LOOSE_BUY_SCORE_THRESHOLD = 50   # 低於原本 120
LOOSE_TOP_N = 15
LOOSE_START_DAYS_BACK = 60       # 約 3 個月

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] 載入設定檔失敗: {e}")
    return {}

def load_micro_features() -> dict:
    """載入券商特徵 (穩重指數 < 0 為隔日沖券商)"""
    if os.path.exists(MICRO_FEATURE_FILE):
        try:
            with open(MICRO_FEATURE_FILE, 'r', encoding='utf-8') as f:
                features = json.load(f)
                # 統一代號為字串 Key，並去除可能的空白
                return {str(item['id']).strip(): item for item in features}
        except Exception as e:
            print(f"[WARN] 載入 micro_feature 失敗: {e}")
    return {}

def load_stock_names() -> dict:
    names = {}
    path = os.path.join(os.path.dirname(__file__), 'taiwan_stocks.csv')
    if os.path.exists(path):
        try:
            import pandas as pd
            df = pd.read_csv(path)
            code_col = 'code' if 'code' in df.columns else df.columns[0]
            name_col = 'name' if 'name' in df.columns else df.columns[1]
            for _, row in df.iterrows():
                names[str(row[code_col])] = str(row[name_col])
        except Exception as e:
            print(f"[WARN] 載入股票名稱失敗: {e}")
    return names

# =================================================================
# 獨立機制函數 (phased: 每個功能一個 function)
# =================================================================

def calculate_momentum_scores(data: dict, start_date: str, end_date: str, weights: dict = None) -> list:
    """
    使用 analyze_momentum.py 原始邏輯計算動能分數
    返回 list of dict: [{'stock_id': , 'score': , 'gain': , ...}]
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
    try:
        results = analyze_momentum.analyze_momentum(data, start_date, end_date, weights=weights)
        return results
    except Exception as e:
        print(f"[WARN] analyze_momentum 失敗: {e}")
        return []

def calculate_day_trading_signal(sid: str, date: str, data: dict, micro_features: dict) -> dict:
    """
    隔日沖訊號計算 (使用 micro 穩重指數 + institutional 券商資料)
    回傳: {'type': 'REVERSAL' | 'FOLLOW' | None, 'strength': float, 'reason': str}
    邏輯：
    1. 淨分 (net_score) = (淨買超股數) * (穩重指數) / 100.0
    2. 買賣指數 (buy_sell_index) = (SUM(買方股數*穩重指數) / SUM(總買股數)) - (SUM(賣方股數*穩重指數) / SUM(總賣股數))
    """
    if not micro_features:
        return {'type': None, 'strength': 0.0, 'reason': '無券商特徵'}

    stock_info = data.get(sid, {})
    
    buy_total_weighted = 0.0
    sell_total_weighted = 0.0
    buy_total_qty = 0.0
    sell_total_qty = 0.0
    has_data = False

    # 格式 A: institutional -> brokers
    inst = stock_info.get('institutional', {}).get(date, {})
    brokers = inst.get('brokers', []) or []
    for b in brokers:
        bid = str(b.get('id', '')).strip()
        if bid in micro_features:
            has_data = True
            stability = micro_features[bid].get('穩重指數', 0)
            b_qty = b.get('buy_qty', 0)
            s_qty = b.get('sell_qty', 0)
            buy_total_weighted += (b_qty * stability / 100.0)
            sell_total_weighted += (s_qty * stability / 100.0)
            buy_total_qty += b_qty
            sell_total_qty += s_qty

    # 格式 B/C: trading_daily_report
    report = stock_info.get('trading_daily_report', {}).get(date, {})
    for key, is_buy in [('top_buyers', True), ('top_sellers', False)]:
        traders = report.get(key, [])
        for t in traders:
            trader_str = str(t.get('trader', ''))
            # 同時支援 "名稱/代號" 或 "純代號" 格式
            bid = trader_str.split('/')[-1] if '/' in trader_str else trader_str
            bid_s = str(bid).strip()
            
            if bid_s in micro_features:
                has_data = True
                stability = micro_features[bid_s].get('穩重指數', 0)
                # 強健判斷：SQL 格式會把量存在 'net'，JSON 格式可能在 'net_b'/'net_s'
                # 注意：在 load_data_from_sql 中，賣方 net 已存為負數，這裡取絕對值作為量
                raw_net = abs(t.get('net', 0))
                if is_buy:
                    qty = t.get('net_b', raw_net)
                    buy_total_weighted += (qty * stability / 100.0)
                    buy_total_qty += qty
                else:
                    qty = t.get('net_s', raw_net)
                    sell_total_weighted += (qty * stability / 100.0)
                    sell_total_qty += qty

    if not has_data:
        return {'type': None, 'strength': 0.0, 'reason': '無券商明細數據'}

    # 1. 原始淨分邏輯
    net_score = buy_total_weighted - sell_total_weighted
    
    # 2. 新增：買進指數 - 賣出指數 (加權平均概念)
    buy_idx = (buy_total_weighted / buy_total_qty) if buy_total_qty > 0 else 0
    sell_idx = (sell_total_weighted / sell_total_qty) if sell_total_qty > 0 else 0
    bs_diff_index = buy_idx - sell_idx

    # === TEMP DEBUG ===
    print(f"[DT DEBUG] {date} {sid} | net_score={net_score:.1f} BS_Diff={bs_diff_index:.2f} (B_Idx:{buy_idx:.2f} S_Idx:{sell_idx:.2f})")

    # 判斷邏輯優化：
    # REVERSAL: 隔日沖賣出 (net_score > 0) 且 買賣指數為正 (代表買方比賣方更「穩重」)
    # 修正：增加對 net_score 絕對值的要求，確保有足夠的券商行為發生
    if net_score > 20 and bs_diff_index > 0.1:
        result = {
            'type': 'REVERSAL',
            'strength': min(100, bs_diff_index * 80),
            'reason': f'REVERSAL: 買賣指數正向({bs_diff_index:.2f})'
        }
    elif net_score < -20 and bs_diff_index < -0.1:
        result = {
            'type': 'FOLLOW',
            'strength': min(100, abs(bs_diff_index) * 60),
            'reason': f'FOLLOW: 買賣指數負向({bs_diff_index:.2f})'
        }
    else:
        result = {'type': None, 'strength': 0.0, 'reason': '訊號不明顯'}

    return result

def calculate_broker_concentration(sid: str, date: str, data: dict) -> float:
    """
    計算分點集中度: (前5大買進分點合計買超 / 總成交量)
    """
    stock_info = data.get(sid, {})
    report = stock_info.get('trading_daily_report', {}).get(date, {})
    top_buyers = report.get('top_buyers', [])
    
    if not top_buyers:
        return 0.0
        
    # 取得當日總成交量 (從價格資料拿)
    total_vol = stock_info.get('price', {}).get(date, {}).get('Trading_Volume', 0)
    if total_vol <= 0:
        return 0.0
        
    top_5_buy_sum = sum([abs(t.get('net', 0)) for t in top_buyers[:5] if t.get('net', 0) > 0])
    return top_5_buy_sum / total_vol

def check_price_volume_alignment(sid: str, date: str, data: dict) -> dict:
    """
    深度量價配合分析：
    1. 買超集中度 (Top 5 Buy / Total Volume)
    2. 買一異常度 (Current Top Buy / Avg Top Buy)
    3. 漲幅匹配度 (漲幅是否由主力買盤支撐)
    """
    stock_info = data.get(sid, {})
    report = stock_info.get('trading_daily_report', {}).get(date, {})
    price_info = stock_info.get('price', {}).get(date, {})
    top_buyers = report.get('top_buyers', [])
    
    if not top_buyers or not price_info:
        return {'concentration': 0, 'is_aligned': False, 'top_buy_ratio': 0}
        
    total_vol = price_info.get('Trading_Volume', 0)
    if total_vol <= 0: return {'concentration': 0, 'is_aligned': False, 'top_buy_ratio': 0}

    top_5_buy_sum = sum([abs(t.get('net', 0)) for t in top_buyers[:5] if t.get('net', 0) > 0])
    concentration = top_5_buy_sum / total_vol
    
    # 漲幅計算
    close = price_info.get('close', 0)
    open_p = price_info.get('open', 0)
    gain = (close - open_p) / open_p if open_p > 0 else 0
    
    # 買一異常度
    current_top_buy = abs(top_buyers[0].get('net', 0))
    all_dates = sorted(list(stock_info.get('trading_daily_report', {}).keys()))
    idx = all_dates.index(date) if date in all_dates else -1
    
    avg_past_buy = 0
    if idx > 0:
        lookback = all_dates[max(0, idx-20):idx]
        past_buys = [abs(stock_info['trading_daily_report'][d]['top_buyers'][0]['net'])
                     for d in lookback if stock_info['trading_daily_report'].get(d, {}).get('top_buyers')]
        avg_past_buy = sum(past_buys) / len(past_buys) if past_buys else 0

    # 邏輯：如果漲幅很大 (>4%) 但集中度很低 (<5%)，代表是散戶盤，不穩
    # 如果集中度很高 (>15%) 但股價沒漲甚至跌，代表有人在倒貨給主力，危險
    is_aligned = True
    if gain > 0.04 and concentration < 0.05: is_aligned = False
    if concentration > 0.15 and gain < -0.01: is_aligned = False
    
    return {
        'concentration': concentration,
        'is_aligned': is_aligned,
        'top_buy_ratio': current_top_buy / avg_past_buy if avg_past_buy > 0 else 1.0
    }

def calculate_day_trader_risk(sid: str, date: str, data: dict, micro_features: dict) -> float:
    """
    計算隔日沖風險佔比: (隔日沖分點買超量) / (前十大買超分點總量)
    """
    stock_info = data.get(sid, {})
    report = stock_info.get('trading_daily_report', {}).get(date, {})
    top_buyers = report.get('top_buyers', [])
    if not top_buyers: return 0.0
    
    day_trader_buy_vol = 0
    total_top_buy_vol = 0
    for t in top_buyers[:10]:
        bid = str(t.get('trader', '')).split('/')[-1].strip()
        net_qty = abs(t.get('net', 0))
        total_top_buy_vol += net_qty
        if bid in micro_features and micro_features[bid].get('穩重指數', 0) < -50:
            day_trader_buy_vol += net_qty
    return day_trader_buy_vol / total_top_buy_vol if total_top_buy_vol > 0 else 0

def decide_buy(momentum_score: float, dt_signal: dict, risk_ratio: float = 0, is_winner_buying: bool = False,
               pv_alignment: dict = None, mom_threshold: float = LOOSE_BUY_SCORE_THRESHOLD,
               use_strict_reversal: bool = True) -> tuple:
    """
    深度優化決策：結合券商行為與量價結構
    """
    # 1. 隔日沖風險過濾 (維持 50%)
    if risk_ratio > 0.50:
        return False, None, f'隔日沖風險過高({risk_ratio:.1%})'

    # 2. 量價背離過濾 (核心優化)
    if pv_alignment and not pv_alignment['is_aligned']:
        return False, None, f'量價背離(集中度:{pv_alignment["concentration"]:.1%})'

    # 3. 贏家與集中度加持
    # 如果集中度高 (>8%) 且贏家在買，大幅放寬門檻 (震盪盤更看重集中度)
    effective_threshold = mom_threshold
    if is_winner_buying:
        effective_threshold *= 0.75 # 贏家同步加權提高
    if pv_alignment and pv_alignment['concentration'] > 0.08:
        effective_threshold *= 0.85 # 集中度門檻降低，但加權提高

    # 4. 策略判斷
    if dt_signal['type'] == 'REVERSAL':
        if use_strict_reversal and '買賣指數正向' not in dt_signal['reason']:
            return False, None, ''
        # 如果是反轉策略，集中度必須 > 5% 才具備可信度
        if dt_signal['strength'] >= 25 and (pv_alignment['concentration'] > 0.05 if pv_alignment else True):
            return True, 'REVERSAL', dt_signal['reason']
            
    if dt_signal['type'] == 'FOLLOW' and dt_signal['strength'] >= 20:
        return True, 'FOLLOW', dt_signal['reason']
        
    if momentum_score >= effective_threshold:
        reason = f'動能分數 {momentum_score:.1f}'
        if is_winner_buying: reason += " (贏家同步)"
        if pv_alignment and pv_alignment['concentration'] > 0.1: reason += f" (集中度:{pv_alignment['concentration']:.1%})"
        return True, 'MOMENTUM', reason
        
    return False, None, ''

# =================================================================
# 主回測函數 (phased 第一版)
# =================================================================

def load_data_from_sql(db_path: str, target_sids: list = None):
    """從 SQL 載入回測所需資料格式"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    data = {}
    
    # 1. 載入價格與法人
    query = "SELECT * FROM daily_prices"
    if target_sids:
        placeholders = ','.join(['?'] * len(target_sids))
        query += f" WHERE stock_id IN ({placeholders})"
        cursor.execute(query, target_sids)
    else:
        cursor.execute(query)
        
    for row in cursor.fetchall():
        sid = row['stock_id']
        date = row['date']
        if sid not in data:
            data[sid] = {'price': {}, 'institutional': {}, 'trading_daily_report': {}}
        
        data[sid]['price'][date] = {
            'open': row['open'], 'max': row['high'], 'min': row['low'], 'close': row['close'],
            'Trading_Volume': row['volume']
        }
        data[sid]['institutional'][date] = {
            'Foreign_Investor': {'buy': row['foreign_buy'], 'sell': 0},
            'Investment_Trust': {'buy': row['sitc_buy'], 'sell': 0}
        }

    # 2. 載入分點明細
    query = "SELECT * FROM broker_details"
    if target_sids:
        placeholders = ','.join(['?'] * len(target_sids))
        query += f" WHERE stock_id IN ({placeholders})"
        cursor.execute(query, target_sids)
    else:
        cursor.execute(query)
        
    for row in cursor.fetchall():
        sid = row['stock_id']
        date = row['date']
        if sid not in data: continue
        
        if date not in data[sid]['trading_daily_report']:
            data[sid]['trading_daily_report'][date] = {'top_buyers': [], 'top_sellers': []}
        
        # 統整為與原本 JSON 一致的格式
        item = {
            'trader': f"{row['trader_name']}/{row['trader_id']}",
            'net': row['net_qty'] if row['is_buy'] else -row['net_qty'],
            'avg_p': row['avg_price']
        }
        if row['is_buy']:
            data[sid]['trading_daily_report'][date]['top_buyers'].append(item)
        else:
            data[sid]['trading_daily_report'][date]['top_sellers'].append(item)
            
    conn.close()
    return data

def run_momentum_day_trading_backtest(override_config: dict = None, silent: bool = False) -> dict:
    """執行 動能 + 隔日沖 整合回測"""
    if not silent: print("執行 動能 + 隔日沖 整合回測 (SQL 模式)...")

    # 1. 載入
    db_path = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"
    target_sids = override_config.get('TARGET_SIDS') if override_config else None
    
    if os.path.exists(db_path):
        data = load_data_from_sql(db_path, target_sids)
    else:
        data = analyze_momentum.load_stock_data_wrapper('stock_data.json')
        
    stock_names = load_stock_names()
    micro_features = load_micro_features()
    _config = load_config()
    if override_config:
        _config.update(override_config)
    
    use_strict_reversal = _config.get('USE_STRICT_REVERSAL', True)
    starting_cash = _config.get('STARTING_CASH', 2000000)
    weights = _config.get('WEIGHTS', DEFAULT_WEIGHTS)

    # 回測期間
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    if not all_dates:
        return None
    end_idx = len(all_dates) - 1
    start_idx = max(0, end_idx - LOOSE_START_DAYS_BACK)

    buy_score_threshold = _config.get('BUY_SCORE_THRESHOLD', LOOSE_BUY_SCORE_THRESHOLD)
    top_n = _config.get('TOP_N', LOOSE_TOP_N)

    # 2. 初始化
    cash = starting_cash
    total_invested = starting_cash
    portfolio = {}
    transactions = []

    # 3. 主要迴圈
    for idx in range(start_idx, len(all_dates)):
        current_date = all_dates[idx]

        # 更新持股價值
        portfolio_value = cash
        for sid, pos in portfolio.items():
            if current_date in data.get(sid, {}).get('price', {}):
                portfolio_value += pos['shares'] * data[sid]['price'][current_date]['close']

        # 賣出檢查
        to_sell = []
        for sid, pos in list(portfolio.items()):
            if current_date not in data.get(sid, {}).get('price', {}):
                continue
            curr_price = data[sid]['price'][current_date]['close']
            gain = (curr_price - pos['avg_price']) / pos['avg_price'] if pos['avg_price'] > 0 else 0

            sell_reason = None
            if gain >= 0.08:
                sell_reason = f"獲利了結 (+{gain:.1%})"
            elif gain <= -0.05:
                sell_reason = f"停損 ({gain:.1%})"
            elif (idx - all_dates.index(pos['buy_date'])) >= 5:
                sell_reason = f"到期賣出 ({gain:.1%})"

            if sell_reason:
                to_sell.append((sid, sell_reason, curr_price, gain))

        for sid, reason, price, gain in to_sell:
            shares = portfolio[sid]['shares']
            value = shares * price * 0.998
            cash += value
            transactions.append({
                'date': current_date,
                'action': 'SELL',
                'stock_id': sid,
                'stock_name': stock_names.get(sid, sid),
                'shares': shares,
                'price': price,
                'gain': gain,
                'reason': reason,
                'strategy': portfolio[sid].get('strategy', 'MOMENTUM')
            })
            del portfolio[sid]
            if not silent:
                print(f"[{current_date}] 賣出 {sid} {shares}股 @ {price:.2f} ({reason})")

        # 買進檢查
        if len(portfolio) < top_n:
            analysis_date = all_dates[idx-1] if idx > 0 else current_date
            start_mom = all_dates[max(0, idx-1-20)]
            mom_results = calculate_momentum_scores(data, start_mom, analysis_date, weights=weights)

            candidates = []
            for r in mom_results[:50]:
                sid = r['stock_id']
                if sid in portfolio or current_date not in data.get(sid, {}).get('price', {}):
                    continue
                price = data[sid]['price'][current_date]['close']
                if price < 10:
                    continue

                mom_score = r['score']
                dt_sig = calculate_day_trading_signal(sid, analysis_date, data, micro_features)
                risk_ratio = calculate_day_trader_risk(sid, analysis_date, data, micro_features)
                pv_alignment = check_price_volume_alignment(sid, analysis_date, data)
                
                # 修正贏家邏輯：只要買一或買二分點是「穩重分點」即視為贏家同步
                is_winner_buying = False
                report = data.get(sid, {}).get('trading_daily_report', {}).get(analysis_date, {})
                top_buyers = report.get('top_buyers', [])
                for tb in top_buyers[:2]:
                    t_bid = str(tb.get('trader', '')).split('/')[-1].strip()
                    if t_bid in micro_features and micro_features[t_bid].get('穩重指數', 0) > 15:
                        is_winner_buying = True
                        break

                buy, strat, reason = decide_buy(mom_score, dt_sig, risk_ratio=risk_ratio, is_winner_buying=is_winner_buying,
                                               pv_alignment=pv_alignment, mom_threshold=buy_score_threshold,
                                               use_strict_reversal=use_strict_reversal)
                if buy:
                    candidates.append({
                        'sid': sid,
                        'score': mom_score,
                        'dt_strength': dt_sig['strength'],
                        'strategy': strat,
                        'reason': reason,
                        'price': price
                    })

            candidates.sort(key=lambda x: (x['score'] + x['dt_strength']), reverse=True)
            available = top_n - len(portfolio)
            buy_budget = cash / max(1, available)

            for cand in candidates[:available]:
                if cash < buy_budget * 0.3:
                    break
                sid = cand['sid']
                price = cand['price']
                shares = int((buy_budget * 0.8) / price / 1000) * 1000
                if shares < 1000:
                    continue

                cost = shares * price * 1.002
                if cost > cash:
                    continue

                cash -= cost
                portfolio[sid] = {
                    'shares': shares,
                    'avg_price': price,
                    'buy_date': current_date,
                    'max_price': price,
                    'strategy': cand['strategy']
                }
                transactions.append({
                    'date': current_date,
                    'action': 'BUY',
                    'stock_id': sid,
                    'stock_name': stock_names.get(sid, sid),
                    'shares': shares,
                    'price': price,
                    'strategy': cand['strategy'],
                    'reason': cand['reason'],
                    'mom_score': cand['score'],
                    'dt_strength': cand['dt_strength']
                })
                if not silent:
                    print(f"[{current_date}] 買進 {sid} {shares}股 @ {price:.2f} ({cand['strategy']}: {cand['reason']})")

    # 4. 最終結算
    final_value = cash
    for sid, pos in portfolio.items():
        if all_dates[-1] in data.get(sid, {}).get('price', {}):
            final_value += pos['shares'] * data[sid]['price'][all_dates[-1]]['close']

    days = (datetime.strptime(all_dates[-1], '%Y-%m-%d') - datetime.strptime(all_dates[start_idx], '%Y-%m-%d')).days
    years = days / 365.25
    total_return = (final_value - total_invested) / total_invested
    annualized = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    # 統計
    reversal_sells = [t for t in transactions if t['action'] == 'SELL' and t.get('strategy') == 'REVERSAL']
    rev_gains = [t['gain'] for t in reversal_sells]
    all_sells = [t for t in transactions if t['action'] == 'SELL']
    all_gains = [t['gain'] for t in all_sells]
    overall_win = len([g for g in all_gains if g > 0]) / len(all_gains) if all_gains else 0

    result = {
        'total_return': total_return,
        'annualized_return': annualized,
        'final_value': final_value,
        'transactions': transactions,
        'days': days,
        'reversal_performance': {
            'win_rate': len([g for g in rev_gains if g > 0]) / len(rev_gains) if rev_gains else 0,
            'avg_return': sum(rev_gains) / len(rev_gains) if rev_gains else 0
        },
        'overall': {
            'win_rate': overall_win,
            'total_transactions': len(transactions)
        }
    }

    try:
        os.makedirs(RESULT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%y%m%d_%H%M")
        fpath = os.path.join(RESULT_DIR, f"momentum_day_trading_{ts}.json")
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except:
        pass

    return result

if __name__ == "__main__":
    print("=== 動能 + 隔日沖 整合回測 (2330 & 6187 對照組測試) ===")
    test_config = {'TARGET_SIDS': ['2330', '6187'], 'STARTING_CASH': 10000000, 'TOP_N': 5}
    
    print("\n>>> 測試 1: 原始邏輯 (不強制買賣指數正向)")
    res_orig = run_momentum_day_trading_backtest(override_config={**test_config, 'USE_STRICT_REVERSAL': False}, silent=True)
    
    print("\n>>> 測試 2: 優化邏輯 (強制買賣指數正向)")
    res_strict = run_momentum_day_trading_backtest(override_config={**test_config, 'USE_STRICT_REVERSAL': True}, silent=True)
    
    if res_orig and res_strict:
        print("\n" + "="*50)
        print(f"{'指標':<15} | {'原始邏輯':<10} | {'優化邏輯':<10}")
        print("-" * 50)
        print(f"{'總報酬率':<15} | {res_orig['total_return']:>10.2%} | {res_strict['total_return']:>10.2%}")
        print(f"{'整體勝率':<15} | {res_orig['overall']['win_rate']:>10.1%} | {res_strict['overall']['win_rate']:>10.1%}")
        print(f"{'REVERSAL勝率':<15} | {res_orig['reversal_performance']['win_rate']:>10.1%} | {res_strict['reversal_performance']['win_rate']:>10.1%}")
        print("="*50)
