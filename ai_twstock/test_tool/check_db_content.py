import sqlite3
import os

def check_db():
    db_path = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"
    if not os.path.exists(db_path):
        print("DB not found")
        return
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    sid = '2330'
    date = '2026-04-02'
    
    print(f"--- 檢查 {sid} 在 {date} 的分點資料 ---")
    cursor.execute("SELECT * FROM broker_details WHERE stock_id = ? AND date = ? LIMIT 10", (sid, date))
    rows = cursor.fetchall()
    
    for row in rows:
        print(f"Trader: {row['trader_name']}, ID: {row['trader_id']}, Qty: {row['net_qty']}, IsBuy: {row['is_buy']} (Type: {type(row['is_buy'])})")
        
    cursor.execute("SELECT is_buy, COUNT(*) FROM broker_details WHERE stock_id = ? AND date = ? GROUP BY is_buy", (sid, date))
    summary = cursor.fetchall()
    print("\n--- 買賣分佈統計 ---")
    for s in summary:
        print(f"IsBuy={s[0]}: {s[1]} 筆")
        
    conn.close()

if __name__ == "__main__":
    check_db()
