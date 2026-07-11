#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sqlite3
import os

DB_PATH = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"

def debug_check_columns():
    if not os.path.exists(DB_PATH):
        print(f"找不到資料庫: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("=== 檢查 broker_details 欄位 ===")
    cursor.execute("PRAGMA table_info(broker_details)")
    columns = [row['name'] for row in cursor.fetchall()]
    print(f"欄位列表: {columns}")
    
    print("\n=== 檢查第一筆資料內容 ===")
    cursor.execute("SELECT * FROM broker_details LIMIT 1")
    row = cursor.fetchone()
    if row:
        for col in columns:
            print(f"{col}: {row[col]} (型態: {type(row[col])})")
            
    conn.close()

if __name__ == "__main__":
    debug_check_columns()
