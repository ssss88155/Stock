import pandas as pd
from datetime import datetime

# Mock 數據測試
def test_logic():
    # 模擬 SDK 回傳的庫存資料
    inv_raw = [
        {'stk_no': '0050', 'stk_na': '元大台灣50', 'cost_qty': 1000, 'cost_sum': -72350, 'price_mkt': 97.0, 'make_a_sum': 24650},
        {'stk_no': '2330', 'stk_na': '台積電', 'cost_qty': 500, 'cost_sum': -250000, 'price_mkt': 600.0, 'make_a_sum': 50000}
    ]
    
    # 模擬 SDK 回傳的成交資料
    tx_raw = [
        {'stk_no': '0050', 'stk_na': '元大台灣50', 'buy_price': 72.35, 'buy_qty': 1000, 'sell_price': 0, 'sell_qty': 0, 'make_a': 0, 't_date': '2026-05-01'},
        {'stk_no': '2330', 'stk_na': '台積電', 'buy_price': 500, 'buy_qty': 500, 'sell_price': 0, 'sell_qty': 0, 'make_a': 0, 't_date': '2026-05-02'}
    ]

    # 模擬報表邏輯
    inv_map = {}
    for item in inv_raw:
        qty = float(item.get('cost_qty', 0))
        cost_sum = abs(float(item.get('cost_sum', 0)))
        inv_map[item.get('stk_no')] = {
            "尚餘股數": qty,
            "尚餘均價": cost_sum / qty if qty > 0 else 0,
            "現價": float(item.get('price_mkt', 0)),
            "未實現": float(item.get('make_a_sum', 0))
        }

    results = []
    tx_df = pd.DataFrame(tx_raw)
    for stk_no, group in tx_df.groupby('stk_no'):
        stk_na = group['stk_na'].iloc[0]
        buy_amt = (group['buy_price'].astype(float) * group['buy_qty'].astype(float)).sum()
        sell_amt = (group['sell_price'].astype(float) * group['sell_qty'].astype(float)).sum()
        cash_profit = group['make_a'].astype(float).sum()
        inv = inv_map.get(stk_no, {"尚餘股數": 0, "尚餘均價": 0, "現價": 0, "未實現": 0})
        
        results.append({
            "編號": stk_no, "公司": stk_na, "購買金額": buy_amt, "賣出金額": sell_amt,
            "現金盈虧": cash_profit, "尚餘股數": inv["尚餘股數"], "尚餘均價": inv["尚餘均價"],
            "現價": inv["現價"], "總盈虧": cash_profit + inv["未實現"]
        })

    df = pd.DataFrame(results)
    print("\n--- 模擬測試結果 ---")
    print(df.to_string(index=False))
    return True

if __name__ == "__main__":
    test_logic()
