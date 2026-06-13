import json
import sqlite3
import os
import ijson
import time

def create_db(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 效能優化設定
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('PRAGMA synchronous=NORMAL;')
    cursor.execute('PRAGMA cache_size = -64000;') # 使用約 64MB 記憶體快取
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_prices (
            stock_id TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            foreign_buy INTEGER,
            sitc_buy INTEGER,
            dealer_buy INTEGER,
            PRIMARY KEY (stock_id, date)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS broker_details (
            stock_id TEXT,
            date TEXT,
            trader_name TEXT,
            trader_id TEXT,
            net_qty INTEGER,
            avg_price REAL,
            is_buy BOOLEAN,
            PRIMARY KEY (stock_id, date, trader_id, is_buy)
        )
    ''')
    
    # 增加複合索引，提升查詢效能
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_lookup ON broker_details (stock_id, date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_query ON broker_details (stock_id, date, is_buy, net_qty DESC)')
    
    # 清空舊資料
    cursor.execute('DELETE FROM daily_prices')
    cursor.execute('DELETE FROM broker_details')
    
    conn.commit()
    return conn

def import_prices(conn, json_path):
    print(f"正在匯入價格資料: {json_path}")
    if not os.path.exists(json_path):
        print(f"找不到檔案: {json_path}")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    cursor = conn.cursor()
    batch_data = []
    
    for sid, info in data.items():
        prices = info.get('price', {})
        inst = info.get('institutional', {})
        for date, p in prices.items():
            i = inst.get(date, {})
            f_buy = i.get('Foreign_Investor', {}).get('buy', 0) - i.get('Foreign_Investor', {}).get('sell', 0)
            s_buy = i.get('Investment_Trust', {}).get('buy', 0) - i.get('Investment_Trust', {}).get('sell', 0)
            d_buy = i.get('Dealer', {}).get('buy', 0) - i.get('Dealer', {}).get('sell', 0)
            
            batch_data.append((
                sid, date, p.get('open'), p.get('max'), p.get('min'), 
                p.get('close'), p.get('Trading_Volume'), f_buy, s_buy, d_buy
            ))
            
    if batch_data:
        cursor.executemany('INSERT OR REPLACE INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', batch_data)
    conn.commit()
    print(f"價格資料匯入完成，共 {len(batch_data)} 筆。")

def import_brokers_streaming(conn, json_path):
    print(f"正在以串流方式匯入分點資料: {json_path}")
    if not os.path.exists(json_path):
        print(f"找不到檔案: {json_path}")
        return

    cursor = conn.cursor()
    batch_data = []
    batch_size = 20000
    total_count = 0
    stock_count = 0
    
    with open(json_path, 'r', encoding='utf-8') as f:
        parser = ijson.kvitems(f, '')
        for sid, info in parser:
            stock_count += 1
            reports = info.get('trading_daily_report', {})
            if not reports:
                continue
                
            for date, report in reports.items():
                for key, is_buy in [('top_buyers', True), ('top_sellers', False)]:
                    for t in report.get(key, []):
                        trader_str = str(t.get('trader', ''))
                        if not trader_str:
                            continue
                            
                        t_name, t_id = trader_str.split('/') if '/' in trader_str else (trader_str, '')
                        
                        qty_raw = t.get('net_b', t.get('net_s', t.get('net', 0)))
                        try:
                            qty = int(abs(float(qty_raw)))
                        except (ValueError, TypeError):
                            qty = 0
                            
                        try:
                            avg_p = float(t.get('avg_p', 0))
                        except (ValueError, TypeError):
                            avg_p = 0.0
                        
                        batch_data.append((sid, date, t_name, t_id, qty, avg_p, is_buy))
                        total_count += 1
                        
                        if len(batch_data) >= batch_size:
                            cursor.executemany('INSERT OR REPLACE INTO broker_details VALUES (?, ?, ?, ?, ?, ?, ?)', batch_data)
                            conn.commit()
                            batch_data = []
                            print(f"已處理 {stock_count} 檔股票，累計寫入 {total_count} 筆分點明細...")

        if batch_data:
            cursor.executemany('INSERT OR REPLACE INTO broker_details VALUES (?, ?, ?, ?, ?, ?, ?)', batch_data)
            conn.commit()
            
    print(f"分點資料匯入完成！總計處理 {stock_count} 檔股票，共 {total_count} 筆明細。")

def finalize_db(conn):
    print("\n--- 執行資料庫最終優化 ---")
    cursor = conn.cursor()
    print("正在更新統計資訊 (ANALYZE)...")
    cursor.execute('ANALYZE')
    
    # 檢查異常資料
    cursor.execute('SELECT COUNT(*) FROM daily_prices WHERE close = 0 OR close IS NULL')
    bad_prices = cursor.fetchone()[0]
    if bad_prices > 0:
        print(f"警告：發現 {bad_prices} 筆價格為 0 或 NULL 的異常資料！")
    
    conn.commit()

if __name__ == "__main__":
    DB_PATH = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"
    PRICE_JSON = r"C:\jupyter_notebook\ai_twstock\stock_data.json"
    BROKER_JSON = r"C:\jupyter_notebook\ai_twstock\stock_data_micro.json"
    
    start_time = time.time()
    conn = create_db(DB_PATH)
    import_prices(conn, PRICE_JSON)
    import_brokers_streaming(conn, BROKER_JSON)
    finalize_db(conn)
    conn.close()
    
    print(f"所有資料轉換完成！總耗時: {time.time() - start_time:.2f} 秒")
    print(f"資料庫位於: {DB_PATH}")
