#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
holy_grail_config.py
聖盃模式 4.0 最強獲利參數 (74.1% 版本)
"""

# 進場過濾參數
HOLY_GRAIL_PARAMS = {
    'PREV_GAIN_THRESHOLD': 0.05,    # 昨日大漲門檻
    'VOL_DRY_RATIO': 0.65,          # 今日縮量比率
    'WINNER_LOCK_RATIO': 0.15,      # 贏家鎖籌比率
    'PRICE_SUPPORT_LEVEL': 0.97,    # 價格支撐門檻
    'USE_MARKET_FILTER': True,      # 區間感應大盤濾網
}

# 出場與模式參數 (這是 74% 報酬率的關鍵)
STRATEGY_MODES = {
    'HOLY_GRAIL_BREAKOUT': {
        'STOP_LOSS': -0.05,
        'TAKE_PROFIT': 9.99,        # 讓利潤奔跑
        'BREAK_EVEN_TRIGGER': 0.06, # 獲利達 6% 啟動保本
        'HOLD_DAYS': 20,            # 波段持有
        'PARTIAL_EXIT_GAIN': 0.10,  # 10% 減碼一半 (鎖利核心)
        'TRAILING_STOP_NORMAL': 0.08 # 移動停損 (回落 8% 出場)
    },
    'VOLATILITY': {'STOP_LOSS': -0.08, 'TAKE_PROFIT': 9.99, 'BREAK_EVEN_TRIGGER': 0.05, 'HOLD_DAYS': 10},
    'SCALPING': {'STOP_LOSS': -0.03, 'TAKE_PROFIT': 0.06, 'BREAK_EVEN_TRIGGER': 0.03, 'HOLD_DAYS': 1},
    'WASH_OUT_DIP': {'STOP_LOSS': -0.03, 'TAKE_PROFIT': 0.05, 'HOLD_DAYS': 2}
}

# 回測基礎設定
BACKTEST_CONFIG = {
    'STARTING_CASH': 2000000,
    'TOP_N': 8,
    'MIN_TRADING_VALUE': 30000000,
    'TARGET_SECTORS_COUNT': 3
}
