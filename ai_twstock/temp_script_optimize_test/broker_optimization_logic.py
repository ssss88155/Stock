#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
broker_optimization_logic.py
優化券商分點演算法：加入隔日沖佔比過濾與贏家分點追蹤
"""

import os
import sys
import json
import sqlite3
import pandas as pd

def calculate_day_trader_risk(sid, date, data, micro_features):
    """
    計算隔日沖風險佔比
    邏輯：(隔日沖分點買超量) / (前十大買超分點總量)
    """
    stock_info = data.get(sid, {})
    report = stock_info.get('trading_daily_report', {}).get(date, {})
    top_buyers = report.get('top_buyers', [])
    
    if not top_buyers:
        return 0.0, "無數據"
        
    day_trader_buy_vol = 0
    total_top_buy_vol = 0
    
    for t in top_buyers:
        trader_str = str(t.get('trader', ''))
        bid = trader_str.split('/')[-1] if '/' in trader_str else trader_str
        bid_s = str(bid).strip()
        
        net_qty = abs(t.get('net', 0))
        total_top_buy_vol += net_qty
        
        # 穩重指數 < -50 通常視為強烈隔日沖
        if bid_s in micro_features:
            stability = micro_features[bid_s].get('穩重指數', 0)
            if stability < -50:
                day_trader_buy_vol += net_qty
                
    risk_ratio = day_trader_buy_vol / total_top_buy_vol if total_top_buy_vol > 0 else 0
    return risk_ratio, f"隔日沖佔比: {risk_ratio:.1%}"

def get_broker_profit_rank(db_path, sid, end_date, lookback=20):
    """
    從 SQL 計算過去 N 天該股獲利最高的分點 (贏家分點)
    """
    conn = sqlite3.connect(db_path)
    query = f"""
    SELECT trader_id, trader_name, 
           SUM(CASE WHEN is_buy = 1 THEN -net_qty * avg_price ELSE net_qty * avg_price END) as realized_profit_estimate,
           SUM(CASE WHEN is_buy = 1 THEN net_qty ELSE -net_qty END) as net_position
    FROM broker_details
    WHERE stock_id = ? AND date < ?
    GROUP BY trader_id
    ORDER BY realized_profit_estimate DESC
    LIMIT 10
    """
    df = pd.read_sql_query(query, conn, params=(sid, end_date))
    conn.close()
    return df

def refined_decide_buy(mom_score, dt_signal, risk_ratio, is_winner_buying, config):
    """
    優化後的買進決策
    """
    # 1. 硬性過濾：隔日沖佔比過高不買 (避開割韭菜)
    if risk_ratio > config.get('MAX_DAY_TRADER_RATIO', 0.4):
        return False, "RISK_HIGH", f"隔日沖佔比過高({risk_ratio:.1%})"
        
    # 2. 贏家加持：如果有贏家分點在買，放寬動能門檻
    effective_mom_threshold = config.get('MOM_THRESHOLD', 50)
    if is_winner_buying:
        effective_mom_threshold *= 0.8
        
    # 3. 綜合判斷
    if dt_signal['type'] == 'REVERSAL' and dt_signal['strength'] > 30:
        return True, "REVERSAL", "贏家反轉訊號"
        
    if mom_score >= effective_mom_threshold:
        if risk_ratio < 0.1: # 極低隔日沖，高品質動能
            return True, "MOMENTUM_PURE", "高品質純動能"
        return True, "MOMENTUM", "標準動能"
        
    return False, None, "未達標"

if __name__ == "__main__":
    # 測試邏輯
    print("Broker Optimization Logic Prototype")
    # 這裡可以加入模擬資料測試
