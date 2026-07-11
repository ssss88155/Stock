import json
import os

def find_brokers():
    path = 'stock_data.json'
    if not os.path.exists(path):
        print("File not found")
        return
    
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    found_count = 0
    for sid, details in data.items():
        inst = details.get('institutional', {})
        for date, day_data in inst.items():
            if 'brokers' in day_data and day_data['brokers']:
                print(f"Found brokers in {sid} on {date}")
                found_count += 1
                break
        if found_count >= 5:
            break
    
    if found_count == 0:
        print("No broker data found in any stock")

if __name__ == "__main__":
    find_brokers()
