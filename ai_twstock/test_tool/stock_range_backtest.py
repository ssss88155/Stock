import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
from datetime import datetime

# 設定路徑
DB_PATH = r'C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db'
OUTPUT_DIR = r'C:\jupyter_notebook\ai_twstock\test_tool'
STOCK_ID = '0050'
START_DATE = '2026-05-01'
END_DATE = '2026-06-15'
INITIAL_CAPITAL = 30000

def run_simulation():
    if not os.path.exists(DB_PATH):
        print(f"錯誤: 找不到資料庫 {DB_PATH}")
        return

    # 1. 抓取資料
    conn = sqlite3.connect(DB_PATH)
    query = f"""
    SELECT date, open, high, low, close 
    FROM daily_prices 
    WHERE stock_id = '{STOCK_ID}' 
    AND date BETWEEN '{START_DATE}' AND '{END_DATE}'
    ORDER BY date ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        print(f"在 {START_DATE} 到 {END_DATE} 期間找不到 {STOCK_ID} 的資料。")
        return

    # 2. 計算最高與最低點
    # 根據需求：計算過程中的最低點+最高點，把低點價位寫下來 -> 高點價位寫下來
    # 這裡理解為在該時段內，先找到最低點買入，再找到最高點賣出（模擬理想化交易或區間分析）
    
    min_price = df['low'].min()
    max_price = df['high'].max()
    
    min_date = df.loc[df['low'] == min_price, 'date'].iloc[0]
    max_date = df.loc[df['high'] == max_price, 'date'].iloc[0]

    print(f"分析期間: {START_DATE} ~ {END_DATE}")
    print(f"股票代號: {STOCK_ID}")
    print(f"期間最低價: {min_price} (日期: {min_date})")
    print(f"期間最高價: {max_price} (日期: {max_date})")

    # 3. 模擬交易邏輯
    # 假設在最低點買入，最高點賣出 (若最高點在最低點之前，則視為區間持有)
    # 由於使用者要求「最終賺了多少錢」，我們以本金 3W 進行計算
    
    # 計算可買股數 (無手續費簡化版，或可加入基本手續費)
    # 台灣股票通常以張(1000股)為單位，但 3W 可能只能買零股
    shares = INITIAL_CAPITAL / min_price
    final_value = shares * max_price
    profit = final_value - INITIAL_CAPITAL
    profit_rate = (final_value / INITIAL_CAPITAL)
    
    # 4. 統計與圖表
    # 使用者要求：統計圖，看出中位數在哪、集中在哪 (針對價格分佈)
    prices = df['close']
    median_price = prices.median()
    mean_price = prices.mean()

    plt.figure(figsize=(12, 6))
    
    # 直方圖與密度圖
    plt.subplot(1, 2, 1)
    plt.hist(prices, bins=15, color='skyblue', edgecolor='black', alpha=0.7)
    plt.axvline(median_price, color='red', linestyle='dashed', linewidth=2, label=f'Median: {median_price:.2f}')
    plt.axvline(mean_price, color='green', linestyle='dashed', linewidth=2, label=f'Mean: {mean_price:.2f}')
    plt.title(f'{STOCK_ID} Price Distribution')
    plt.xlabel('Price')
    plt.ylabel('Frequency')
    plt.legend()

    # 箱線圖
    plt.subplot(1, 2, 2)
    plt.boxplot(prices)
    plt.title(f'{STOCK_ID} Price Boxplot')
    plt.ylabel('Price')

    plot_path = os.path.join(OUTPUT_DIR, f'stock_analysis_{STOCK_ID}.png')
    plt.tight_layout()
    plt.savefig(plot_path)
    print(f"統計圖表已儲存至: {plot_path}")

    # 5. 產出 REPORT
    print("\n" + "="*30)
    print("交易模擬報告 (REPORT)")
    print("="*30)
    print(f"初始本金: {INITIAL_CAPITAL} 元")
    print(f"買入價位 (最低): {min_price}")
    print(f"賣出價位 (最高): {max_price}")
    print(f"交易次數: 1 次 (區間低買高賣模擬)")
    print(f"最終獲利金額: {profit:.2f} 元")
    print(f"最終總資產: {final_value:.2f} 元")
    print(f"獲利倍率: {profit_rate:.4f} 倍")
    print(f"價格中位數: {median_price:.2f}")
    print(f"價格平均值: {mean_price:.2f}")
    print("="*30)

if __name__ == "__main__":
    run_simulation()
