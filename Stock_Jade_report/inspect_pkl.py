import pickle
import os

pkl_path = r'C:\jupyter_notebook\Stock_Jade_report\doc\data_snapshot.p'
if os.path.exists(pkl_path):
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)
    
    tx = data.get('tx', [])
    if tx:
        print("--- Transaction Object Keys ---")
        # 如果是字典
        if isinstance(tx[0], dict):
            print(tx[0].keys())
            print("Sample data:", tx[0])
        else:
            # 如果是物件，列出屬性
            print(dir(tx[0]))
            # 嘗試轉成 dict
            try:
                print("As dict:", vars(tx[0]))
            except:
                pass
    else:
        print("No transactions found in pkl")
        
    inv = data.get('inv', [])
    if inv:
        print("\n--- Inventory Object Keys ---")
        if isinstance(inv[0], dict):
            print(inv[0].keys())
        else:
            print(dir(inv[0]))
else:
    print("Pkl file not found")
