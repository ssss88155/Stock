import json
import os
import sys

def shrink_data(input_file='stock_data.json', output_file='stock_data_slim.json'):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), input_file)
    if not os.path.exists(path):
        print(f"Error: {input_file} not found.")
        return

    print(f"Loading {input_file} (this may take a moment)...")
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 交易量級距 (單位：股) - Match analyze_momentum.py
    VOL_LEVELS = [100000, 500000, 1500000, 5000000]

    slim_data = {}
    print(f"Shrinking data with dynamic retention (Top 4 levels: 30 days, Level 0: 15 days)...")
    
    counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}

    for stock_id, details in data.items():
        price_data = details.get('price', {})
        inst_data = details.get('institutional', {})
        
        if not price_data:
            continue
            
        # Determine level based on latest volume
        sorted_dates = sorted(price_data.keys())
        latest_date = sorted_dates[-1]
        vol = price_data[latest_date].get('Trading_Volume', 0)
        
        level = 0
        if vol >= VOL_LEVELS[3]: level = 4
        elif vol >= VOL_LEVELS[2]: level = 3
        elif vol >= VOL_LEVELS[1]: level = 2
        elif vol >= VOL_LEVELS[0]: level = 1
        else: level = 0
        
        counts[level] += 1
        keep_days = 30 if level > 0 else 15
        
        dates_to_keep = sorted_dates[-keep_days:]
        
        new_price = {d: price_data[d] for d in dates_to_keep}
        new_inst = {d: inst_data[d] for d in dates_to_keep if d in inst_data}
        
        slim_data[stock_id] = {
            'price': new_price,
            'institutional': new_inst
        }

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_file)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(slim_data, f, ensure_ascii=False, indent=2)
    
    original_size = os.path.getsize(path) / (1024*1024)
    new_size = os.path.getsize(out_path) / (1024*1024)
    
    print(f"Done!")
    print(f"Original size: {original_size:.2f} MB")
    print(f"New size: {new_size:.2f} MB")
    print(f"Stocks per level: {counts}")
    print(f"Slim data saved to: {output_file}")

if __name__ == "__main__":
    shrink_data()
