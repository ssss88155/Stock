#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
holy_grail_config.py
聖盃模式 4.0 核心參數設定
"""

# 進場過濾參數 (恢復 2026 年最強版本)
HOLY_GRAIL_PARAMS = {
    'PREV_GAIN_THRESHOLD': 0.05,
    'VOL_DRY_RATIO': 0.65,
    'WINNER_LOCK_RATIO': 0.15,
    'PRICE_SUPPORT_LEVEL': 0.97,
    'USE_MARKET_FILTER': True
}

# 出場與模式參數 (優化期望值)
STRATEGY_MODES = {
    'HOLY_GRAIL_BREAKOUT': {
        'STOP_LOSS': -0.06,         # 稍微放寬停損，避免被洗
        'TAKE_PROFIT': 9.99,
        'BREAK_EVEN_TRIGGER': 0.08, # 獲利達 8% 啟動保本
        'HOLD_DAYS': 40,            # 延長持有，咬住大波段
        'PARTIAL_EXIT_GAIN': 0.15,  # 15% 減碼一半
        'TRAILING_STOP_NORMAL': 0.10, # 移動停損放寬
        'TRAILING_STOP_TIGHT': 0.05
    }
}

# 回測基礎設定
BACKTEST_CONFIG = {
    'STARTING_CASH': 2000000,
    'TOP_N': 5, # 資金集中化
    'MIN_TRADING_VALUE': 30000000,
    'TARGET_SECTORS_COUNT': 3
}
