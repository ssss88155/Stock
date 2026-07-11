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
    
    cursor.execute('PRAGMA journal_mode=WAL;')
    cursor.execute('PRAGMA synchronous=NORMAL;')
    cursor.execute('PRAGMA cache_size = -524288;') 
    cursor.execute('PRAGMA temp_store = MEMORY;')
    cursor.execute('PRAGMA mmap_size = 30000000000;')
    
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
    
    return conn

def import_prices(conn, json_path):
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
                f_net = float(i.get('Foreign_Investor', {}).get('buy', 0)) - float(i.get('Foreign_Investor', {}).get('sell', 0))
                s_net = float(i.get('Investment_Trust', {}).get('buy', 0)) - float(i.get('Investment_Trust', {}).get('sell', 0))
                d_net = float(i.get('Dealer', {}).get('buy', 0)) - float(i.get('Dealer', {}).get('sell', 0))
                batch_data.append((sid, date, float(p.get('open', 0)), float(p.get('max', 0)), float(p.get('min', 0)), float(p.get('close', 0)), int(float(p.get('Trading_Volume', 0))), int(f_net), int(s_net), int(d_net)))
                if len(batch_data) >= batch_size:
                    cursor.executemany('INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?,?,?,?)', batch_data)
                    batch_data = []
        if batch_data:
            cursor.executemany('INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?,?,?,?)', batch_data)

def import_brokers_streaming(conn, json_path):
    print(f"正在以串流方式匯入分點資料: {json_path}")
    if not os.path.exists(json_path): return
    cursor = conn.cursor()
    batch_data = []
    batch_size = 50000
    total_count = 0
    with open(json_path, 'r', encoding='utf-8') as f:
        parser = ijson.kvitems(f, '')
        for sid, info in parser:
            reports = info.get('trading_daily_report', {})
            for date, report in reports.items():
                for key, is_buy in [('top_buyers', True), ('top_sellers', False)]:
                    for t in report.get(key, []):
                        trader_str = str(t.get('trader', ''))
                        if not trader_str: continue
                        parts = trader_str.split('/', 1)
                        t_name, t_id = parts if len(parts) == 2 else (parts[0], '')
                        qty = int(abs(float(t.get('net_b', t.get('net_s', t.get('net', 0))))))
                        batch_data.append((sid, date, t_name, t_id, qty, float(t.get('avg_p', 0)), is_buy))
                        total_count += 1
                        if len(batch_data) >= batch_size:
                            cursor.executemany('INSERT OR REPLACE INTO broker_details VALUES (?,?,?,?,?,?,?)', batch_data)
                            batch_data = []
        if batch_data:
            cursor.executemany('INSERT OR REPLACE INTO broker_details VALUES (?,?,?,?,?,?,?)', batch_data)
    print(f"分點資料匯入完成！共 {total_count} 筆。")

def finalize_db(conn, use_new_index=True):
    print(f"\n--- 執行資料庫最終優化 (使用新索引策略: {use_new_index}) ---")
    cursor = conn.cursor()
    
    if use_new_index:
        # 建議 1: 增加以 date 為首的索引，加速日期範圍查詢
        print("正在建立日期索引 (idx_broker_date)...")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_date ON broker_details (date)')
        
        # 強化版覆蓋索引 (包含 trader_id, trader_name)
        print("正在建立強化版覆蓋索引 (idx_broker_lookup)...")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_lookup ON broker_details (stock_id, date, is_buy, net_qty, trader_id, trader_name, avg_price)')
    else:
        # 原本的索引方式
        print("正在建立原始索引 (idx_broker_lookup)...")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_lookup ON broker_details (stock_id, date)')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_broker_query ON broker_details (stock_id, date, is_buy, net_qty DESC)')
    cursor.execute('ANALYZE')
    conn.commit()
    
    print("正在執行 VACUUM...")
    old_isolation = conn.isolation_level
    conn.isolation_level = None 
    conn.execute('VACUUM')
    conn.isolation_level = old_isolation

def test_logic(db_path, use_new_index):
    start_time = time.time()
    conn = None
    try:
        conn = create_db(db_path)
        import_prices(conn, r"C:\jupyter_notebook\ai_twstock\test\stock_data.json")
        import_brokers_streaming(conn, r"C:\jupyter_notebook\ai_twstock\test\stock_data_micro.json")
        finalize_db(conn, use_new_index=use_new_index)
        duration = time.time() - start_time
        return duration
    except Exception as e:
        if conn: conn.rollback()
        print(f"錯誤: {e}")
        return None
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    print("=== 索引優化對比測試 ===")
    
    # 1. 測試原本邏輯
    print("\n>>> 階段 1: 執行原本索引邏輯")
    db_old = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\test_idx_old.db"
    time_old = test_logic(db_old, use_new_index=False)
    print(f"原本邏輯耗時: {time_old:.2f} 秒")
    
    # 2. 測試更新邏輯 (增加 date 索引)
    print("\n>>> 階段 2: 執行更新索引邏輯 (增加 idx_broker_date)")
    db_new = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\test_idx_new.db"
    time_new = test_logic(db_new, use_new_index=True)
    print(f"更新邏輯耗時: {time_new:.2f} 秒")
    
    print("\n" + "="*50)
    print(f"原本耗時: {time_old:.2f}s")
    print(f"更新耗時: {time_new:.2f}s")
    print(f"差異: {time_new - time_old:.2f}s (註: 增加索引會增加匯入時間，但能極大加速上層查詢)")
    print("="*50)
