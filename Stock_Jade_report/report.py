import os
import pandas as pd
import json
import keyring
import argparse
import calendar
import pickle
from datetime import datetime, timedelta
from configparser import ConfigParser
from esun_trade.sdk import SDK
from esun_marketdata.util import TRADE_SDK_ACCOUNT_KEY, TRADE_SDK_CERT_KEY, setup_keyring

# --- 配置區 ---
CONFIG_PATH = './config.ini'
PSD_PATH = 'psd.txt'
DOC_DIR = 'doc'
JSON_PATH = os.path.join(DOC_DIR, 'transactions.json')
INV_CACHE = os.path.join(DOC_DIR, 'inv_cache.p')

def force_float(val):
    if val is None or val == "": return 0.0
    try: return float(val)
    except: return 0.0

def g(obj, k):
    val = getattr(obj, k, None)
    if val is None and isinstance(obj, dict): val = obj.get(k)
    return val

def get_display_width(s):
    import unicodedata
    width = 0
    for char in str(s):
        if unicodedata.east_asian_width(char) in ('W', 'F', 'A'): width += 2
        else: width += 1
    return width

def pad_to_width(s, width, align='left'):
    s = str(s)
    current_width = get_display_width(s)
    pad_size = max(0, width - current_width)
    if align == 'left': return s + ' ' * pad_size
    else: return ' ' * pad_size + s

def login_sdk():
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
    return sdk

def update_json_history(tx_list):
    history = {}
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            try: history = json.load(f)
            except: history = {}

    for tx in tx_list:
        t_date = g(tx, 't_date') or 'Unknown'
        if t_date not in history: history[t_date] = []
        mat_dats = g(tx, 'mat_dats') or []
        fee = sum(force_float(g(m, 'fee')) + force_float(g(m, 'tax')) for m in mat_dats)
        entry = {
            "stk_no": g(tx, 'stk_no'), "stk_na": g(tx, 'stk_na'), "side": g(tx, 'buy_sell'),
            "amount": force_float(g(tx, 'price_qty')), "fee": fee, "profit": force_float(g(tx, 'make'))
        }
        # 以股票編號、金額、買賣別去重
        if not any(h['stk_no'] == entry['stk_no'] and h['amount'] == entry['amount'] and h['side'] == entry['side'] for h in history[t_date]):
            history[t_date].append(entry)

    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', type=int, nargs='?', default=0, help='模式 (0:不抓, -1:抓一年, 1-12:抓該月)')
    args = parser.parse_args()

    print(f"\n[模式說明] 0:讀取本地 | -1:同步一年 | 1-12:同步該月份資料。目前輸入: {args.mode}")
    
    # 決定過濾範圍
    display_start = "2000-01-01"
    display_end = "2099-12-31"
    if 1 <= args.mode <= 12:
        y = datetime.now().year
        ld = calendar.monthrange(y, args.mode)[1]
        display_start = f"{y}-{args.mode:02d}-01"
        display_end = f"{y}-{args.mode:02d}-{ld:02d}"
    
    try:
        if not os.path.exists(DOC_DIR): os.makedirs(DOC_DIR)
        inv_map = {}
        sdk_online = False
        
        # 1. SDK 同步
        try:
            sdk = login_sdk()
            sdk_online = True
            inv_raw = sdk.get_inventories()
            with open(INV_CACHE, 'wb') as f: pickle.dump(inv_raw, f)
            
            if args.mode == -1:
                print("[DEBUG] 正在抓取年度紀錄...")
                for i in range(12):
                    e = datetime.now() - timedelta(days=i*30)
                    s = e - timedelta(days=30)
                    try:
                        res = sdk.get_transactions_by_date(s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d"))
                        if res: update_json_history(res)
                    except: continue
            elif 1 <= args.mode <= 12:
                y = datetime.now().year
                ld = calendar.monthrange(y, args.mode)[1]
                s_str = f"{y}-{args.mode:02d}-01"
                # 結束日期不能超過今天
                today_str = datetime.now().strftime("%Y-%m-%d")
                e_str = min(f"{y}-{args.mode:02d}-{ld:02d}", today_str)
                print(f"[DEBUG] 正在同步 {s_str} ~ {e_str}...")
                res = sdk.get_transactions_by_date(s_str, e_str)
                if res: update_json_history(res)
        except Exception as e:
            print(f"[DEBUG] 無法同步最新資料: {e}")

        # 2. 準備庫存數據 (SDK優先, 否則快取)
        if not inv_map:
            source = INV_CACHE if os.path.exists(INV_CACHE) else None
            if source:
                with open(source, 'rb') as f:
                    ir = pickle.load(f)
                    for item in ir:
                        s_no = g(item, 'stk_no')
                        q = force_float(g(item, 'cost_qty'))
                        c_sum = abs(force_float(g(item, 'cost_sum')))
                        inv_map[s_no] = {
                            "尚餘股數": q, "均價": c_sum / q if q > 0 else 0, "總成本": c_sum,
                            "現價": force_float(g(item, 'price_mkt')), "未實現": force_float(g(item, 'make_a_sum'))
                        }

        # 3. 讀取與過濾 JSON 歷史
        if not os.path.exists(JSON_PATH):
            print("⚠️ 找不到資料庫，請先執行同步 (參數 -1)")
            return
        with open(JSON_PATH, 'r', encoding='utf-8') as f: history = json.load(f)

        filtered_tx = []
        for d, tasks in history.items():
            cd = d.replace('/', '-').replace('.', '-')
            if display_start <= cd <= display_end: filtered_tx.extend(tasks)

        # 4. 彙整報表
        report_rows = []
        if filtered_tx:
            df_tx = pd.DataFrame(filtered_tx)
            for s_no, gp in df_tx.groupby('stk_no'):
                inv = inv_map.get(s_no, {"尚餘股數": 0, "均價": 0, "現價": 0, "未實現": 0, "總成本": 0})
                report_rows.append({
                    "編號": s_no, "公司": gp['stk_na'].iloc[-1],
                    "購買金額": gp[gp['side']=='B']['amount'].sum(),
                    "賣出金額": gp[gp['side']=='S']['amount'].sum(),
                    "現金盈虧": gp['profit'].sum(),
                    "尚餘股數": inv["尚餘股數"], "均價": inv["均價"], "現價": inv["現價"],
                    "總盈虧": gp['profit'].sum() + inv["未實現"], "庫存成本": inv["總成本"]
                })

        # 加上有庫存但在選定期間沒交易的
        for s_no, inv in inv_map.items():
            if not any(r['編號'] == s_no for r in report_rows):
                report_rows.append({
                    "編號": s_no, "公司": "(庫存)", "購買金額": 0, "賣出金額": 0, "現金盈虧": 0,
                    "尚餘股數": inv["尚餘股數"], "均價": inv["均價"], "現價": inv["現價"],
                    "總盈虧": inv["未實現"], "庫存成本": inv["總成本"]
                })

        # 5. 表格渲染
        headers = ["編號", "公司", "購買金額", "賣出金額", "現金盈虧", "尚餘股數", "均價", "現價", "總盈虧"]
        widths = [8, 14, 12, 12, 12, 10, 10, 10, 12]
        print("\n" + "="*110 + f"\n  玉山證券 投資績效彙整報表 ({display_start} ~ {display_end})\n" + "="*110)
        print("".join(pad_to_width(h, w) for h, w in zip(headers, widths)))
        print("-" * 110)
        for r in report_rows:
            line = pad_to_width(r["編號"], widths[0]) + pad_to_width(r["公司"], widths[1])
            line += pad_to_width(f"{r['購買金額']:,.0f}", widths[2]) + pad_to_width(f"{r['賣出金額']:,.0f}", widths[3])
            line += pad_to_width(f"{r['現金盈虧']:,.0f}", widths[4]) + pad_to_width(f"{r['尚餘股數']:,.0f}", widths[5])
            line += pad_to_width(f"{r['均價']:.2f}", widths[6]) + pad_to_width(f"{r['現價']:.2f}", widths[7])
            line += pad_to_width(f"{r['總盈虧']:,.0f}", widths[8])
            print(line)

        # 總和列 (Back!)
        print("-" * 110)
        s_buy = sum(r["購買金額"] for r in report_rows)
        s_sell = sum(r["賣出金額"] for r in report_rows)
        s_cash = sum(r["現金盈虧"] for r in report_rows)
        s_total = sum(r["總盈虧"] for r in report_rows)
        sum_line = pad_to_width("總計", widths[0]) + pad_to_width("", widths[1])
        sum_line += pad_to_width(f"{s_buy:,.0f}", widths[2]) + pad_to_width(f"{s_sell:,.0f}", widths[3])
        sum_line += pad_to_width(f"{s_cash:,.0f}", widths[4]) + pad_to_width("", widths[5])
        sum_line += pad_to_width("", widths[6]) + pad_to_width("", widths[7])
        sum_line += pad_to_width(f"{s_total:,.0f}", widths[8])
        print(sum_line)
        print("=" * 110)

        # 總體摘要
        sum_inv_cost = sum(r["庫存成本"] for r in report_rows)
        cash_pct = (s_cash / s_buy * 100) if s_buy > 0 else 0
        final_pct = (s_total / s_buy * 100) if s_buy > 0 else 0
        print(f"目前總投入金額: {sum_inv_cost:,.0f} 元")
        print(f"累計現金盈虧 (已實現): {s_cash:,.0f} 元 ({cash_pct:.2f}%)")
        print(f"最終預估盈虧 (含持股): {s_total:,.0f} 元 ({final_pct:.2f}%)")
        print("-" * 110 + "\n")

    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
