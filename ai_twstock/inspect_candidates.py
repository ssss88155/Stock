import backtest_momentum
import analyze_momentum
import json
import os

def inspect_candidates():
    data = analyze_momentum.load_stock_data_wrapper('stock_data.json')
    data = backtest_momentum.preprocess_data(data)
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    
    weights = {
        "WEIGHT_GAIN": 53, "WEIGHT_VOLUME": 12, "WEIGHT_FOREIGN": 4, "WEIGHT_SITC": 4,
        "WEIGHT_VCP": 9, "WEIGHT_BREAKOUT": 3, "WEIGHT_HANDOVER": 7,
        "INDUSTRY_FILTER_TOP_N": 3
    }
    threshold = 100

    periods = [('2025-07-01', '2025-07-31'), ('2025-11-01', '2026-01-31')]
    
    for start, end in periods:
        print(f"\nChecking candidates for period {start} to {end}:")
        for i, d in enumerate(all_dates):
            if start <= d <= end:
                if i > 0:
                    analysis_date = all_dates[i-1]
                    start_date_mom = all_dates[max(0, i-1-20)]
                    results = analyze_momentum.analyze_momentum(data, start_date_mom, analysis_date, weights=weights)
                    valid = [r for r in results if r['score'] >= threshold]
                    if len(valid) > 0:
                        print(f"  {d}: Found {len(valid)} candidates. Top score: {valid[0]['score']:.1f}")
                    # else:
                    #    print(f"  {d}: 0 candidates")

if __name__ == "__main__":
    inspect_candidates()
