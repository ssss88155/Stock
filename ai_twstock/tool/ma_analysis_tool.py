import sqlite3
import pandas as pd
import os
import argparse
import sys
import json
from datetime import datetime, timedelta
from collections import OrderedDict

# 設定路徑
DB_PATH = r'C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db'
MA_DATA_DIR = r'C:\jupyter_notebook\ai_twstock\data\MA_data'

# 終端機顏色
class Color:
    RED = '\033[91m'
    ORANGE = '\033[38;5;208m'
    END = '\033[0m'

def get_ma_file_path(stock_id):
    return os.path.join(MA_DATA_DIR, f'MA_detail_{stock_id}.py')

def load_ma_data_from_file(stock_id):
    file_path = get_ma_file_path(stock_id)
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if "DATA =" in content:
                    data_str = content.split("DATA =")[1].strip()
                    return json.loads(data_str)
        except Exception as e:
            print(f"[WARN] 讀取快取失敗: {e}")
    return None

def save_ma_data_to_file(stock_id, data_dict):
    file_path = get_ma_file_path(stock_id)
    os.makedirs(MA_DATA_DIR, exist_ok=True)
    
    # 依日期反向排序 (最新的在上面)
    sorted_keys = sorted(data_dict.keys(), reverse=True)
    sorted_data = OrderedDict()
    for k in sorted_keys:
        sorted_data[k] = data_dict[k]
        
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(f"# Generated MA Data for {stock_id}\n")
        f.write("DATA = ")
        json.dump(sorted_data, f, ensure_ascii=False, indent=4)
        f.write("\n")

def calculate_ma(stock_id):
    print(f"計算中... {stock_id}")
    conn = sqlite3.connect(DB_PATH)
    query = f"SELECT date, close FROM daily_prices WHERE stock_id = '{stock_id}' ORDER BY date ASC"
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        return None

    df['MA5'] = df['close'].rolling(window=5).mean()
    df['MA20'] = df['close'].rolling(window=20).mean()
    df['MA60'] = df['close'].rolling(window=60).mean()

    ma_data = {}
    for _, row in df.iterrows():
        if pd.isna(row['MA60']): continue
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
    parser.add_argument('--end', type=str, nargs='?', help='End date YYYY-MM-DD (optional, default is latest)')
    parser.add_argument('stock_id', type=str, help='Stock ID (e.g. 0050)')
    parser.add_argument('--ma', type=int, choices=[5, 20, 60], default=60, help='MA period to compare')
    parser.add_argument('--compare', type=str, help='Compare with another stock ID (e.g. 0050)')

    args = parser.parse_args()
    stock_id = args.stock_id
    comp_id = args.compare
    start_date = args.start
    ma_key = f'MA{args.ma}'

    # 1. 載入主股票資料
    ma_data = load_ma_data_from_file(stock_id)
    if not ma_data: ma_data = calculate_ma(stock_id)
    if not ma_data:
        print(f"找不到股票 {stock_id} 的資料")
        return

    # 2. 載入比較股票資料 (如果有)
    comp_data = None
    if comp_id:
        comp_data = load_ma_data_from_file(comp_id)
        if not comp_data: comp_data = calculate_ma(comp_id)

    # 處理日期範圍
    all_dates = sorted(ma_data.keys())
    latest_date = all_dates[-1]
    end_date = args.end if args.end else latest_date
    display_dates = [d for d in all_dates if start_date <= d <= end_date]

    # 標題列
    header = f"編號 {stock_id}"
    if comp_id: header += f" vs {comp_id}"
    print(f"{header} ( {start_date} ~ {end_date} )")
    
    line_len = 50 if not comp_id else 90
    print("=" * line_len)
    
    col_header = f"{'Date':<12}\t{ma_key:<8}\t{'限價':<8}\t{'幅度':<8}"
    if comp_id:
        col_header += f"\t | \t{comp_id}限價\t{comp_id}幅度"
    print(col_header)
    print("-" * line_len)

    # 流水帳輸出
    for date in display_dates:
        info = ma_data[date]
        ma_val = info[ma_key]
        close_val = info['close']
        diff_pct = (close_val - ma_val) / ma_val * 100
        
        def get_colored_diff(pct):
            s = f"{pct:.2f}%"
            a = abs(pct)
            if a >= 15: return f"{Color.RED}{s}{Color.END}"
            if a >= 10: return f"{Color.ORANGE}{s}{Color.END}"
            return s

        row = f"{date:<12}\t{ma_val:<8.2f}\t{close_val:<8.2f}\t{get_colored_diff(diff_pct)}"
        
        if comp_id and comp_data and date in comp_data:
            c_info = comp_data[date]
            c_close = c_info['close']
            c_ma = c_info[ma_key]
            c_diff = (c_close - c_ma) / c_ma * 100
            row += f"\t | \t{c_close:<8.2f}\t{get_colored_diff(c_diff)}"
            
        print(row)

    print() # 空一行
    # 5. 預測未來 (假設限價持平)
    print("\n預測未來 (假設限價持平於最新價格)")
    print("-" * 50)
    
    # 獲取所有歷史收盤價
    conn = sqlite3.connect(DB_PATH)
    query = f"SELECT close FROM daily_prices WHERE stock_id = '{stock_id}' ORDER BY date ASC"
    all_closes = pd.read_sql_query(query, conn)['close'].tolist()
    conn.close()
    
    last_price = all_closes[-1]
    periods = [10, 20, 30]
    
    for p in periods:
        # 模擬未來 p 天價格持平
        future_prices = all_closes + [last_price] * p
        # 計算新的 MA
        ma_future = pd.Series(future_prices).rolling(window=args.ma).mean().iloc[-1]
        diff_pct = (last_price - ma_future) / ma_future * 100
        
        diff_str = f"{diff_pct:.2f}%"
        abs_diff = abs(diff_pct)
        if abs_diff >= 15:
            diff_str = f"{Color.RED}{diff_str}{Color.END}"
        elif abs_diff >= 10:
            diff_str = f"{Color.ORANGE}{diff_str}{Color.END}"
            
        print(f"第 {p:<2} 天後 | 預估 {ma_key}: {ma_future:<8.2f} | 限價: {last_price:<8.2f} | 幅度: {diff_str}")

if __name__ == "__main__":
    main()
