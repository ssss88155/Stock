import json
import sqlite3
import os

def inspect_elements():
    BROKER_JSON = r"C:\jupyter_notebook\ai_twstock\stock_data_micro.json"
    MICRO_FEATURE = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
    DB_PATH = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"
    
    sid = '2330'
    date = '2026-04-02'
    
    print(f"=== 檢查元素: {sid} @ {date} ===")
    
    # 1. 檢查原始 JSON 元素
    print("\n[1] 原始 JSON 賣方前 3 名元素:")
    with open(BROKER_JSON, 'r', encoding='utf-8') as f:
        # 由於檔案大，我們用搜尋的方式
        for line in f:
            if f'"{sid}"' in line:
                # 這裡簡化處理，假設能抓到該行或區塊
                # 實際上我們已經抽取過 debug 資料，直接看 debug 資料更準
                pass
    
    DEBUG_JSON = r"C:\jupyter_notebook\ai_twstock\stock_data_debug.json"
    if os.path.exists(DEBUG_JSON):
        with open(DEBUG_JSON, 'r', encoding='utf-8') as f:
            debug_data = json.load(f)
            sellers = debug_data.get(sid, {}).get('trading_daily_report', {}).get(date, {}).get('top_sellers', [])
            for s in sellers[:3]:
                print(f"    {s}")

    # 2. 檢查微特徵元素
    print("\n[2] 微特徵庫樣本 (前 5 筆):")
    with open(MICRO_FEATURE, 'r', encoding='utf-8') as f:
        features = json.load(f)
        for feat in features[:5]:
            print(f"    ID: {feat['id']} ({type(feat['id'])}), 分數: {feat.get('穩重指數')}")

    # 3. 檢查 SQL 資料庫元素
    print("\n[3] SQL 資料庫賣方元素:")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT trader_name, trader_id, net_qty, is_buy FROM broker_details WHERE stock_id=? AND date=? AND is_buy=0 LIMIT 3", (sid, date))
    for row in cursor.fetchall():
        print(f"    Name: {row[0]}, ID: {row[1]}, Qty: {row[2]}, IsBuy: {row[3]}")
    conn.close()

if __name__ == "__main__":
    inspect_elements()
