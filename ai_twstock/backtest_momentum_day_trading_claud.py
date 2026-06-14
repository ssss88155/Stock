#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
backtest_momentum_day_trading.py
聖盃模式 5.1 雙軌平行版 (順勢軌道 / 逆勢軌道 各自獨立開關與評分)

=================================================================
架構說明
=================================================================
run_backtest()
├── 1. 資料載入層 (load_all_data / load_stock_info / micro_features)
├── 2. 每日掃描迴圈
│   ├── [出場判定]
│   │     1. 盤中停損 (用當日最低價判定，避免「盤中重摔收盤拉回」的生存者偏差)
│   │     2. 分批減碼 (PARTIAL_EXIT_GAIN，收盤價)
│   │     3. 移動停損 / 保本出場 (收盤價)
│   │     4. 到期出場 (HOLD_DAYS)
│   └── [進場判定] (當持倉 < TOP_N)
│       ├── get_top_sectors()              ← 兩軌共用：前3強產業
│       ├──【順勢軌道 BREAKOUT_TRACK】
│       │     evaluate_breakout_candidate()
│       │       → check_liquidity()        ← 流動性濾網 (MIN_TRADING_VALUE)
│       │       → calculate_momentum_score()
│       │       → decide_buy_breakout()    (HOLY_GRAIL_BREAKOUT / VOLATILITY / SCALPING)
│       │     → 依 score 排序，取前 TOP_N_BREAKOUT
│       │
│       └──【逆勢軌道 DIP_TRACK】
│             evaluate_dip_candidate()
│               → check_liquidity()        ← 流動性濾網 (MIN_TRADING_VALUE)
│               → decide_buy_dip()         (WASH_OUT_DIP)
│               → calculate_dip_score()
│             → 依 dip_score 排序，取前 TOP_N_DIP
│
│       兩軌候選各自獨立排序、獨立取額，最後合併買入 (受 available_slots 限制)
│
└── 3. 結果輸出層
      ├── final_v: 用 get_last_available_price() 結算，避免末日停牌股估值歸零
      ├── mode_stats
      └── transaction_log.txt
=================================================================

v5.1 修正項目:
  1. 出場判定改用「盤中最低價」偵測停損，避免回測過度樂觀 (生存者偏差)
  2. 期末資產結算改用「最後一個可得收盤價」，避免末日停牌股價值歸零
  3. 新增 check_liquidity() 流動性濾網，套用至兩軌候選評估，過濾低成交額殭屍股
  4. [BUG FIX] prev_gain 改用「昨日收盤 vs 前日收盤」，精準捕捉跳空開低洗盤
  5. [PERF]    全市場個股 sorted_dates / date_to_idx 預處理，消滅每日迴圈 O(N) 重複排序瓶頸
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
    'ENABLE_SECTOR_SCAN': True,
    'ENABLE_DIP_SCORE': True,
    'TRACK_SWITCH': {
        'BREAKOUT_TRACK': False,
        'DIP_TRACK': True,
    },
    'STRATEGY_SWITCH': {
        'HOLY_GRAIL_BREAKOUT': False,
        'VOLATILITY': False,
        'SCALPING': False,
        'WASH_OUT_DIP': True,
        'LOW_ENTRY': False,
    }
}

TRACK_ALLOCATION = {
    'TOP_N_BREAKOUT': 0,
    'TOP_N_DIP': 8,
}

HOLY_GRAIL_PARAMS = {'PREV_GAIN_THRESHOLD': 0.05, 'VOL_DRY_RATIO': 0.65, 'WINNER_LOCK_RATIO': 0.15, 'PRICE_SUPPORT_LEVEL': 0.97, 'USE_MARKET_FILTER': True}
STRATEGY_MODES = {
    'HOLY_GRAIL_BREAKOUT': {'STOP_LOSS': -0.05, 'TAKE_PROFIT': 9.99, 'BREAK_EVEN_TRIGGER': 0.06, 'HOLD_DAYS': 20, 'PARTIAL_EXIT_GAIN': 0.10, 'TRAILING_STOP_NORMAL': 0.08},
    'VOLATILITY': {'STOP_LOSS': -0.08, 'TAKE_PROFIT': 9.99, 'BREAK_EVEN_TRIGGER': 0.05, 'HOLD_DAYS': 10},
    'SCALPING': {'STOP_LOSS': -0.03, 'TAKE_PROFIT': 0.06, 'BREAK_EVEN_TRIGGER': 0.03, 'HOLD_DAYS': 1},
    'WASH_OUT_DIP': {'STOP_LOSS': -0.05, 'TAKE_PROFIT': 0.10, 'HOLD_DAYS': 5},
    'LOW_ENTRY': {'STOP_LOSS': -0.05, 'TAKE_PROFIT': 9.99, 'BREAK_EVEN_TRIGGER': 0.08, 'HOLD_DAYS': 40, 'MAX_MOMENTUM': 45}
}
BACKTEST_CONFIG = {'STARTING_CASH': 2000000, 'TOP_N': 8, 'MIN_TRADING_VALUE': 30000000}

try:
    from holy_grail_config import (
        HOLY_GRAIL_PARAMS as HGP, STRATEGY_MODES as SM,
        BACKTEST_CONFIG as BC, PIPELINE_CONTROL as PC, TRACK_ALLOCATION as TA,
    )
    HOLY_GRAIL_PARAMS.update(HGP); STRATEGY_MODES.update(SM); BACKTEST_CONFIG.update(BC)
    for k, v in PC.items():
        if isinstance(v, dict) and isinstance(PIPELINE_CONTROL.get(k), dict): PIPELINE_CONTROL[k].update(v)
        else: PIPELINE_CONTROL[k] = v
    TRACK_ALLOCATION.update(TA)
except ImportError:
    pass

DEFAULT_WEIGHTS = {'WEIGHT_GAIN': 40, 'WEIGHT_VOLUME': 10, 'WEIGHT_FOREIGN': 10, 'WEIGHT_SITC': 10, 'WEIGHT_VCP': 10, 'WEIGHT_BREAKOUT': 10, 'WEIGHT_HANDOVER': 40, 'MIN_SCORE_TO_PRINT': 60, 'MIN_TRADING_VALUE': BACKTEST_CONFIG['MIN_TRADING_VALUE']}

MICRO_FEATURE_FILE = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
DB_PATH = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"
RESULT_DIR = r"C:\jupyter_notebook\ai_twstock\backtest_micro_simulate\v1\result"
CACHE_DIR = r"C:\jupyter_notebook\ai_twstock\backtest_micro_simulate\v1\cache"
GRIDS_CACHE_FILE = r"C:\jupyter_notebook\ai_twstock\data\Grids_0050_MA.py"

# =================================================================
# 共用指標函數 (Indicators)
# =================================================================

def check_vcp_pattern(price_data, sorted_dates, idx):
    if idx < 60: return False, 0
    lookback_dates = sorted_dates[idx - 60: idx + 1]
    prices = [price_data[d]['close'] for d in lookback_dates]
    segment_size = len(prices) // 3
    if segment_size < 5: return False, 0
    v1, v2, v3 = prices[:segment_size], prices[segment_size:segment_size * 2], prices[segment_size * 2:]
    def get_range(v): return (max(v) - min(v)) / min(v) if min(v) > 0 else 0
    r1, r2, r3 = get_range(v1), get_range(v2), get_range(v3)
    is_tightening = r1 > r2 and r2 > r3
    tightness_score = max(0, 100 * (1 - (r3 / 0.15))) if r3 < 0.15 else 0
    return is_tightening or (r1 > r3 * 2), min(100, tightness_score)


def check_handover_consolidation(price_data, sorted_dates, idx):
    if idx < 30: return False, 0
    lookback_dates = sorted_dates[idx - 10: idx + 1]
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
    """順勢軌道評分：動能越強分數越高"""
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
    逆勢軌道評分系統 2.0
    維度：跌幅深度、縮量程度、價格止跌強度、趨勢底氣、券商籌碼、動能交叉
    """
    score = 0
    # 1. 跌幅深度 (權重 15)
    score += min(15, abs(details['prev_gain']) * 150)
    # 2. 縮量程度 (權重 15)
    score += max(0, (1 - details['vol_ratio']) * 15)
    # 3. 價格止跌強度 (權重 15)
    if details['is_red_candle']: score += 15
    
    # 4. 【強勢回檔加分】趨勢底氣 (權重 20)
    if details.get('is_above_ma60', False): score += 20
    
    # 5. 【券商籌碼加分】(權重 20)
    # 邏輯：(穩重買入 - 炒作買入) 為正，代表炒作券商在賣、穩重券商在接
    broker_net = details.get('broker_manipulation_net', 0)
    if broker_net > 0:
        score += min(20, broker_net * 2)
        
    # 6. 【動能交叉加分】(權重 15)
    # 邏輯：MA5 轉折或黃金交叉
    if details.get('is_golden_cross', False): score += 15
    elif details.get('is_ma5_up', False): score += 7
        
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
    """量價背離檢查 (目前未接入決策流程，保留供未來風控擴充)"""
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
    """隔日沖風險比例 (目前未接入決策流程，保留供未來風控擴充)"""
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
    確認個股是否處於上行趨勢，並找出最近的支撐點 (逆勢軌道用)
    [PERF] 使用預處理快取 sorted_dates / date_to_idx，O(1) 查表
    """
    stock_info = data.get(sid, {})
    price_data = stock_info.get('price', {})
    sorted_dates = stock_info.get('sorted_dates', [])
    date_to_idx  = stock_info.get('date_to_idx', {})

    if date not in date_to_idx: return False, 0, False
    idx = date_to_idx[date]
    if idx < 20: return False, 0, False

    lookback_20 = sorted_dates[idx - 20:idx]
    prices_20 = [price_data[d]['close'] for d in lookback_20]
    ma20 = sum(prices_20) / 20
    curr_p = price_data[date]['close']
    support_p = min(prices_20)
    is_near_support = curr_p <= support_p * 1.07
    is_uptrend = curr_p > ma20
    return is_uptrend, support_p, is_near_support


def check_broker_dumping(sid, date, data, micro_features):
    """
    檢查是否有「隔日沖」或「短線券商」在大量倒貨
    賣方前五名中穩重指數 < -50 的券商賣壓超過今日成交量 10%，視為倒貨風險
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
    return (dumping_vol / total_vol) > 0.10


def check_bull_market(data, date):
    """大盤環境判定 (0050 站上 MA20 且 MA20 > MA60)，供順勢軌道使用"""
    is_bull_market = True
    if HOLY_GRAIL_PARAMS.get('USE_MARKET_FILTER', False) and '0050' in data:
        p0050 = data['0050'].get('price', {})
        date_to_idx = data['0050'].get('date_to_idx', {})
        sorted_0050 = data['0050'].get('sorted_dates', [])
        if date in date_to_idx:
            idx_0050 = date_to_idx[date]
            if idx_0050 >= 60:
                def get_ma_0050(n): return sum([p0050[sorted_0050[i]]['close'] for i in range(idx_0050 - n + 1, idx_0050 + 1)]) / n
                ma20 = get_ma_0050(20); ma60 = get_ma_0050(60)
                is_bull_market = p0050[date]['close'] > ma20 and ma20 > ma60
    return is_bull_market


def check_liquidity(sid, date, data, lookback=5, min_value=None):
    """
    流動性濾網：近 lookback 日平均成交金額是否達 MIN_TRADING_VALUE
    [PERF] 使用預處理快取
    """
    if min_value is None: min_value = BACKTEST_CONFIG.get('MIN_TRADING_VALUE', 0)
    if min_value <= 0: return True
    stock_info = data.get(sid, {})
    price_data  = stock_info.get('price', {})
    sorted_dates = stock_info.get('sorted_dates', [])
    date_to_idx  = stock_info.get('date_to_idx', {})
    if date not in date_to_idx: return False
    idx = date_to_idx[date]
    start = max(0, idx - lookback + 1)
    window = sorted_dates[start:idx + 1]
    if not window: return False
    values = [price_data[d]['close'] * price_data[d].get('Trading_Volume', 0) for d in window]
    return (sum(values) / len(values)) >= min_value


# =================================================================
# 雙軌候選評估 (Track Evaluators)
# =================================================================

def get_top_sectors(data, analysis_date, stock_industries, top_k=3, min_samples=5):
    """
    兩軌共用：依過去20日漲幅找出最強前 top_k 個產業
    [PERF] 使用預處理快取
    """
    if not PIPELINE_CONTROL.get('ENABLE_SECTOR_SCAN', True): return None
    sector_scores = defaultdict(list)
    for sid, details in data.items():
        if analysis_date not in details['price']: continue
        p_data = details['price']
        date_to_idx = details.get('date_to_idx', {})
        sorted_d    = details.get('sorted_dates', [])
        if analysis_date not in date_to_idx: continue
        a_idx = date_to_idx[analysis_date]
        if a_idx < 20: continue
        start_p = p_data[sorted_d[a_idx - 20]]['close']
        if start_p <= 0: continue
        gain_20 = (p_data[analysis_date]['close'] - start_p) / start_p
        ind = stock_industries.get(sid, "其他")
        if ind != "其他": sector_scores[ind].append(gain_20)
    avg_sector_gain = {ind: sum(g) / len(g) for ind, g in sector_scores.items() if len(g) >= min_samples}
    return [x[0] for x in sorted(avg_sector_gain.items(), key=lambda x: x[1], reverse=True)[:top_k]]


def decide_buy_breakout(momentum_score, sid, date, data, micro_features):
    """順勢軌道判定：HOLY_GRAIL_BREAKOUT / VOLATILITY / SCALPING"""
    switches = PIPELINE_CONTROL['STRATEGY_SWITCH']
    if not any(switches.get(s, False) for s in ['HOLY_GRAIL_BREAKOUT', 'VOLATILITY', 'SCALPING']):
        return False, None

    stock_info   = data.get(sid, {})
    price_data   = stock_info.get('price', {})
    sorted_dates = stock_info.get('sorted_dates', [])
    date_to_idx  = stock_info.get('date_to_idx', {})
    if date not in date_to_idx: return False, None
    idx = date_to_idx[date]
    if idx < 20: return False, None

    prev_date = sorted_dates[idx - 1]
    curr_p, prev_p = price_data[date], price_data[prev_date]
    prev_gain = (prev_p['close'] - prev_p['open']) / prev_p['open'] if prev_p['open'] > 0 else 0
    curr_vol = curr_p.get('Trading_Volume', 0)
    prev_vol = prev_p.get('Trading_Volume', 0)
    is_bull_market = check_bull_market(data, date)

    # A. HOLY_GRAIL_BREAKOUT
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
        if (prev_gain > HOLY_GRAIL_PARAMS['PREV_GAIN_THRESHOLD'] and is_vol_dry and is_winner_locked
                and curr_p['close'] >= prev_p['close'] * HOLY_GRAIL_PARAMS['PRICE_SUPPORT_LEVEL']):
            return True, ('HOLY_GRAIL_BREAKOUT', momentum_score)

    # B. VOLATILITY
    if switches.get('VOLATILITY', False) and is_bull_market:
        if momentum_score > 75 and curr_p['close'] > curr_p['open']:
            return True, ('VOLATILITY', momentum_score)

    # C. SCALPING
    if switches.get('SCALPING', False):
        dt_sig = calculate_day_trading_signal(sid, date, data, micro_features)
        if dt_sig['type'] == 'REVERSAL' and dt_sig['strength'] > 50:
            return True, ('SCALPING', dt_sig['strength'])

    return False, None


def decide_buy_dip(sid, date, data, micro_features):
    """
    逆勢軌道判定：WASH_OUT_DIP
    [UPGRADE]  加入位階過濾 (60日高點回檔 < 15% 拒絕)
    [UPGRADE]  右側 K 線升級 (下影線 >= 實體 1.2 倍)
    [BUG FIX]  prev_gain 改用「昨日收盤 vs 前日收盤」，正確捕捉跳空開低洗盤
    [PERF]     使用預處理快取 sorted_dates / date_to_idx
    """
    switches = PIPELINE_CONTROL['STRATEGY_SWITCH']
    if not switches.get('WASH_OUT_DIP', False): return False, None

    stock_info   = data.get(sid, {})
    price_data   = stock_info.get('price', {})
    sorted_dates = stock_info.get('sorted_dates', [])
    date_to_idx  = stock_info.get('date_to_idx', {})

    if date not in date_to_idx: return False, None
    idx = date_to_idx[date]
    if idx < 60: return False, None  # 需要 60 日高點位階過濾

    # 1. 【位階過濾】距離 60 日高點回檔 < 10% 拒絕進場 (放寬：15% -> 10%)
    lookback_60 = sorted_dates[idx-60:idx]
    max_p_60 = max(price_data[d]['max'] for d in lookback_60)
    curr_close = price_data[date]['close']
    if curr_close > (max_p_60 * 0.90):
        return False, None

    prev_date   = sorted_dates[idx - 1]
    prev_2_date = sorted_dates[idx - 2]
    curr_p  = price_data[date]
    prev_p  = price_data[prev_date]
    prev_2_p = price_data[prev_2_date]

    # [BUG FIX] 用「昨日收盤 vs 前日收盤」計算實際跌幅，避免跳空開低被忽略
    prev_gain = (prev_p['close'] - prev_2_p['close']) / prev_2_p['close'] if prev_2_p['close'] > 0 else 0
    curr_vol = curr_p.get('Trading_Volume', 0)
    prev_vol = prev_p.get('Trading_Volume', 0)

    is_wash_out_base = prev_gain < -0.03 and curr_vol < prev_vol * 0.8
    if not is_wash_out_base: return False, None

    # 2. 【右側 K 線升級】紅K + 下影線 >= 實體 1.2 倍
    body = abs(curr_p['close'] - curr_p['open'])
    # 修正 KeyError: 'low'，SQL 載入時 key 為 'min'
    curr_low = curr_p.get('min', curr_p['close'])
    lower_shadow = min(curr_p['open'], curr_p['close']) - curr_low
    is_red = curr_p['close'] > curr_p['open']
    # 2. 【右側 K 線升級】紅K + 下影線 >= 實體 0.8 倍 (放寬：1.2 -> 0.8)
    is_strong_reversal = is_red and lower_shadow >= (body * 0.8)
    
    if not is_strong_reversal:
        return False, None

    _is_uptrend, _support_p, is_near_support = check_uptrend_and_support(sid, date, data)
    is_dumping = check_broker_dumping(sid, date, data, micro_features)

    if is_near_support and not is_dumping:
        dip_score = 0
        if PIPELINE_CONTROL.get('ENABLE_DIP_SCORE', True):
            dip_details = {
                'prev_gain': prev_gain,
                'vol_ratio': (curr_vol / prev_vol) if prev_vol > 0 else 0,
                'is_red_candle': is_red,
            }
            dip_score = calculate_dip_score(dip_details)
        return True, ('WASH_OUT_DIP', dip_score)

    return False, None


def evaluate_breakout_candidate(sid, analysis_date, current_date, data, micro_features, stock_industries, top_sectors):
    """順勢軌道：單一個股候選評估，回傳候選 dict 或 None"""
    if top_sectors is not None and stock_industries.get(sid) not in top_sectors: return None
    details = data[sid]
    if analysis_date not in details['price'] or current_date not in details['price']: return None
    if not check_liquidity(sid, analysis_date, data): return None

    p_data      = details['price']
    sorted_d    = details.get('sorted_dates', [])
    date_to_idx = details.get('date_to_idx', {})
    if analysis_date not in date_to_idx: return None
    a_idx = date_to_idx[analysis_date]
    if a_idx < 20: return None

    start_p = p_data[sorted_d[a_idx - 20]]['close']
    gain_20 = (p_data[analysis_date]['close'] - start_p) / start_p if start_p > 0 else 0
    vcp_ok, vcp_s = check_vcp_pattern(p_data, sorted_d, a_idx)
    hand_ok, hand_s = check_handover_consolidation(p_data, sorted_d, a_idx)
    inst = details['institutional'].get(analysis_date, {})
    f_net = inst.get('Foreign_Investor', {}).get('buy', 0)
    s_net = inst.get('Investment_Trust', {}).get('buy', 0)
    mom_details = {'gain': gain_20, 'vol_ratio': 1.5, 'foreign_days': 3 if f_net > 0 else 0, 'sitc_ratio': 1.2 if s_net > 0 else 0, 'vcp_ok': vcp_ok, 'vcp_score': vcp_s, 'handover_ok': hand_ok, 'handover_score': hand_s}
    score = calculate_momentum_score(mom_details)
    buy, res = decide_buy_breakout(score, sid, analysis_date, data, micro_features)
    if not buy: return None
    strat, final_score = res
    return {'sid': sid, 'score': final_score, 'mode': strat, 'price': p_data[current_date]['open'], 'strategy': strat}


def evaluate_dip_candidate(sid, analysis_date, current_date, data, micro_features, stock_industries, top_sectors):
    """逆勢軌道：單一個股候選評估，回傳候選 dict 或 None"""
    if top_sectors is not None and stock_industries.get(sid) not in top_sectors: return None
    details = data[sid]
    if analysis_date not in details['price'] or current_date not in details['price']: return None
    if not check_liquidity(sid, analysis_date, data): return None
    p_data = details['price']
    buy, res = decide_buy_dip(sid, analysis_date, data, micro_features)
    if not buy: return None
    strat, final_score = res
    return {'sid': sid, 'score': final_score, 'mode': strat, 'price': p_data[current_date]['open'], 'strategy': strat}


def scan_candidates(data, analysis_date, current_date, portfolio, stock_industries, micro_features):
    """
    每日候選掃描：兩軌平行，各自獨立排序
    回傳 (breakout_candidates, dip_candidates)，皆已依分數高到低排序
    """
    top_sectors = get_top_sectors(data, analysis_date, stock_industries)
    breakout_enabled = PIPELINE_CONTROL['TRACK_SWITCH'].get('BREAKOUT_TRACK', False)
    dip_enabled      = PIPELINE_CONTROL['TRACK_SWITCH'].get('DIP_TRACK', False)
    breakout_candidates, dip_candidates = [], []
    for sid, details in data.items():
        if sid in portfolio: continue
        if breakout_enabled:
            c = evaluate_breakout_candidate(sid, analysis_date, current_date, data, micro_features, stock_industries, top_sectors)
            if c: breakout_candidates.append(c)
        if dip_enabled:
            c = evaluate_dip_candidate(sid, analysis_date, current_date, data, micro_features, stock_industries, top_sectors)
            if c: dip_candidates.append(c)
    breakout_candidates.sort(key=lambda x: x['score'], reverse=True)
    dip_candidates.sort(key=lambda x: x['score'], reverse=True)
    return breakout_candidates, dip_candidates


def get_last_available_price(sid, data, all_dates):
    """期末結算用：回溯找最後一個有資料的收盤價，避免停牌股估值歸零"""
    price_data = data.get(sid, {}).get('price', {})
    if not price_data: return 0
    for d in reversed(all_dates):
        if d in price_data: return price_data[d]['close']
    return 0


def update_market_grids_cache(all_dates):
    """
    整合計算邏輯：計算 Market Breadth 與 0050 Drawdown 並更新快取檔案
    """
    print("正在從 SQL 載入資料進行大盤指標計算...")
    import sqlite3
    import pprint
    conn = sqlite3.connect(DB_PATH)
    
    # 1. 載入 0050 資料計算 Drawdown
    query_0050 = "SELECT date, close, high FROM daily_prices WHERE stock_id = '0050' ORDER BY date"
    df_0050 = pd.read_sql(query_0050, conn)
    
    twse_dd_60 = {}
    if not df_0050.empty:
        df_0050['peak_60'] = df_0050['high'].rolling(window=60, min_periods=1).max()
        df_0050['dd_60'] = (df_0050['close'] - df_0050['peak_60']) / df_0050['peak_60']
        twse_dd_60 = df_0050.set_index('date')['dd_60'].to_dict()

    # 2. 載入全市場資料計算 Market Breadth
    query_all = "SELECT date, stock_id, close FROM daily_prices WHERE date >= '2025-01-01' ORDER BY date"
    df_all = pd.read_sql(query_all, conn)
    conn.close()

    print("正在計算全市場 MA60 與 Market Breadth...")
    df_pivot = df_all.pivot(index='date', columns='stock_id', values='close')
    df_ma60 = df_pivot.rolling(window=60).mean()
    df_above = (df_pivot > df_ma60).astype(float)
    
    if '0050' in df_above.columns:
        df_above = df_above.drop(columns=['0050'])
    
    market_breadth = df_above.mean(axis=1, skipna=True).dropna().to_dict()

    # 3. 封裝資料
    grids_data = {
        'market_breadth': market_breadth,
        'twse_dd_60': twse_dd_60,
        'last_update': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'description': {
            'market_breadth': '全市場(不含0050)收盤價站上 60日均線(MA60) 的家數比例。',
            'twse_dd_60': '0050 距離過去 60 個交易日最高價(High)的回檔幅度。'
        }
    }

    # 4. 寫入檔案 (具備縮排與註解)
    print(f"正在更新快取檔案: {GRIDS_CACHE_FILE}...")
    with open(GRIDS_CACHE_FILE, 'w', encoding='utf-8') as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write("\"\"\"\n各項數值意義：\n")
        f.write("1. market_breadth: 市場寬度。代表全市場有多少比例的股票站上季線(MA60)。\n")
        f.write("2. twse_dd_60: 0050 波段回檔深度。\n\"\"\"\n\n")
        f.write("GRIDS_DATA = ")
        f.write(pprint.pformat(grids_data, indent=4, width=120, sort_dicts=True))
        f.write("\n")
    
    return market_breadth, twse_dd_60


def preprocess_market_indicators(data, all_dates):
    """
    預處理 Market Breadth 與 0050 Drawdown
    自動判斷是否需要更新快取
    """
    market_breadth = {}
    twse_dd_60 = {}
    
    # 1. 嘗試載入現有快取
    if os.path.exists(GRIDS_CACHE_FILE):
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("grids_cache", GRIDS_CACHE_FILE)
            grids_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(grids_module)
            grids_data = getattr(grids_module, 'GRIDS_DATA', {})
            market_breadth = grids_data.get('market_breadth', {})
            twse_dd_60 = grids_data.get('twse_dd_60', {})
        except Exception as e:
            print(f"[WARN] 載入快取失敗，將重新計算: {e}")

    # 2. 檢查日期是否完整 (檢查最後一天即可)
    last_date = all_dates[-1]
    if last_date not in market_breadth or last_date not in twse_dd_60:
        print(f"快取資料不完整 (缺失日期: {last_date})，觸發自動更新...")
        market_breadth, twse_dd_60 = update_market_grids_cache(all_dates)
    else:
        print(f"成功載入大盤指標快取 (最後更新日期: {last_date})")

    return market_breadth, twse_dd_60


# =================================================================
# 資料載入
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
    cache_files = [f for f in os.listdir(CACHE_DIR) if f.startswith("data_cache_") and f.endswith(".pkl")]
    best_cache = None
    if cache_files:
        valid_caches = [(f.replace("data_cache_", "").replace(".pkl", ""), f) for f in cache_files]
        valid_caches = [(c, f) for c, f in valid_caches if c <= start_date]
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


# =================================================================
# 回測引擎
# =================================================================

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

    # ----------------------------------------------------------------
    # [PERF] 預處理全市場個股日期索引，消滅每日迴圈內的重複排序 O(N) 瓶頸
    # ----------------------------------------------------------------
    print("正在預處理全市場個股日期索引與查表...")
    for sid in data:
        if 'price' in data[sid] and data[sid]['price']:
            s_dates = sorted(data[sid]['price'].keys())
            data[sid]['sorted_dates'] = s_dates
            data[sid]['date_to_idx']  = {d: i for i, d in enumerate(s_dates)}

    # ----------------------------------------------------------------
    # [NEW] 預處理 Market Breadth 與 0050 Drawdown
    # ----------------------------------------------------------------
    market_breadth, twse_dd_60 = preprocess_market_indicators(data, all_dates)

    print(f"開始回測: {all_dates[start_idx]} -> {all_dates[-1]}")
    print(f"軌道設定: BREAKOUT_TRACK={PIPELINE_CONTROL['TRACK_SWITCH'].get('BREAKOUT_TRACK')} "
          f"(名額={TRACK_ALLOCATION['TOP_N_BREAKOUT']}) | "
          f"DIP_TRACK={PIPELINE_CONTROL['TRACK_SWITCH'].get('DIP_TRACK')} "
          f"(名額={TRACK_ALLOCATION['TOP_N_DIP']})")

    for idx in range(start_idx, len(all_dates)):
        t_day_start = time.time()
        current_date = all_dates[idx]

        # ------------------------------------------------------------
        # [出場判定]
        # ------------------------------------------------------------
        to_sell_list = []
        for sid, pos in list(portfolio.items()):
            if current_date not in data[sid]['price']: continue
            day_price = data[sid]['price'][current_date]
            curr_p    = day_price['close']
            curr_open = day_price.get('open', curr_p)
            curr_low  = day_price.get('min', curr_p)

            gain      = (curr_p    - pos['avg_price']) / pos['avg_price']
            low_gain  = (curr_low  - pos['avg_price']) / pos['avg_price']
            open_gain = (curr_open - pos['avg_price']) / pos['avg_price']

            if 'max_gain' not in pos or gain > pos['max_gain']: pos['max_gain'] = gain
            mode = pos['mode']; params = STRATEGY_MODES.get(mode, STRATEGY_MODES['HOLY_GRAIL_BREAKOUT'])
            sell_reason = None; sell_ratio = 1.0; exit_price = curr_p; realized_gain = gain

            # 1. 盤中停損 (最高優先)：用最低價判定是否曾觸及停損價
            if low_gain <= params['STOP_LOSS']:
                sell_reason = f"停損({mode})"
                stop_price  = pos['avg_price'] * (1 + params['STOP_LOSS'])
                exit_price  = curr_open if open_gain <= params['STOP_LOSS'] else stop_price
                realized_gain = (exit_price - pos['avg_price']) / pos['avg_price']

            # 2. 分批減碼 (收盤價)
            if not sell_reason and mode in ['VOLATILITY', 'LOW_ENTRY', 'HOLY_GRAIL_BREAKOUT'] and not pos.get('half_sold') and gain >= params.get('PARTIAL_EXIT_GAIN', 0.10):
                sell_reason = f"分批減碼({mode}) (+{gain:.1%})"; sell_ratio = 0.5; pos['half_sold'] = True
                exit_price = curr_p; realized_gain = gain

            # 3. 移動停損 / 保本出場 (收盤價)
            if not sell_reason:
                trailing_limit = params.get('TRAILING_STOP_NORMAL', 0.08)
                if gain > 0.30: trailing_limit = params.get('TRAILING_STOP_TIGHT', 0.04)
                if gain < (pos['max_gain'] - trailing_limit):
                    sell_reason = f"移動停損({mode})"
                elif pos.get('max_gain', 0) > params.get('BREAK_EVEN_TRIGGER', 0.05) and gain < 0.02:
                    sell_reason = f"保本({mode})"
                if sell_reason: exit_price = curr_p; realized_gain = gain

            # 4. 到期出場 (收盤價)
            max_days = params.get('HOLD_DAYS', 10)
            if mode == 'VOLATILITY' and pos.get('half_sold'): max_days = 30
            if not sell_reason and (idx - all_dates.index(pos['buy_date'])) >= max_days:
                sell_reason = f"到期({mode})"; exit_price = curr_p; realized_gain = gain

            if sell_reason:
                qty = int(pos['shares'] * sell_ratio); cash += qty * exit_price * 0.998
                transactions.append({'date': current_date, 'sid': sid, 'action': 'SELL', 'gain': realized_gain, 'reason': sell_reason, 'price': exit_price, 'mode': mode})
                if qty >= pos['shares']: to_sell_list.append(sid)
                else: pos['shares'] -= qty
        for sid in to_sell_list: del portfolio[sid]

        # ------------------------------------------------------------
        # [進場判定] 雙軌平行掃描 (優化版)
        # ------------------------------------------------------------
        # 1. 動態計算當前總淨值 (Total Equity)
        current_portfolio_value = sum(p['shares'] * data[s]['price'][current_date]['close']
                                    for s, p in portfolio.items() if current_date in data[s]['price'])
        total_equity = cash + current_portfolio_value
        
        # 2. 資金平準法：計算單一車位預算
        available_slots = max(0, top_n - len(portfolio))
        if available_slots > 0:
            max_budget_by_equity = total_equity * 0.20
            budget_by_cash = cash / available_slots
            buy_budget_per_slot = min(max_budget_by_equity, budget_by_cash) * 0.95
        else:
            buy_budget_per_slot = 0

        if available_slots > 0:
            analysis_date = all_dates[idx - 1]
            
            # 3. 動態雙軌車位分配 (基於 Market Breadth)
            pct_above_ma60 = market_breadth.get(analysis_date, 0.5)
            raw_breakout_slots = round(top_n * pct_above_ma60)
            max_breakout_slots = max(1, min(top_n - 1, raw_breakout_slots))
            
            # 4. Drawdown Grids 階梯式解鎖逆勢上限
            m_dd = twse_dd_60.get(analysis_date, 0)
            # 3. Drawdown Grids 階梯式解鎖逆勢上限 (放寬平時上限：1 -> 2)
            if m_dd >= -0.03:
                max_dip_limit = 2
            elif -0.07 <= m_dd < -0.03:
                max_dip_limit = 3
            else:
                max_dip_limit = 5
            
            # 最終逆勢上限取 (剩餘總額度) 與 (階梯解鎖額度) 的小值
            max_dip_slots = min(max_dip_limit, top_n - max_breakout_slots)

            breakout_candidates, dip_candidates = scan_candidates(
                data, analysis_date, current_date, portfolio, stock_industries, micro_features
            )
            
            # 統計目前佔用
            curr_breakout_count = len([s for s, p in portfolio.items() if p['mode'] in ['HOLY_GRAIL_BREAKOUT', 'VOLATILITY', 'SCALPING']])
            curr_dip_count = len([s for s, p in portfolio.items() if p['mode'] in ['WASH_OUT_DIP']])
            
            # 算出今日可買名額
            n_breakout_avail = max(0, max_breakout_slots - curr_breakout_count)
            n_dip_avail = max(0, max_dip_slots - curr_dip_count)
            
            # 5. 每日進場總量限制 (DAILY_DIP_LIMIT = 2)
            DAILY_DIP_LIMIT = 2
            n_dip_to_buy = min(n_dip_avail, len(dip_candidates), DAILY_DIP_LIMIT, available_slots)
            n_breakout_to_buy = min(n_breakout_avail, len(breakout_candidates), available_slots - n_dip_to_buy)
            
            selected = breakout_candidates[:n_breakout_to_buy] + dip_candidates[:n_dip_to_buy]

            for cand in selected:
                buy_price = cand['price']
                if buy_price <= 0: continue
                
                # 套用資金平準法算出的預算
                shares = int(buy_budget_per_slot / buy_price / 1000) * 1000
                if shares >= 1000:
                    cost = shares * buy_price * 1.002
                    if cash >= cost:
                        cash -= cost
                        portfolio[cand['sid']] = {'shares': shares, 'avg_price': buy_price, 'buy_date': current_date, 'mode': cand['mode'], 'strategy': cand.get('strategy', 'MOMENTUM')}
                        transactions.append({'date': current_date, 'sid': cand['sid'], 'action': 'BUY', 'price': buy_price, 'mode': cand['mode'], 'strategy': cand.get('strategy', 'MOMENTUM')})

        if idx % 20 == 0: print(f"[{current_date}] 每日演算耗時: {time.time()-t_day_start:.2f}s, RAM: {get_ram_usage():.1f} MB")

    # ------------------------------------------------------------
    # 結果輸出
    # ------------------------------------------------------------
    final_v = cash + sum(p['shares'] * get_last_available_price(s, data, all_dates) for s, p in portfolio.items())
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
        f.write(f"=== 交易流水帳 (聖盃模式 5.1 雙軌平行版) ===\n"); f.write(f"起始資金: {BACKTEST_CONFIG['STARTING_CASH']:,} | 最終價值: {final_v:,.0f}\n"); f.write("-" * 80 + "\n")
        for t in transactions:
            gain_str = f"{t.get('gain', 0):.1%}" if t['action'] == 'SELL' else "-"
            f.write(f"{t['date']:<12} | {t['sid']:<6} | {t['action']:<4} | {t.get('price', 0):<8.2f} | {gain_str:<8} | {t.get('reason', ''):<20}\n")


if __name__ == "__main__":
    run_backtest()