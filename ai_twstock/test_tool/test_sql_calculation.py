import sqlite3
import json
import os

def test_sql_logic():
    db_path = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"
    micro_feature_path = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
    
    # 1. 載入微特徵
    with open(micro_feature_path, 'r', encoding='utf-8') as f:
        micro_features = {str(item['id']).strip(): item for item in json.load(f)}
    
    # 2. 連接資料庫
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    sid = '2330'
    date = '2026-04-02'
    
    print(f"--- 測試標的: {sid} 日期: {date} ---")
    
    # 模擬從 SQL 抓取資料並計算
    cursor.execute("SELECT * FROM broker_details WHERE stock_id = ? AND date = ?", (sid, date))
    rows = cursor.fetchall()
    
    buy_total_weighted = 0.0
    sell_total_weighted = 0.0
    buy_total_qty = 0.0
    sell_total_qty = 0.0
    
    found_count = 0
    for row in rows:
        # 這裡模擬 calculate_day_trading_signal 內部的邏輯
        bid_s = str(row['trader_id']).strip()
        is_buy = row['is_buy']
        qty = abs(row['net_qty'])
        
        if bid_s in micro_features:
            found_count += 1
            stability = micro_features[bid_s].get('穩重指數', 0)
            weighted_score = (qty * stability / 100.0)
            
            if is_buy:
                buy_total_weighted += weighted_score
                buy_total_qty += qty
            else:
                sell_total_weighted += weighted_score
                sell_total_qty += qty
                # Debug: 印出前幾個賣方計算
                if found_count < 20 and not is_buy:
                    print(f"  [SELL] ID:{bid_s} Qty:{qty} Stability:{stability} Weighted:{weighted_score:.1f}")

    buy_idx = (buy_total_weighted / buy_total_qty) if buy_total_qty > 0 else 0
    sell_idx = (sell_total_weighted / sell_total_qty) if sell_total_qty > 0 else 0
    bs_diff = buy_idx - sell_idx
    
    print(f"\n--- 計算結果 ---")
    print(f"比對成功分點數: {found_count}")
    print(f"B_Idx: {buy_idx:.2f} (Weighted: {buy_total_weighted:.1f}, Qty: {buy_total_qty})")
    print(f"S_Idx: {sell_idx:.2f} (Weighted: {sell_total_weighted:.1f}, Qty: {sell_total_qty})")
    print(f"BS_Diff: {bs_diff:.2f}")
    
    conn.close()

if __name__ == "__main__":
    test_sql_logic()
