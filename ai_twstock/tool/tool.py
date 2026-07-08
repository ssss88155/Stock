import sqlite3
import pandas as pd
import os
import argparse
import sys
from datetime import datetime, timedelta

# 設定路徑
DB_PATH = r'C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db'
MA_DATA_DIR = r'C:\jupyter_notebook\ai_twstock\data\MA_data'

# 終端機顏色
class Color:
    RED = '\033[91m'
    END = '\033[0m'

def get_ma_file_path(stock_id):
    return os.path.join(MA_DATA_DIR, f'MA_detail_{stock_id}.py')

def load_ma_data_from_file(stock_id):
    file_path = get_ma_file_path(stock_id)
    if os.path.exists(file_path):
        try:
            # 讀取 .py 檔案中的字典 (假設格式為 DATA = {...})
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # 簡單解析，實際建議用 json 或更嚴謹的格式，但依需求存為 .py
                if "DATA =" in content:
                    data_str = content.split("DATA =")[1].strip()
                    return eval(data_str)
        except Exception as e:
            print(f"[WARN] 讀取快取失敗: {e}")
    return None

def save_ma_data_to_file(stock_id, data_dict):
    file_path = get_ma_file_path(stock_id)
    os.makedirs(MA_DATA_DIR, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(f"# Generated MA Data for {stock_id}\n")
        f.write(f"DATA = {repr(data_dict)}\n")

def calculate_ma(stock_id):
    print(f"計算中... {stock_id}")
    conn = sqlite3.connect(DB_PATH)
    # 抓取所有歷史資料以計算正確的 MA
    query = f"SELECT date, close FROM daily_prices WHERE stock_id = '{stock_id}' ORDER BY date ASC"
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        return None

    df['MA5'] = df['close'].rolling(window=5).mean()
    df['MA20'] = df['close'].rolling(window=20).mean()
    df['MA60'] = df['close'].rolling(window=60).mean()

    # 轉為字典格式存檔
    ma_data = {}
    for _, row in df.iterrows():
        if pd.isna(row['MA60']): continue # 至少要有 MA60 才有意義
        ma_data[row['date']] = {
            'close': row['close'],
            'MA5': round(row['MA5'], 2),
            'MA20': round(row['MA20'], 2),
            'MA60': round(row['MA60'], 2)
        }
    
    save_ma_data_to_file(stock_id, ma_data)
    return ma_data

def main():
    parser = argparse.ArgumentParser(description='Stock MA Analysis Tool')
    parser.add_argument('--start', type=str, required=True, help='Start date YYYY-MM-DD')
    parser.add_argument('--end', type=str, required=True, help='End date YYYY-MM-DD')
    parser.add_argument('stock_id', type=str, help='Stock ID (e.g. 0050)')
    parser.add_argument('--ma', type=int, choices=[5, 20, 60], default=60, help='MA period to compare')

    args = parser.parse_args()
    stock_id = args.stock_id
    start_date = args.start
    end_date = args.end
    ma_key = f'MA{args.ma}'

    # 1. & 2. 檢查快取或產生
    ma_data = load_ma_data_from_file(stock_id)
    
    # 檢查快取是否包含所需區段 (簡單檢查 start/end 是否在 key 中，或重新計算)
    if not ma_data or start_date not in ma_data or end_date not in ma_data:
        ma_data = calculate_ma(stock_id)

    if not ma_data:
        print(f"找不到股票 {stock_id} 的資料")
        return

    # 4. 印出流水帳
    print(f"編號 {stock_id} ( {start_date} ~ {end_date} )")
    print("=" * 50)
    print(f"{'Date':<12}\t{ma_key:<8}\t{'限價':<8}\t{'幅度':<8}")
    print("-" * 50)

    # 過濾日期範圍並排序
    sorted_dates = sorted([d for d in ma_data.keys() if start_date <= d <= end_date])

    for date in sorted_dates:
        info = ma_data[date]
        ma_val = info[ma_key]
        close_val = info['close']
        
        # 計算幅度: (限價 - MA) / MA
        diff_pct = (close_val - ma_val) / ma_val * 100
        
        diff_str = f"{diff_pct:.2f}%"
        if abs(diff_pct) >= 10:
            # 加上紅色標記 (ANSI)
            diff_str = f"{Color.RED}{diff_str}{Color.END}"

        print(f"{date:<12}\t{ma_val:<8.2f}\t{close_val:<8.2f}\t{diff_str}")

if __name__ == "__main__":
    main()
