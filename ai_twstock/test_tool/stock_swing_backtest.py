import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
from scipy.signal import argrelextrema

# 設定路徑
DB_PATH = r'C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db'
OUTPUT_DIR = r'C:\jupyter_notebook\ai_twstock\test_tool'
STOCK_ID = '0050'
START_DATE = '2026-05-01'
END_DATE = '2026-06-15'
INITIAL_CAPITAL = 30000

def run_swing_simulation():
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

    # 2. 尋找波段高低點 (局部極值)
    # 使用 scipy 尋找局部最小與最大值
    n = 2 # 比較前後 n 天
    df['min_idx'] = argrelextrema(df['low'].values, np.less_equal, order=n)[0].tolist() + [None] * (len(df) - len(argrelextrema(df['low'].values, np.less_equal, order=n)[0]))
    
    # 手動標記局部高低點以進行模擬
    local_min_indices = argrelextrema(df['low'].values, np.less_equal, order=n)[0]
    local_max_indices = argrelextrema(df['high'].values, np.greater_equal, order=n)[0]

    # 3. 模擬波段交易邏輯 (極大化獲利模擬)
    # 策略：在每個局部低點買入，在下一個局部高點賣出
    cash = INITIAL_CAPITAL
    shares = 0
    transactions = []
    last_action_idx = -1

    # 合併並排序所有極值點
    extrema = []
    for idx in local_min_indices:
        extrema.append((idx, 'BUY', df.iloc[idx]['low']))
    for idx in local_max_indices:
        extrema.append((idx, 'SELL', df.iloc[idx]['high']))
    
    extrema.sort()

    # 簡化邏輯：確保買賣交替且獲利
    for idx, action, price in extrema:
        if idx <= last_action_idx:
            continue
            
        if action == 'BUY' and shares == 0:
            # 買入
            shares = cash / price
            buy_price = price
            buy_date = df.iloc[idx]['date']
            cash = 0
            transactions.append({'date': buy_date, 'action': 'BUY', 'price': price, 'shares': shares})
            last_action_idx = idx
        elif action == 'SELL' and shares > 0:
            # 賣出 (僅當價格高於買入價或為波段高點)
            if price > buy_price:
                cash = shares * price
                profit = cash - (shares * buy_price)
                transactions.append({'date': df.iloc[idx]['date'], 'action': 'SELL', 'price': price, 'profit': profit})
                shares = 0
                last_action_idx = idx

    # 若結束時還持有股票，以最後一天收盤價賣出
    if shares > 0:
        final_price = df.iloc[-1]['close']
        cash = shares * final_price
        profit = cash - (shares * buy_price)
        transactions.append({'date': df.iloc[-1]['date'], 'action': 'SELL_END', 'price': final_price, 'profit': profit})
        shares = 0

    final_value = cash
    total_profit = final_value - INITIAL_CAPITAL
    profit_rate = final_value / INITIAL_CAPITAL
    num_trades = len([t for t in transactions if t['action'].startswith('SELL')])

    # 4. 統計圖表
    prices = df['close']
    median_price = prices.median()

    plt.figure(figsize=(15, 10))
    
    # 子圖 1: 價格走勢與買賣點
    plt.subplot(2, 1, 1)
    plt.plot(df['date'], df['close'], label='Close Price', color='gray', alpha=0.5)
    plt.scatter(df.iloc[local_min_indices]['date'], df.iloc[local_min_indices]['low'], color='red', marker='^', label='Local Min')
    plt.scatter(df.iloc[local_max_indices]['date'], df.iloc[local_max_indices]['high'], color='green', marker='v', label='Local Max')
    
    # 標記實際交易點
    for t in transactions:
        color = 'red' if 'BUY' in t['action'] else 'green'
        plt.annotate(t['action'], (t['date'], t['price']), textcoords="offset points", xytext=(0,10), ha='center', color=color, weight='bold')

    plt.title(f'{STOCK_ID} Swing Trading Simulation ({START_DATE} ~ {END_DATE})')
    plt.xticks(rotation=45)
    plt.legend()

    # 子圖 2: 價格分佈 (中位數與集中度)
    plt.subplot(2, 2, 3)
    plt.hist(prices, bins=15, color='skyblue', edgecolor='black')
    plt.axvline(median_price, color='orange', linestyle='--', label=f'Median: {median_price:.2f}')
    plt.title('Price Distribution')
    plt.legend()

    # 子圖 3: 獲利貢獻
    plt.subplot(2, 2, 4)
    sell_profits = [t['profit'] for t in transactions if 'profit' in t]
    plt.bar(range(len(sell_profits)), sell_profits, color='gold')
    plt.title('Profit per Trade')
    plt.ylabel('Amount (TWD)')

    plot_path = os.path.join(OUTPUT_DIR, f'stock_swing_analysis_{STOCK_ID}.png')
    plt.tight_layout()
    plt.savefig(plot_path)
    print(f"波段分析圖表已儲存至: {plot_path}")

    # 5. 產出 REPORT
    print("\n" + "="*30)
    print("波段交易模擬報告 (REPORT)")
    print("="*30)
    print(f"初始本金: {INITIAL_CAPITAL} 元")
    print(f"最終總資產: {final_value:.2f} 元")
    print(f"總獲利金額: {total_profit:.2f} 元")
    print(f"獲利倍率: {profit_rate:.4f} 倍")
    print(f"總交易次數 (賣出計): {num_trades} 次")
    print("\n交易明細:")
    for t in transactions:
        if 'profit' in t:
            print(f"- {t['date']} {t['action']}: 價格 {t['price']:.2f}, 獲利 {t['profit']:.2f}")
        else:
            print(f"- {t['date']} {t['action']}: 價格 {t['price']:.2f}")
    
    print(f"\n價格統計:")
    print(f"中位數: {median_price:.2f}")
    print(f"集中區間 (10%-90%): {np.percentile(prices, 10):.2f} ~ {np.percentile(prices, 90):.2f}")
    print("="*30)

if __name__ == "__main__":
    run_swing_simulation()
