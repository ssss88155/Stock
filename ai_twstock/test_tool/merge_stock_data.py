import json
import os
import time

def merge_incremental():
    source_dir = 'data_independent'
    target_file = 'stock_data.json'
    
    if not os.path.exists(source_dir):
        print(f"Source directory {source_dir} not found.")
        return

    # Get last merge time (mtime of target_file)
    last_merge_time = 0
    if os.path.exists(target_file):
        last_merge_time = os.path.getmtime(target_file)
    
    files = [f for f in os.listdir(source_dir) if f.endswith('.json')]
    changed_files = []
    
    for filename in files:
        path = os.path.join(source_dir, filename)
        if os.path.getmtime(path) > last_merge_time:
            changed_files.append(filename)
            
    if not changed_files:
        print("No changes detected since last merge.")
        return

    print(f"Detected {len(changed_files)} changed stocks.")
    
    merged_data = {}
    if os.path.exists(target_file):
        print(f"Loading existing {target_file}...")
        try:
            with open(target_file, 'r', encoding='utf-8') as f:
                merged_data = json.load(f)
        except Exception as e:
            print(f"Error loading {target_file}, performing full merge: {e}")
            merged_data = {}

    print(f"Updating {len(changed_files)} stocks...")
    for filename in changed_files:
        path = os.path.join(source_dir, filename)
        with open(path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                merged_data.update(data)
            except Exception as e:
                print(f"Error reading {filename}: {e}")

    # Optional: Sort by stock ID
    print("Sorting data...")
    sorted_data = dict(sorted(merged_data.items()))

    print(f"Writing {target_file}...")
    # Using a temporary file to ensure atomicity
    temp_file = target_file + ".tmp"
    with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump(sorted_data, f, ensure_ascii=False, indent=4)
    
    # Replace old file
    if os.path.exists(target_file):
        os.remove(target_file)
    os.rename(temp_file, target_file)
    
    print("Merge complete.")

if __name__ == "__main__":
    merge_incremental()
