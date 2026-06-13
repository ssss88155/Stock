import json
import sqlite3
import os
import ijson
import time
import sys

def create_db(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 寫入與讀取效能優化
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('PRAGMA synchronous=NORMAL;')
    cursor.execute('PRAGMA cache_size = -524288;') # 512MB Cache
    cursor.execute('PRAGMA temp_store = MEMORY;')  # 暫存檔放記憶體
    cursor.execute('PRAGMA mmap_size = 30000000000;') # 允許使用 Memory-Mapped I/O
    
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

def import_prices(conn, json_path):
    """優化：改用 ijson 串流讀取價格資料，並強制轉換 Decimal 為 float/int"""
    print(f"正在匯入價格資料 (串流): {json_path}")
    if not os.path.exists(json_path): return
    
    cursor = conn.cursor()
    batch_data = []
    batch_size = 10000
    
    with open(json_path, 'r', encoding='utf-8') as f:
        parser = ijson.kvitems(f, '')
        for sid, info in parser:
            prices = info.get('price', {})
            inst = info.get('institutional', {})
            for date, p in prices.items():
                i = inst.get(date, {})
                f_inv = i.get('Foreign_Investor', {})
                s_inv = i.get('Investment_Trust', {})
                d_inv = i.get('Dealer', {})
                
                # 強制轉換 Decimal 為 float/int 以相容 SQLite
                f_net = float(f_inv.get('buy', 0)) - float(f_inv.get('sell', 0))
                s_net = float(s_inv.get('buy', 0)) - float(s_inv.get('sell', 0))
                d_net = float(d_inv.get('buy', 0)) - float(d_inv.get('sell', 0))
                
                batch_data.append((
                    sid, date, 
                    float(p.get('open', 0)) if p.get('open') is not None else None,
                    float(p.get('max', 0)) if p.get('max') is not None else None,
                    float(p.get('min', 0)) if p.get('min') is not None else None,
                    float(p.get('close', 0)) if p.get('close') is not None else None,
                    int(float(p.get('Trading_Volume', 0))),
                    int(f_net), int(s_net), int(d_net)
                ))
                
                if len(batch_data) >= batch_size:
                    cursor.executemany('INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?,?,?,?)', batch_data)
                    batch_data = []
        
        if batch_data:
            cursor.executemany('INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?,?,?,?)', batch_data)
    conn.commit()

def import_brokers_streaming(conn, json_path):
    print(f"正在以串流方式匯入分點資料: {json_path}")
    if not os.path.exists(json_path): return
    cursor = conn.cursor()
    batch_data = []
    batch_size = 50000
    total_count = 0
    stock_count = 0
    
    with open(json_path, 'r', encoding='utf-8') as f:
        parser = ijson.kvitems(f, '')
        for sid, info in parser:
            stock_count += 1
            reports = info.get('trading_daily_report', {})
            for date, report in reports.items():
                for key, is_buy in [('top_buyers', True), ('top_sellers', False)]:
                    for t in report.get(key, []):
                        trader_str = str(t.get('trader', ''))
                        if not trader_str: continue
                        
                        parts = trader_str.split('/', 1)
                        t_name, t_id = parts if len(parts) == 2 else (parts[0], '')
                        
                        qty_raw = t.get('net_b', t.get('net_s', t.get('net', 0)))
                        qty = int(abs(float(qty_raw)))
                        avg_p = float(t.get('avg_p', 0))
                        batch_data.append((sid, date, t_name, t_id, qty, avg_p, is_buy))
                        total_count += 1
                        
                        if len(batch_data) >= batch_size:
                            cursor.executemany('INSERT OR REPLACE INTO broker_details VALUES (?,?,?,?,?,?,?)', batch_data)
                            conn.commit()
                            batch_data = []
                            print(f"已處理 {stock_count} 檔股票，累計寫入 {total_count} 筆...")
        if batch_data:
            cursor.executemany('INSERT OR REPLACE INTO broker_details VALUES (?,?,?,?,?,?,?)', batch_data)
            conn.commit()
    print(f"分點資料匯入完成！共 {total_count} 筆。")

def finalize_db(conn):
    print("\n--- 執行資料庫最終優化 ---")
    cursor = conn.cursor()
    
    print("正在建立索引 (idx_broker_lookup)...")
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_lookup ON broker_details (stock_id, date, is_buy, net_qty, trader_name, avg_price)')
    
    print("正在建立索引 (idx_broker_query)...")
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_query ON broker_details (stock_id, date, is_buy, net_qty DESC)')
    
    print("正在更新統計資訊 (ANALYZE)...")
    cursor.execute('ANALYZE')
    
    conn.commit()
    
    print("正在執行資料叢集化與壓縮 (VACUUM)...")
    old_isolation = conn.isolation_level
    conn.isolation_level = None 
    conn.execute('VACUUM')
    conn.isolation_level = old_isolation
    
    print("優化完成。")

if __name__ == "__main__":
    DB_PATH = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"
    PRICE_JSON = r"C:\jupyter_notebook\ai_twstock\stock_data.json"
    BROKER_JSON = r"C:\jupyter_notebook\ai_twstock\stock_data_micro.json"
    
    start_time = time.time()
    conn = None
    try:
        print(f"開始執行轉換流程...")
        conn = create_db(DB_PATH)
        import_prices(conn, PRICE_JSON)
        import_brokers_streaming(conn, BROKER_JSON)
        finalize_db(conn)
        print(f"\n轉換完成！總耗時: {time.time() - start_time:.2f} 秒")
    except Exception as e:
        if conn: conn.rollback()
        print(f"\n發生致命錯誤: {e}")
        sys.exit(1)
    finally:
        if conn: conn.close()
    
    print(f"資料庫位於: {DB_PATH}")
