import os
import pandas as pd
import json
import keyring
from datetime import datetime, timedelta
from configparser import ConfigParser
from esun_trade.sdk import SDK
from esun_marketdata.util import TRADE_SDK_ACCOUNT_KEY, TRADE_SDK_CERT_KEY, setup_keyring

# --- 配置 ---
CONFIG_PATH = './config.ini'
PSD_PATH = 'psd.txt'
DOC_DIR = 'doc'
JSON_PATH = os.path.join(DOC_DIR, 'transactions.json')

def force_float(val):
    if val is None or val == "": return 0.0
    try: return float(val)
    except: return 0.0

def g(obj, k):
    val = getattr(obj, k, None)
    if val is None and isinstance(obj, dict): val = obj.get(k)
    return val

def get_display_width(s):
    """計算字串的顯示寬度 (中文計為 2, 英文計為 1)"""
    import unicodedata
    width = 0
    for char in str(s):
        if unicodedata.east_asian_width(char) in ('W', 'F', 'A'):
            width += 2
        else:
            width += 1
    return width

def pad_to_width(s, width, align='left'):
    """根據顯示寬度進行填充對齊"""
    s = str(s)
    current_width = get_display_width(s)
    pad_size = max(0, width - current_width)
    if align == 'left':
        return s + ' ' * pad_size
    else:
        return ' ' * pad_size + s

def main():
    try:
        if not os.path.exists(DOC_DIR): os.makedirs(DOC_DIR)
        
        # 1. 登入
        config = ConfigParser()
        config.read(CONFIG_PATH)
        account = config['User']['Account']
        password = "psd.txt"
        if os.path.exists(PSD_PATH):
            with open(PSD_PATH, 'r', encoding='utf-8') as f:
                p = f.read().strip()
                if p: password = p
        
        setup_keyring(account)
        keyring.set_password(TRADE_SDK_ACCOUNT_KEY, account, password)
        keyring.set_password(TRADE_SDK_CERT_KEY, account, password)
        
        sdk = SDK(config)
        sdk.login()

        # 2. 抓取數據
        inv_raw = sdk.get_inventories()
        inv_map = {}
        for item in inv_raw:
            s_no = g(item, 'stk_no')
            q = force_float(g(item, 'cost_qty'))
            c_sum = abs(force_float(g(item, 'cost_sum')))
            inv_map[s_no] = {
                "尚餘股數": q,
                "尚餘均價": c_sum / q if q > 0 else 0,
                "現價": force_float(g(item, 'price_mkt')),
                "未實現": force_float(g(item, 'make_a_sum'))
            }

        tx_all = []
        for i in range(12):
            end_dt = datetime.now() - timedelta(days=i*30)
            start_dt = end_dt - timedelta(days=30)
            try:
                res = sdk.get_transactions_by_date(start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
                if res: tx_all.extend(res)
            except: continue

        # 3. 更新 JSON
        history = {}
        if os.path.exists(JSON_PATH):
            with open(JSON_PATH, 'r', encoding='utf-8') as f:
                try: history = json.load(f)
                except: history = {}

        for tx in tx_all:
            t_date = g(tx, 't_date') or 'Unknown'
            if t_date not in history: history[t_date] = []
            
            # 解析
            total_fee = 0
            mat_dats = g(tx, 'mat_dats') or []
            for mat in mat_dats:
                total_fee += force_float(g(mat, 'fee')) + force_float(g(mat, 'tax'))

            side = g(tx, 'buy_sell')
            p_qty = force_float(g(tx, 'price_qty'))
            
            entry = {
                "stk_no": g(tx, 'stk_no'),
                "stk_na": g(tx, 'stk_na'),
                "side": side,
                "amount": p_qty,
                "profit": force_float(g(tx, 'make'))
            }
            if not any(h['stk_no'] == entry['stk_no'] and h['amount'] == entry['amount'] and h['side'] == entry['side'] for h in history[t_date]):
                history[t_date].append(entry)

        with open(JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        # 4. 生成報表數據
        all_json_tx = [t for tasks in history.values() for t in tasks]
        df_hist = pd.DataFrame(all_json_tx)
        report_rows = []
        
        if not df_hist.empty:
            for s_no, group in df_hist.groupby('stk_no'):
                s_na = group['stk_na'].iloc[-1]
                buy_amt = group[group['side'] == 'B']['amount'].sum()
                sell_amt = group[group['side'] == 'S']['amount'].sum()
                cash_p = group['profit'].sum()
                inv = inv_map.get(s_no, {"尚餘股數": 0, "尚餘均價": 0, "現價": 0, "未實現": 0})
                
                report_rows.append({
                    "編號": s_no, "公司": s_na, "購買金額": buy_amt, "賣出金額": sell_amt,
                    "現金盈虧": cash_p, "尚餘股數": inv["尚餘股數"], "均價": inv["尚餘均價"],
                    "現價": inv["現價"], "總盈虧": cash_p + inv["未實現"]
                })

        for s_no, inv in inv_map.items():
            if not any(r['編號'] == s_no for r in report_rows):
                report_rows.append({
                    "編號": s_no, "公司": "(庫存)", "購買金額": 0, "賣出金額": 0, "現金盈虧": 0,
                    "尚餘股數": inv["尚餘股數"], "均價": inv["尚餘均價"], "現價": inv["現價"], "總盈虧": inv["未實現"]
                })

        # 5. 美化表格輸出 (手動對齊)
        headers = ["編號", "公司", "購買金額", "賣出金額", "現金盈虧", "尚餘股數", "均價", "現價", "總盈虧"]
        widths = [8, 14, 12, 12, 12, 10, 10, 10, 12]
        
        print("\n" + "="*110)
        print("  玉山證券投資績效對帳表")
        print("="*110)
        
        # 標題列
        header_line = ""
        for h, w in zip(headers, widths):
            header_line += pad_to_width(h, w)
        print(header_line)
        print("-" * 110)
        
        # 資料列
        for r in report_rows:
            line = ""
            line += pad_to_width(r["編號"], widths[0])
            line += pad_to_width(r["公司"], widths[1])
            line += pad_to_width(f"{r['購買金額']:,.0f}", widths[2], 'left')
            line += pad_to_width(f"{r['賣出金額']:,.0f}", widths[3], 'left')
            line += pad_to_width(f"{r['現金盈虧']:,.0f}", widths[4], 'left')
            line += pad_to_width(f"{r['尚餘股數']:,.0f}", widths[5], 'left')
            line += pad_to_width(f"{r['均價']:.2f}", widths[6], 'left')
            line += pad_to_width(f"{r['現價']:.2f}", widths[7], 'left')
            line += pad_to_width(f"{r['總盈虧']:,.0f}", widths[8], 'left')
            print(line)
            
        print("-" * 110)
        total_cash = sum(r["現金盈虧"] for r in report_rows)
        total_combined = sum(r["總盈虧"] for r in report_rows)
        print(f"累計現金盈虧: {total_cash:,.0f} 元")
        print(f"最終預估盈虧: {total_combined:,.0f} 元\n")

    except Exception as e:
        print(f"[Error] {e}")

if __name__ == "__main__":
    main()
