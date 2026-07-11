import json
import sqlite3
import os
import ijson
import time

def create_db_old_logic(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('PRAGMA synchronous=NORMAL;')
    
    cursor.execute('CREATE TABLE IF NOT EXISTS daily_prices (stock_id TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, foreign_buy INTEGER, sitc_buy INTEGER, dealer_buy INTEGER, PRIMARY KEY (stock_id, date))')
    cursor.execute('CREATE TABLE IF NOT EXISTS broker_details (stock_id TEXT, date TEXT, trader_name TEXT, trader_id TEXT, net_qty INTEGER, avg_price REAL, is_buy BOOLEAN, PRIMARY KEY (stock_id, date, trader_id, is_buy))')
    
    # 舊邏輯：先建立索引
    print("[舊邏輯] 正在匯入前建立索引...")
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_lookup ON broker_details (stock_id, date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_query ON broker_details (stock_id, date, is_buy, net_qty DESC)')
    
    cursor.execute('DELETE FROM daily_prices')
    cursor.execute('DELETE FROM broker_details')
    conn.commit()
    return conn

def create_db_new_logic(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('PRAGMA synchronous=NORMAL;')
    
    cursor.execute('CREATE TABLE IF NOT EXISTS daily_prices (stock_id TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, foreign_buy INTEGER, sitc_buy INTEGER, dealer_buy INTEGER, PRIMARY KEY (stock_id, date))')
    cursor.execute('CREATE TABLE IF NOT EXISTS broker_details (stock_id TEXT, date TEXT, trader_name TEXT, trader_id TEXT, net_qty INTEGER, avg_price REAL, is_buy BOOLEAN, PRIMARY KEY (stock_id, date, trader_id, is_buy))')
    
    # 新邏輯：不先建立索引
    print("[新邏輯] 匯入前不建立索引")
    
    cursor.execute('DELETE FROM daily_prices')
    cursor.execute('DELETE FROM broker_details')
    conn.commit()
    return conn

def import_data(conn, price_json, broker_json):
    cursor = conn.cursor()
    # 匯入價格
    with open(price_json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    p_batch = []
    for sid, info in data.items():
        for date, p in info.get('price', {}).items():
            p_batch.append((sid, date, p.get('open'), p.get('max'), p.get('min'), p.get('close'), p.get('Trading_Volume'), 0, 0, 0))
    cursor.executemany('INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?,?,?,?)', p_batch)
    
    # 匯入分點 (串流)
    b_batch = []
    with open(broker_json, 'r', encoding='utf-8') as f:
        parser = ijson.kvitems(f, '')
        for sid, info in parser:
            reports = info.get('trading_daily_report', {})
            for date, report in reports.items():
                for key, is_buy in [('top_buyers', True), ('top_sellers', False)]:
                    for t in report.get(key, []):
                        trader_str = str(t.get('trader', ''))
                        t_name, t_id = trader_str.split('/') if '/' in trader_str else (trader_str, '')
                        qty = int(abs(float(t.get('net_b', t.get('net_s', t.get('net', 0))))))
                        b_batch.append((sid, date, t_name, t_id, qty, float(t.get('avg_p', 0)), is_buy))
                        if len(b_batch) >= 20000:
                            cursor.executemany('INSERT OR REPLACE INTO broker_details VALUES (?,?,?,?,?,?,?)', b_batch)
                            b_batch = []
        if b_batch:
            cursor.executemany('INSERT OR REPLACE INTO broker_details VALUES (?,?,?,?,?,?,?)', b_batch)
    conn.commit()

def finalize_new_logic(conn):
    cursor = conn.cursor()
    print("[新邏輯] 正在匯入後建立索引...")
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_lookup ON broker_details (stock_id, date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_query ON broker_details (stock_id, date, is_buy, net_qty DESC)')
    cursor.execute('ANALYZE')
    conn.commit()

if __name__ == "__main__":
    P_JSON = r"C:\jupyter_notebook\ai_twstock\test\stock_data.json"
    B_JSON = r"C:\jupyter_notebook\ai_twstock\test\stock_data_micro.json"
    DB_OLD = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\test_old.db"
    DB_NEW = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\test_new.db"

    # 測試舊邏輯
    print("\n=== 開始測試舊邏輯 (邊塞邊建索引) ===")
    start_old = time.time()
    conn_old = create_db_old_logic(DB_OLD)
    import_data(conn_old, P_JSON, B_JSON)
    conn_old.close()
    end_old = time.time()
    time_old = end_old - start_old
    print(f"舊邏輯總耗時: {time_old:.4f} 秒")

    # 測試新邏輯
    print("\n=== 開始測試新邏輯 (後建索引) ===")
    start_new = time.time()
    conn_new = create_db_new_logic(DB_NEW)
    import_data(conn_new, P_JSON, B_JSON)
    finalize_new_logic(conn_new)
    conn_new.close()
    end_new = time.time()
    time_new = end_new - start_new
    print(f"新邏輯總耗時: {time_new:.4f} 秒")

    print("\n=== 效能差異報告 ===")
    print(f"舊邏輯: {time_old:.4f} 秒")
    print(f"新邏輯: {time_new:.4f} 秒")
    diff = time_old - time_new
    if diff > 0:
        print(f"優化後節省了: {diff:.4f} 秒 (約提升 { (diff/time_old)*100 :.2f}%)")
    else:
        print(f"在小資料量下差異可能不明顯，但在正式環境 (1800萬筆) 差異會非常巨大。")
