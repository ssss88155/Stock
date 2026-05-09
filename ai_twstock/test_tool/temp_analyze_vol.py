import json
import os
import statistics

def get_script_dir():
    return os.path.dirname(os.path.abspath(__file__))

def analyze_volumes(filename='stock_data.json'):
    path = os.path.join(get_script_dir(), filename)
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    all_volumes = []
    for stock_id, details in data.items():
        price_data = details.get('price', {})
        if not price_data:
            continue
        
        sorted_dates = sorted(price_data.keys())
        latest_date = sorted_dates[-1]
        vol = price_data[latest_date].get('Trading_Volume', 0)
        if vol > 0:
            all_volumes.append(vol)

    if not all_volumes:
        print("No volume data found.")
        return

    all_volumes.sort()
    count = len(all_volumes)
    
    print(f"Total stocks with volume: {count}")
    print(f"Min: {min(all_volumes):,}")
    print(f"Max: {max(all_volumes):,}")
    print(f"Median: {statistics.median(all_volumes):,}")
    
    # Calculate quantiles for 5 levels (20th, 40th, 60th, 80th percentiles)
    levels = [20, 40, 60, 80]
    results = {}
    for p in levels:
        val = all_volumes[int(count * p / 100)]
        results[p] = val
        print(f"{p}th percentile: {val:,}")

if __name__ == "__main__":
    analyze_volumes()
