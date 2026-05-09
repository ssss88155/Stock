import json
import os

VOL_LEVELS = [100000, 500000, 1500000, 5000000]

def analyze_stock_levels(input_file='stock_data_slim.json'):
    path = os.path.join('C:/jupyter_notebook/ai_twstock/', input_file)
    if not os.path.exists(path):
        print(f"Error: {path} not found.")
        return

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    level_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    total_days = 0
    
    for stock_id, details in data.items():
        price_data = details.get('price', {})
        if not price_data:
            continue
        
        # Get latest volume
        sorted_dates = sorted(price_data.keys())
        latest_date = sorted_dates[-1]
        vol = price_data[latest_date].get('Trading_Volume', 0)
        
        # Determine level
        level = 0
        if vol >= VOL_LEVELS[3]:
            level = 4
        elif vol >= VOL_LEVELS[2]:
            level = 3
        elif vol >= VOL_LEVELS[1]:
            level = 2
        elif vol >= VOL_LEVELS[0]:
            level = 1
        else:
            level = 0
            
        level_counts[level] += 1
        total_days += len(price_data)

    print(f"Total stocks: {len(data)}")
    print("Stock counts per level (based on latest Trading_Volume):")
    print(f"Level 0 (< 100k): {level_counts[0]}")
    print(f"Level 1 (100k - 500k): {level_counts[1]}")
    print(f"Level 2 (500k - 1.5M): {level_counts[2]}")
    print(f"Level 3 (1.5M - 5M): {level_counts[3]}")
    print(f"Level 4 (> 5M): {level_counts[4]}")
    
    # Calculate potential reduction
    # Level 0 stocks currently have some days (likely 30), reduce to 15.
    # We'll assume they currently have 30 days for estimation.
    current_level0_days = level_counts[0] * 30
    new_level0_days = level_counts[0] * 15
    reduction = current_level0_days - new_level0_days
    
    total_estimated_days = (level_counts[1] + level_counts[2] + level_counts[3] + level_counts[4]) * 30 + level_counts[0] * 30
    new_estimated_days = (level_counts[1] + level_counts[2] + level_counts[3] + level_counts[4]) * 30 + level_counts[0] * 15
    
    percent_reduction = (reduction / total_estimated_days) * 100 if total_estimated_days > 0 else 0
    
    print(f"\nCurrent total entries (est.): {total_estimated_days}")
    print(f"New total entries (est.): {new_estimated_days}")
    print(f"Estimated reduction in data points: {reduction} ({percent_reduction:.2f}%)")

if __name__ == "__main__":
    analyze_stock_levels()
