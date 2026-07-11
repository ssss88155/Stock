import json
import sqlite3
import os
import time
import glob
from collections import defaultdict
from datetime import datetime

# ==========================================
# 路徑配置 (可統一修改)
# ==========================================
BASE_DIR = r"C:\jupyter_notebook\ai_twstock"
# 修正後的資料路徑
RAW_PRICE_DIR = os.path.join(BASE_DIR, "data_independent_price")
RAW_MICRO_DIR = os.path.join(BASE_DIR, "data_independent_microstructure")
OUTPUT_DB_DIR = os.path.join(BASE_DIR, "data", "SQL_DB_test")

# 測試用檔案
TEST_FILES = ["1109_complete.json", "1109.json", "1101.json", "0050.json"]

class MultiDimDataConverter:
    def __init__(self, price_dir, micro_dir, output_dir):
        self.price_dir = price_dir
        self.micro_dir = micro_dir
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.stats = []

    def log_time(self, stage, start_time):
        duration = time.time() - start_time
        msg = f"[{stage}] 耗時: {duration:.2f} 秒"
        print(msg)
        self.stats.append(msg)

    def get_target_files(self, data_type):
        """獲取要處理的檔案清單"""
        search_path = self.price_dir if data_type == "price" else self.micro_dir
        all_files = glob.glob(os.path.join(search_path, "*.json"))
        
        # 篩選測試檔案
        target_files = [f for f in all_files if os.path.basename(f) in TEST_FILES]
        if not target_files:
            print(f"未找到指定測試檔案，將處理 {data_type} 目錄下的前 5 個檔案...")
            target_files = all_files[:5]
        return target_files

    def create_db_connection(self, data_type, year):
        """建立分型分年的資料庫連線與表結構"""
        db_folder = os.path.join(self.output_dir, data_type)
        os.makedirs(db_folder, exist_ok=True)
        db_path = os.path.join(db_folder, f"{data_type}_{year}.db")
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 效能優化設定
        cursor.execute('PRAGMA journal_mode=WAL;')
        cursor.execute('PRAGMA synchronous=OFF;')
        
        if data_type == "price":
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_prices (
                    stock_id TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, 
                    volume INTEGER, foreign_buy INTEGER, sitc_buy INTEGER, dealer_buy INTEGER, 
                    PRIMARY KEY (stock_id, date)
                )
            ''')
        elif data_type == "micro":
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS broker_details (
                    stock_id TEXT, date TEXT, trader_name TEXT, trader_id TEXT, 
                    net_qty INTEGER, avg_price REAL, is_buy BOOLEAN, 
                    PRIMARY KEY (stock_id, date, trader_id, is_buy)
                )
            ''')
        return conn

    def process_price_data(self):
        t0 = time.time()
        files = self.get_target_files("price")
        yearly_conns = {}
        
        print(f"開始處理 Price 資料，共 {len(files)} 個檔案...")
        
        for f_path in files:
            print(f"讀取檔案: {os.path.basename(f_path)}")
            with open(f_path, 'r', encoding='utf-8') as f:
                try:
                    raw_json = json.load(f)
                    # 處理嵌套結構：如果最外層 Key 是股票代號
                    sid_from_filename = os.path.basename(f_path).replace('.json', '')
                    if sid_from_filename in raw_json:
                        stock_data = raw_json[sid_from_filename]
                        sid = sid_from_filename
                    else:
                        stock_data = raw_json
                        sid = stock_data.get('id') or sid_from_filename
                    
                    prices = stock_data.get('price', {})
                    inst = stock_data.get('institutional', {})
                    
                    if not prices:
                        print(f"警告: {f_path} 內找不到 price 欄位")
                        continue

                    print(f"股票 {sid} 共有 {len(prices)} 筆價格資料")
                    for date, p in prices.items():
                        year = date[:4]
                        if year not in yearly_conns:
                            yearly_conns[year] = self.create_db_connection("price", year)
                        
                        i = inst.get(date, {})
                        f_net = float(i.get('Foreign_Investor', {}).get('buy', 0)) - float(i.get('Foreign_Investor', {}).get('sell', 0))
                        s_net = float(i.get('Investment_Trust', {}).get('buy', 0)) - float(i.get('Investment_Trust', {}).get('sell', 0))
                        d_net = float(i.get('Dealer', {}).get('buy', 0)) - float(i.get('Dealer', {}).get('sell', 0))
                        
                        val = (sid, date, float(p.get('open', 0)), float(p.get('max', 0)), float(p.get('min', 0)), 
                               float(p.get('close', 0)), int(float(p.get('Trading_Volume', 0))), 
                               int(f_net), int(s_net), int(d_net))
                        
                        yearly_conns[year].cursor().execute(
                            'INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?,?,?,?)', val)
                except Exception as e:
                    print(f"處理 {f_path} 出錯: {e}")

        for year, conn in yearly_conns.items():
            print(f"正在優化 price_{year}.db 索引...")
            conn.cursor().execute('CREATE INDEX IF NOT EXISTS idx_price_date ON daily_prices (date)')
            conn.commit()
            conn.close()
            
        self.log_time("Price 轉檔與分切", t0)

    def process_micro_data(self):
        t0 = time.time()
        files = self.get_target_files("micro")
        yearly_conns = {}
        
        print(f"開始處理 Micro 資料，共 {len(files)} 個檔案...")
        
        for f_path in files:
            print(f"讀取檔案: {os.path.basename(f_path)}")
            with open(f_path, 'r', encoding='utf-8') as f:
                try:
                    raw_json = json.load(f)
                    sid_from_filename = os.path.basename(f_path).replace('.json', '').replace('_complete', '')
                    
                    if sid_from_filename in raw_json:
                        stock_data = raw_json[sid_from_filename]
                        sid = sid_from_filename
                    else:
                        stock_data = raw_json
                        sid = stock_data.get('id') or sid_from_filename
                        
                    reports = stock_data.get('trading_daily_report', {})
                    
                    print(f"股票 {sid} 共有 {len(reports)} 筆分點資料")
                    for date, report in reports.items():
                        year = date[:4]
                        if year not in yearly_conns:
                            yearly_conns[year] = self.create_db_connection("micro", year)
                        
                        cursor = yearly_conns[year].cursor()
                        for key, is_buy in [('top_buyers', True), ('top_sellers', False)]:
                            for t in report.get(key, []):
                                trader_str = str(t.get('trader', ''))
                                if not trader_str: continue
                                parts = trader_str.split('/', 1)
                                t_name, t_id = parts if len(parts) == 2 else (parts[0], '')
                                qty = int(abs(float(t.get('net_b', t.get('net_s', t.get('net', 0))))))
                                
                                val = (sid, date, t_name, t_id, qty, float(t.get('avg_p', 0)), is_buy)
                                cursor.execute('INSERT OR REPLACE INTO broker_details VALUES (?,?,?,?,?,?,?)', val)
                except Exception as e:
                    print(f"處理 {f_path} 出錯: {e}")

        for year, conn in yearly_conns.items():
            print(f"正在優化 micro_{year}.db 索引...")
            conn.cursor().execute('CREATE INDEX IF NOT EXISTS idx_broker_date ON broker_details (date)')
            conn.cursor().execute('CREATE INDEX IF NOT EXISTS idx_broker_lookup ON broker_details (stock_id, date, is_buy)')
            conn.commit()
            conn.close()
            
        self.log_time("Micro 轉檔與分切", t0)

    def run(self):
        total_start = time.time()
        print("=== 開始執行多維度分切轉檔流程 ===")
        self.process_price_data()
        self.process_micro_data()
        print("\n" + "="*40)
        print("總結報告:")
        for s in self.stats:
            print(s)
        self.log_time("總流程", total_start)
        print("="*40)

if __name__ == "__main__":
    converter = MultiDimDataConverter(RAW_PRICE_DIR, RAW_MICRO_DIR, OUTPUT_DB_DIR)
    converter.run()
