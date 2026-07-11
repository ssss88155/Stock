import os

def peek_file():
    path = 'stock_data_micro.json'
    if not os.path.exists(path):
        print("File not found")
        return
    
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read(2000)
        print("--- File Start (2000 chars) ---")
        print(content)
        print("--- End Peek ---")

if __name__ == "__main__":
    peek_file()
