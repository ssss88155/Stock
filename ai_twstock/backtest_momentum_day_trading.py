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
                return {item['id']: item for item in features}
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
        bid = str(b.get('id', ''))
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
            trader_str = t.get('trader', '')
            if '/' in trader_str:
                bid = trader_str.split('/')[-1]
                if bid in micro_features:
                    has_data = True
                    stability = micro_features[bid].get('穩重指數', 0)
                    # 優先使用 net_s/net_b (若有)，否則用 net
                    net = t.get('net', 0)
                    if is_buy:
                        qty = t.get('net_b', net)
                        buy_total_weighted += (qty * stability / 100.0)
                        buy_total_qty += qty
                    else:
                        qty = abs(t.get('net_s', net))
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
    # REVERSAL: 隔日沖賣出 (net_score > 10) 且 買賣指數為正 (代表買方比賣方更「穩重」)
    if net_score > 10 and bs_diff_index > 0:
        result = {
            'type': 'REVERSAL',
            'strength': min(100, net_score * 2),
            'reason': f'REVERSAL: 淨分{net_score:.1f} 且 買賣指數正向({bs_diff_index:.2f})'
        }
    elif net_score < -10:
        result = {
            'type': 'FOLLOW',
            'strength': min(100, abs(net_score) * 2),
            'reason': f'FOLLOW: 淨分負向(隔日沖買進) {net_score:.1f}'
        }
    else:
        result = {'type': None, 'strength': 0.0, 'reason': '訊號不明顯'}

    return result

def decide_buy(momentum_score: float, dt_signal: dict, mom_threshold: float = LOOSE_BUY_SCORE_THRESHOLD) -> tuple:
    """
    給定動能分數 + 隔日沖訊號，決定是否買進及策略類型
    """
    if dt_signal['type'] == 'REVERSAL' and dt_signal['strength'] >= 25:
        return True, 'REVERSAL', dt_signal['reason']
    if dt_signal['type'] == 'FOLLOW' and dt_signal['strength'] >= 20:
        return True, 'FOLLOW', dt_signal['reason']
    if momentum_score >= mom_threshold:
        return True, 'MOMENTUM', f'動能分數 {momentum_score:.1f}'
    return False, None, ''

# =================================================================
# 主回測函數 (phased 第一版)
# =================================================================

def run_momentum_day_trading_backtest(override_config: dict = None, silent: bool = False) -> dict:
    """執行 動能 + 隔日沖 整合回測 (第一版，寬鬆參數讓交易發生)"""
    print("執行 動能 + 隔日沖 整合回測 (第一版 loose)...")

    # 1. 載入
    # 由於 stock_data_micro.json (1.2GB) 過大導致 MemoryError，
    # 且 analyze_momentum.py 內部使用 json.load()，
    # 暫時切換回 stock_data.json 進行回測，以確保基礎動能邏輯能運作。
    data = analyze_momentum.load_stock_data_wrapper('stock_data.json')
    stock_names = load_stock_names()
    micro_features = load_micro_features()
    _config = load_config()
    if override_config:
        _config.update(override_config)

    starting_cash = _config.get('STARTING_CASH', 2000000)
    weights = _config.get('WEIGHTS', DEFAULT_WEIGHTS)

    # 回測期間 (寬鬆 3 個月)
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

        # 賣出檢查 (簡單版)
        to_sell = []
        for sid, pos in list(portfolio.items()):
            if current_date not in data.get(sid, {}).get('price', {}):
                continue
            curr_price = data[sid]['price'][current_date]['close']
            gain = (curr_price - pos['avg_price']) / pos['avg_price'] if pos['avg_price'] > 0 else 0

            sell_reason = None
            if gain >= 0.08:  # 寬鬆獲利了結
                sell_reason = f"獲利了結 (+{gain:.1%})"
            elif gain <= -0.05:  # 寬鬆停損
                sell_reason = f"停損 ({gain:.1%})"
            elif (idx - all_dates.index(pos['buy_date'])) >= 5:  # 最多持 5 天
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

        # 買進檢查 (寬鬆)
        if len(portfolio) < top_n:
            analysis_date = all_dates[idx-1] if idx > 0 else current_date
            start_mom = all_dates[max(0, idx-1-20)]
            mom_results = calculate_momentum_scores(data, start_mom, analysis_date, weights=weights)

            candidates = []
            for r in mom_results[:50]:  # 寬鬆掃描前 50 檔
                sid = r['stock_id']
                if sid in portfolio or current_date not in data.get(sid, {}).get('price', {}):
                    continue
                price = data[sid]['price'][current_date]['close']
                if price < 10:  # 寬鬆價格門檻
                    continue

                mom_score = r['score']
                dt_sig = calculate_day_trading_signal(sid, analysis_date, data, micro_features)

                buy, strat, reason = decide_buy(mom_score, dt_sig, mom_threshold=buy_score_threshold)
                if buy:
                    candidates.append({
                        'sid': sid,
                        'score': mom_score,
                        'dt_strength': dt_sig['strength'],
                        'strategy': strat,
                        'reason': reason,
                        'price': price
                    })

            # 排序 (動能 + dt 強度)
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

    # 統計 (各自買入/賣出 + 總體 + 持續跟進)
    reversal_buys = [t for t in transactions if t['action'] == 'BUY' and t.get('strategy') == 'REVERSAL']
    follow_buys = [t for t in transactions if t['action'] == 'BUY' and t.get('strategy') == 'FOLLOW']
    mom_buys = [t for t in transactions if t['action'] == 'BUY' and t.get('strategy') == 'MOMENTUM']

    reversal_sells = [t for t in transactions if t['action'] == 'SELL' and t.get('strategy') == 'REVERSAL']
    follow_sells = [t for t in transactions if t['action'] == 'SELL' and t.get('strategy') == 'FOLLOW']
    mom_sells = [t for t in transactions if t['action'] == 'SELL' and t.get('strategy') == 'MOMENTUM']

    rev_gains = [t['gain'] for t in reversal_sells]
    fol_gains = [t['gain'] for t in follow_sells]
    mom_gains = [t['gain'] for t in mom_sells]

    all_sells = [t for t in transactions if t['action'] == 'SELL']
    all_gains = [t['gain'] for t in all_sells]
    overall_win = len([g for g in all_gains if g > 0]) / len(all_gains) if all_gains else 0

    # 持續跟進 (REVERSAL 買後又有 FOLLOW 買)
    continued = 0
    rev_sids = set()
    for t in transactions:
        if t['action'] == 'BUY' and t.get('strategy') == 'REVERSAL':
            rev_sids.add(t['stock_id'])
        if t['action'] == 'BUY' and t.get('strategy') == 'FOLLOW' and t['stock_id'] in rev_sids:
            continued += 1

    if not silent:
        print(f"\n=== 動能 + 隔日沖 整合回測結果 (第一版 loose) ===")
        print(f"回測期間: {all_dates[start_idx]} ~ {all_dates[-1]} ({days}天)")
        print(f"初始資金: {starting_cash:,.0f}  最終價值: {final_value:,.0f}")
        print(f"總報酬率: {total_return:.2%}  年化: {annualized:.2%}")
        print(f"交易次數: {len(transactions)}")

        print(f"\n策略分析 (買入/賣出):")
        mom_wr = (len([g for g in mom_gains if g>0])/len(mom_gains) if mom_gains else 0)
        mom_avg = (sum(mom_gains)/len(mom_gains) if mom_gains else 0)
        rev_wr = (len([g for g in rev_gains if g>0])/len(rev_gains) if rev_gains else 0)
        rev_avg = (sum(rev_gains)/len(rev_gains) if rev_gains else 0)
        fol_wr = (len([g for g in fol_gains if g>0])/len(fol_gains) if fol_gains else 0)
        fol_avg = (sum(fol_gains)/len(fol_gains) if fol_gains else 0)
        print(f"  MOMENTUM: 買 {len(mom_buys)} / 賣 {len(mom_sells)} | 賣出勝率 {mom_wr:.1%} 平均 {mom_avg:.2%}")
        print(f"  REVERSAL: 買 {len(reversal_buys)} / 賣 {len(reversal_sells)} | 賣出勝率 {rev_wr:.1%} 平均 {rev_avg:.2%}")
        print(f"  FOLLOW:   買 {len(follow_buys)} / 賣 {len(follow_sells)} | 賣出勝率 {fol_wr:.1%} 平均 {fol_avg:.2%}")

        overall_avg = (sum(all_gains)/len(all_gains) if all_gains else 0)
        print(f"\n總體: 買 {len([t for t in transactions if t['action']=='BUY'])} / 賣 {len(all_sells)} | 整體勝率 {overall_win:.1%} 賣出平均 {overall_avg:.2%}")
        print(f"反彈後持續跟進次數: {continued}")

    result = {
        'total_return': total_return,
        'annualized_return': annualized,
        'final_value': final_value,
        'transactions': transactions,
        'days': days,
        'momentum_performance': {
            'buys': len(mom_buys), 'sells': len(mom_sells),
            'win_rate': len([g for g in mom_gains if g > 0]) / len(mom_gains) if mom_gains else 0,
            'avg_return': sum(mom_gains) / len(mom_gains) if mom_gains else 0
        },
        'reversal_performance': {
            'buys': len(reversal_buys), 'sells': len(reversal_sells),
            'win_rate': len([g for g in rev_gains if g > 0]) / len(rev_gains) if rev_gains else 0,
            'avg_return': sum(rev_gains) / len(rev_gains) if rev_gains else 0
        },
        'follow_performance': {
            'buys': len(follow_buys), 'sells': len(follow_sells),
            'win_rate': len([g for g in fol_gains if g > 0]) / len(fol_gains) if fol_gains else 0,
            'avg_return': sum(fol_gains) / len(fol_gains) if fol_gains else 0
        },
        'overall': {
            'total_buys': len([t for t in transactions if t['action'] == 'BUY']),
            'total_sells': len(all_sells),
            'win_rate': overall_win,
            'avg_gain_on_sells': sum(all_gains) / len(all_gains) if all_gains else 0,
            'continued_follow_after_reversal': continued
        }
    }

    # 自動存檔 (時間戳)
    try:
        os.makedirs(RESULT_DIR, exist_ok=True)
        ts = datetime.now().strftime("%y%m%d_%H%M")
        fpath = os.path.join(RESULT_DIR, f"momentum_day_trading_{ts}.json")
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        if not silent:
            print(f"[SAVE] 結果已存檔: {fpath}")
    except Exception as e:
        if not silent:
            print(f"[WARN] 存檔失敗: {e}")

    return result

if __name__ == "__main__":
    print("=== 動能 + 隔日沖 整合回測 (第一版) ===")
    result = run_momentum_day_trading_backtest()
    if result:
        print(f"\n最終年化報酬率: {result['annualized_return']:.2%}")
        print(f"總體勝率: {result['overall']['win_rate']:.1%}")
        print("詳細結果已存檔至 v1/result (時間戳 json)")
        print("請查看輸出與存檔，確認 base 是否能動，然後告訴我下一步調整方向。")