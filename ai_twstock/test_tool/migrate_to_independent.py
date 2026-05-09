import json
import os

def migrate():
    source_file = 'stock_data.json'
    target_dir = 'data_independent'
    
    if not os.path.exists(source_file):
        print(f"Source file {source_file} not found.")
        return

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    print(f"Reading {source_file}...")
    with open(source_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"Splitting into {len(data)} files...")
    for stock_id, stock_data in data.items():
        target_path = os.path.join(target_dir, f"{stock_id}.json")
        with open(target_path, 'w', encoding='utf-8') as f:
            json.dump({stock_id: stock_data}, f, ensure_ascii=False, indent=4)
    
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
