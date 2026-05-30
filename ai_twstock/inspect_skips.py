import backtest_momentum
import analyze_momentum
import json
import os
import pandas as pd

def inspect_skipped_periods():
    data = analyze_momentum.load_stock_data_wrapper('stock_data.json')
    data = backtest_momentum.preprocess_data(data)
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    
    # 2. 指數趨勢 (0050 是否站在 MA20 之上)
    def check_market(date_idx):
        if date_idx < 20: return True, 1.0, True
        target_date = all_dates[date_idx]
        
        above_ma = 0; total = 0
        for sid in data:
            prices = [data[sid]['price'][d]['close'] for d in all_dates[date_idx-10:date_idx+1] if d in data[sid]['price']]
            if len(prices) < 10: continue
            ma10 = sum(prices[:-1]) / 10
            if prices[-1] > ma10: above_ma += 1
            total += 1
        breadth = above_ma / total if total > 0 else 1.0
        
        index_bullish = True
        if '0050' in data:
            idx_prices = [data['0050']['price'][d]['close'] for d in all_dates[date_idx-20:date_idx+1] if d in data['0050']['price']]
            if len(idx_prices) >= 20:
                ma20 = sum(idx_prices[:-1]) / 20
                index_bullish = idx_prices[-1] > ma20
        
        pass_filter = index_bullish or (breadth >= 0.5)
        return pass_filter, breadth, index_bullish

    periods = [('2025-07-01', '2025-07-31'), ('2025-11-01', '2026-01-31')]
    
    for start, end in periods:
        print(f"\nChecking period {start} to {end}:")
        count_skipped = 0
        total_days = 0
        for i, d in enumerate(all_dates):
            if start <= d <= end:
                total_days += 1
                pass_f, br, idx_b = check_market(i)
                if not pass_f:
                    count_skipped += 1
                    # print(f"  {d}: SKIPPED (Breadth: {br:.1%}, Bullish: {idx_b})")
        print(f"Total days: {total_days}, Skipped by market filter: {count_skipped}")

if __name__ == "__main__":
    inspect_skipped_periods()
