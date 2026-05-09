import json
import os
import sys

def lookup_stock(stock_id, filename='stock_data_tmp.json'):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    if not os.path.exists(path):
        print(f"Error: {filename} not found.")
        return

    print(f"Searching for {stock_id} in {filename}...")
    
    # We still need to load it, but we do it in Python which handles 200MB easily, 
    # unlike VS Code's text editor which tries to highlight/format it.
    with open(path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f"Error loading JSON: {e}")
            return

    stock_data = data.get(stock_id)
    if not stock_data:
        print(f"Stock {stock_id} not found.")
        return

    # Pretty print the result
    print(json.dumps({stock_id: stock_data}, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python lookup_stock.py <stock_id> [filename]")
    else:
        sid = sys.argv[1]
        fn = sys.argv[2] if len(sys.argv) > 2 else 'stock_data_tmp.json'
        lookup_stock(sid, fn)
