# -*- coding: utf-8 -*-
"""
generate_grids_data.py
獨立腳本：專門計算大盤指標 (Market Breadth 與 0050 Drawdown) 並存入 Grids_0050_MA.py
"""

import os
import sqlite3
import pandas as pd
import pprint
from datetime import datetime

# 設定路徑
DB_PATH = r"C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db"
GRIDS_CACHE_FILE = r"C:\jupyter_notebook\ai_twstock\data\Grids_0050_MA.py"

def generate():
    print("正在從 SQL 載入資料進行大盤指標計算...")
    conn = sqlite3.connect(DB_PATH)
    
    # 1. 載入 0050 資料計算 Drawdown
    query_0050 = "SELECT date, close, high FROM daily_prices WHERE stock_id = '0050' ORDER BY date"
    df_0050 = pd.read_sql(query_0050, conn)
    
    twse_dd_60 = {}
    if not df_0050.empty:
        # 計算過去 60 日最高價 (包含當天)
        df_0050['peak_60'] = df_0050['high'].rolling(window=60, min_periods=1).max()
        # 計算回檔比例 (當前收盤價 vs 60日最高價)
        df_0050['dd_60'] = (df_0050['close'] - df_0050['peak_60']) / df_0050['peak_60']
        twse_dd_60 = df_0050.set_index('date')['dd_60'].to_dict()

    # 2. 載入全市場資料計算 Market Breadth
    # 為了效能，我們先抓出所有日期，再逐日計算
    query_all = "SELECT date, stock_id, close FROM daily_prices WHERE date >= '2025-01-01' ORDER BY date"
    df_all = pd.read_sql(query_all, conn)
    conn.close()

    print("正在計算全市場 MA60...")
    market_breadth = {}
    
    # 將資料轉為 pivot table: index=date, columns=stock_id, values=close
    df_pivot = df_all.pivot(index='date', columns='stock_id', values='close')
    
    # 計算所有股票的 MA60
    df_ma60 = df_pivot.rolling(window=60).mean()
    
    # 判斷每日收盤價是否大於 MA60
    # True 為 1, False 為 0
    df_above = (df_pivot > df_ma60).astype(float)
    
    # 計算每日站上 MA60 的比例 (排除 NaN)
    # 排除 0050 自身
    if '0050' in df_above.columns:
        df_above = df_above.drop(columns=['0050'])
    
    breadth_series = df_above.mean(axis=1, skipna=True)
    market_breadth = breadth_series.dropna().to_dict()

    # 3. 寫入檔案
    grids_data = {
        'market_breadth': market_breadth,
        'twse_dd_60': twse_dd_60,
        'last_update': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'description': {
            'market_breadth': '全市場(不含0050)收盤價站上 60日均線(MA60) 的家數比例。數值 0.6 代表 60% 股票站上均線。',
            'twse_dd_60': '0050 距離過去 60 個交易日最高價(High)的回檔幅度。數值 -0.05 代表回檔 5%。'
        }
    }

    print(f"正在寫入快取至 {GRIDS_CACHE_FILE}...")
    with open(GRIDS_CACHE_FILE, 'w', encoding='utf-8') as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write("\"\"\"\n各項數值意義：\n")
        f.write("1. market_breadth: 市場寬度。代表全市場有多少比例的股票站上季線(MA60)。\n")
        f.write("   - > 0.5: 多頭佔優勢，適合順勢策略。\n")
        f.write("   - < 0.3: 市場極度低迷，可能出現逆勢接刀機會。\n")
        f.write("2. twse_dd_60: 0050 波段回檔深度。\n")
        f.write("   - 0: 代表目前處於 60 日高點。\n")
        f.write("   - -0.03: 回檔 3%，進入初步修正。\n")
        f.write("   - -0.07: 回檔 7%，進入恐慌區，解鎖更多逆勢車位。\n")
        f.write("\"\"\"\n\n")
        f.write("GRIDS_DATA = ")
        f.write(pprint.pformat(grids_data, indent=4, width=120, sort_dicts=True))
        f.write("\n")
    
    print("計算完成！")

if __name__ == "__main__":
    generate()
