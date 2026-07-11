import json
import sqlite3
import os
import ijson
import time

def create_db(db_path, cache_mb=64, use_temp_mem=False):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 基礎優化
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('PRAGMA synchronous=NORMAL;')
    
    # 進階優化 1: 設定 Cache Size (512MB = 512 * 1024 = 524288 KB)
    # SQLite PRAGMA cache_size 如果是負數，代表以 KB 為單位
    cache_kb = -cache_mb * 1024
    cursor.execute(f'PRAGMA cache_size = {cache_kb};')
    
    # 進階優化 2: Temp Store (將暫存檔放在記憶體中，加速排序與索引建立)
    if use_temp_mem:
        cursor.execute('PRAGMA temp_store = MEMORY;')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_prices (
            stock_id TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, 
            volume INTEGER, foreign_buy INTEGER, sitc_buy INTEGER, dealer_buy INTEGER, 
            PRIMARY KEY (stock_id, date)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS broker_details (
            stock_id TEXT, date TEXT, trader_name TEXT, trader_id TEXT, 
            net_qty INTEGER, avg_price REAL, is_buy BOOLEAN, 
            PRIMARY KEY (stock_id, date, trader_id, is_buy)
        )
    ''')
    
    cursor.execute('DELETE FROM daily_prices')
    cursor.execute('DELETE FROM broker_details')
    conn.commit()
    return conn

def import_data(conn, price_json, broker_json, batch_size=20000):
    cursor = conn.cursor()
    # 價格匯入
    with open(price_json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    p_batch = []
    for sid, info in data.items():
        for date, p in info.get('price', {}).items():
            p_batch.append((sid, date, p.get('open'), p.get('max'), p.get('min'), p.get('close'), p.get('Trading_Volume'), 0, 0, 0))
    cursor.executemany('INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?,?,?,?)', p_batch)
    
    # 分點匯入
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
                        if len(b_batch) >= batch_size:
                            cursor.executemany('INSERT OR REPLACE INTO broker_details VALUES (?,?,?,?,?,?,?)', b_batch)
                            b_batch = []
        if b_batch:
            cursor.executemany('INSERT OR REPLACE INTO broker_details VALUES (?,?,?,?,?,?,?)', b_batch)
    conn.commit()

def finalize_db(conn):
    cursor = conn.cursor()
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_lookup ON broker_details (stock_id, date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_query ON broker_details (stock_id, date, is_buy, net_qty DESC)')
    cursor.execute('ANALYZE')
    conn.commit()

if __name__ == "__main__":
    P_JSON = r"C:\jupyter_notebook\ai_twstock\test\stock_data.json"
    B_JSON = r"C:\jupyter_notebook\ai_twstock\test\stock_data_micro.json"
    
    # 1. 基準測試 (原本的優化: 64MB Cache, 20000 Batch)
    print("\n=== 1. 基準測試 (64MB Cache, 20000 Batch) ===")
    DB_BASE = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\test_base.db"
    s1 = time.time()
    c1 = create_db(DB_BASE, cache_mb=64)
    import_data(c1, P_JSON, B_JSON, batch_size=20000)
    finalize_db(c1)
    c1.close()
    t1 = time.time() - s1
    print(f"基準測試耗時: {t1:.4f} 秒")

    # 2. 進階測試 (512MB Cache, 50000 Batch, Temp Store Memory)
    print("\n=== 2. 進階測試 (512MB Cache, 50000 Batch, Temp Store Memory) ===")
    DB_ADV = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\test_adv.db"
    s2 = time.time()
    c2 = create_db(DB_ADV, cache_mb=512, use_temp_mem=True)
    import_data(c2, P_JSON, B_JSON, batch_size=50000)
    finalize_db(c2)
    c2.close()
    t2 = time.time() - s2
    print(f"進階測試耗時: {t2:.4f} 秒")

    print("\n=== 效能差異報告 ===")
    print(f"基準優化: {t1:.4f} 秒")
    print(f"進階優化: {t2:.4f} 秒")
    diff = t1 - t2
    if diff > 0:
        print(f"進階優化又節省了: {diff:.4f} 秒 (約再提升 { (diff/t1)*100 :.2f}%)")
    else:
        print(f"小資料量下差異不明顯，但在 1800 萬筆資料時，512MB Cache 與 Temp Store Memory 會極大減少磁碟壓力。")
