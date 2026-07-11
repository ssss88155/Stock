#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
holy_grail_config.py
聖盃模式 4.0 核心參數設定
"""

# 進場過濾參數
HOLY_GRAIL_PARAMS = {
    'PREV_GAIN_THRESHOLD': 0.05,    # 昨日大漲門檻
    'VOL_DRY_RATIO': 0.65,          # 今日縮量比率 (今日量 < 昨日量 * 0.65)
    'WINNER_LOCK_RATIO': 0.15,      # 贏家鎖籌比率 (今日賣 < 昨日買 * 0.15)
    'PRICE_SUPPORT_LEVEL': 0.97,    # 價格支撐門檻 (守住昨日收盤 -3%)
}

# 出場與模式參數
STRATEGY_MODES = {
    'HOLY_GRAIL_BREAKOUT': {
        'STOP_LOSS': -0.05,
        'TAKE_PROFIT': 9.99,        # 讓利潤奔跑
        'BREAK_EVEN_TRIGGER': 0.06, # 獲利達 6% 啟動保本
        'HOLD_DAYS': 20,            # 波段持有天數
        'PARTIAL_EXIT_GAIN': 0.10,  # 10% 減碼一半
        'TRAILING_STOP_NORMAL': 0.08, # 一般移動停損
        'TRAILING_STOP_TIGHT': 0.04   # 獲利 > 30% 後的緊縮停損
    }
}

# 回測基礎設定
BACKTEST_CONFIG = {
    'STARTING_CASH': 2000000,
    'TOP_N': 8,
    'MIN_TRADING_VALUE': 30000000,
    'TARGET_SECTORS_COUNT': 3
}
