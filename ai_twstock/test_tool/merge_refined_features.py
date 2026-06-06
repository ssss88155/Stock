import json
import os

def merge_refined_features():
    second_dir = r'C:\jupyter_notebook\ai_twstock\data\second'
    output_path = r'C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json'
    
    all_features = []
    
    print("Merging refined features from second/ directory...")
    # 遍歷 01 到 20
    for i in range(1, 21):
        filename = f'micro_feature_{i:02d}.json'
        path = os.path.join(second_dir, filename)
        
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                try:
                    chunk = json.load(f)
                    all_features.extend(chunk)
                    print(f"  Added {filename} (count: {len(chunk)})")
                except Exception as e:
                    print(f"  Error reading {filename}: {e}")
        else:
            print(f"  Warning: {filename} not found in second/")

    # 儲存最終合併檔案
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_features, f, ensure_ascii=False, indent=2)
    
    print(f"\nMerge Complete!")
    print(f"Total unique traders refined: {len(all_features)}")
    print(f"Final file saved: {output_path}")

if __name__ == "__main__":
    merge_refined_features()
