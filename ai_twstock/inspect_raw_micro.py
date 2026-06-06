import os
import json
import pandas as pd
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import sys

# 將 lib 目錄加入 Python 路徑
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
from common_lib import get_script_dir

def load_config():
    config_path = os.path.join(get_script_dir(__file__), 'config', 'find_mind_config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

def inspect_raw_data():
    config = load_config()
    token = None
    for k in sorted(config.keys()):
        if k.startswith('find_mind') and config[k].get('token'):
            token = config[k]['token']
            break
    
    if not token:
        print("No token found!")
        return

    api = DataLoader()
    api.login_by_token(token)
    
    stock_id = '3081'
    date_str = '2026-05-29' # 使用一個確定的交易日
    
    print(f"--- Inspecting Raw Data for {stock_id} on {date_str} ---")

    datasets = [
        ('1. 當日券商分點統計表 (TradingDailyReport)', "TaiwanStockTradingDailyReport"),
        ('2. 台股分點資料表 (SecuritiesTraderInfo)', "TaiwanSecuritiesTraderInfo"),
        ('3. 鉅額交易買賣日報表 (BookAndTrade)', "TaiwanStockStatisticsOfOrderBookAndTrade"),
        ('4. 台股八大行庫買賣表 (GovernmentBankBuySell)', "TaiwanStockGovernmentBankBuySell"),
        ('5. 借貸款項擔保品餘額表 (MarginMaintenance)', "TaiwanTotalExchangeMarginMaintenance"),
    ]

    for label, dataset_name in datasets:
        try:
            print(f"\n[{label}]")
            # 使用最原始的 get_data 獲取原始 DataFrame
            # 大部分需要 date 或 start_date
            params = {"dataset": dataset_name}
            if dataset_name != "TaiwanSecuritiesTraderInfo":
                params["start_date"] = date_str
                params["end_date"] = date_str
            
            # 部分接口需要 data_id
            if dataset_name in ["TaiwanStockTradingDailyReport", "TaiwanStockGovernmentBankBuySell"]:
                params["data_id"] = stock_id

            df = api.get_data(**params)
            
            if not df.empty:
                # 輸出前幾筆 raw data (dict 格式)
                raw_sample = df.head(3).to_dict(orient='records')
                print(json.dumps(raw_sample, indent=4, ensure_ascii=False))
                print(f"Total rows: {len(df)}")
            else:
                print("No data returned.")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    inspect_raw_data()
