import json
import os

VOL_LEVELS = [100000, 500000, 1500000, 5000000]

def calculate_actual_reduction(input_file='stock_data.json'):
    path = os.path.join('C:/jupyter_notebook/ai_twstock/', input_file)
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    current_total = 0
    new_total = 0
    level_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    
    for stock_id, details in data.items():
        price_data = details.get('price', {})
        if not price_data: continue
        
        current_total += len(price_data)
        
        sorted_dates = sorted(price_data.keys())
        vol = price_data[sorted_dates[-1]].get('Trading_Volume', 0)
        
        level = 0
        if vol >= VOL_LEVELS[3]: level = 4
        elif vol >= VOL_LEVELS[2]: level = 3
        elif vol >= VOL_LEVELS[1]: level = 2
        elif vol >= VOL_LEVELS[0]: level = 1
        else: level = 0
        
        level_counts[level] += 1
        
        keep = 30 if level > 0 else 15
        new_total += min(len(price_data), keep)

    reduction = current_total - new_total
    percent = (reduction / current_total) * 100 if current_total > 0 else 0
    
    print(f"Current entries: {current_total}")
    print(f"New entries: {new_total}")
    print(f"Reduction: {reduction} ({percent:.2f}%)")
    print(f"\nCounts per level:")
    for i in range(5):
        print(f"Level {i}: {level_counts[i]} stocks")

if __name__ == "__main__":
    calculate_actual_reduction()
