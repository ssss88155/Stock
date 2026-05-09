import os
import pandas as pd
import json
import keyring
import argparse
import calendar
import pickle
from datetime import datetime, timedelta
from collections import OrderedDict
from configparser import ConfigParser
from esun_trade.sdk import SDK
from esun_marketdata.util import TRADE_SDK_ACCOUNT_KEY, TRADE_SDK_CERT_KEY, setup_keyring

# --- 配置區 ---
CONFIG_PATH = './config.ini'
PSD_PATH = 'psd.txt'
DOC_DIR = 'doc'
JSON_PATH = os.path.join(DOC_DIR, 'transactions.json')
INV_CACHE = os.path.join(DOC_DIR, 'inv_cache.p')
LOCAL_DATA_DIR = r'C:\jupyter_notebook\ai_twstock\data_independent'

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

def parse_date(d_str):
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try: return datetime.strptime(d_str, fmt)
        except: continue
    return None

def get_local_price(stk_no, target_date_obj):
    stk_no = str(stk_no).lower()
    path = os.path.join(LOCAL_DATA_DIR, f"{stk_no}.json")
    if not os.path.exists(path): return None
    try:
        with open(path, 'r', encoding='utf-8') as f: data = json.load(f)
        stk_data = data.get(stk_no.upper()) or data.get(stk_no)
        if not stk_data: return None
        prices = stk_data.get('price', {})
        target_str = target_date_obj.strftime("%Y-%m-%d")
        if target_str in prices: return force_float(prices[target_str].get('close'))
        available_dates = sorted([d for d in prices.keys() if d <= target_str], reverse=True)
        if available_dates: return force_float(prices[available_dates[0]].get('close'))
    except: pass
    return None

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
        t_date = str(g(tx, 't_date'))
        if t_date not in history: history[t_date] = []
        mat_dats = g(tx, 'mat_dats') or []
        fee = sum(force_float(g(m, 'fee')) for m in mat_dats)
        tax = sum(force_float(g(m, 'tax')) for m in mat_dats)
        entry = {
            "stk_no": g(tx, 'stk_no'), "stk_na": g(tx, 'stk_na'), "side": g(tx, 'buy_sell'),
            "amount": force_float(g(tx, 'price_qty')), "fee": fee, "tax": tax, "profit": force_float(g(tx, 'make'))
        }
        if not any(h['stk_no'] == entry['stk_no'] and h['amount'] == entry['amount'] and h['side'] == entry['side'] for h in history[t_date]):
            history[t_date].append(entry)

    # 計算在場成本 (舊到新)
    sorted_dates = sorted([k for k in history.keys() if k != 'Unknown'])
    rc = 0
    for d in sorted_dates:
        for e in history[d]:
            if e['side'] == 'B': rc += (e['amount'] + e['fee'])
            else: rc -= (e['amount'] - e.get('fee',0) - e.get('tax',0) - e['profit'])
        history[d][-1]["invested_capital_snapshot"] = max(0, rc)

    # 排序 (新到舊)
    final = OrderedDict()
    for d in sorted(sorted_dates, reverse=True): final[d] = history[d]
    if 'Unknown' in history: final['Unknown'] = history['Unknown']
    with open(JSON_PATH, 'w', encoding='utf-8') as f: json.dump(final, f, ensure_ascii=False, indent=2)

def calculate_report(history, inv_map, target_end_date):
    """根據截止日期彙整報表數據"""
    all_tx = []
    for d_str, tasks in history.items():
        dt = parse_date(d_str)
        if dt and dt <= target_end_date:
            for t in tasks:
                t['dt'] = dt
                all_tx.append(t)
    
    if not all_tx: return None, 0, 0, 0

    df = pd.DataFrame(all_tx).sort_values('dt')
    peak_cap = 0
    running_max = 0
    for d_str, tasks in history.items():
        dt = parse_date(d_str)
        if dt and dt <= target_end_date:
            cap = tasks[-1].get('invested_capital_snapshot', 0)
            if cap > peak_cap: peak_cap = cap

    report_rows = []
    for s_no, gp in df.groupby('stk_no'):
        inv = inv_map.get(s_no, {"尚餘股數": 0, "均價": 0, "SDK現價": 0})
        # 抓取截止日的本地收盤價
        p_date = target_end_date if target_end_date < datetime.now() else datetime.now()
        local_p = get_local_price(s_no, p_date)
        final_p = local_p if local_p is not None else inv["SDK現價"]
        
        cash_p = gp['profit'].sum()
        # 修正：根據歷史價格手動計算未實現盈虧
        unrealized = (final_p - inv["均價"]) * inv["尚餘股數"] if inv["尚餘股數"] > 0 else 0
        
        report_rows.append({
            "編號": s_no, "公司": gp['stk_na'].iloc[-1],
            "購買金額": gp[gp['side']=='B']['amount'].sum(),
            "賣出金額": gp[gp['side']=='S']['amount'].sum(),
            "現金盈虧": cash_p, "尚餘股數": inv["尚餘股數"], "均價": inv["均價"],
            "現價": final_p, "總盈虧": cash_p + unrealized
        })
    return report_rows, peak_cap, sum(r['現金盈虧'] for r in report_rows), sum(r['總盈虧'] for r in report_rows)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', type=int, nargs='?', default=0)
    args = parser.parse_args()

    # 1. 決定區間
    today = datetime.now()
    report_end = datetime(2099, 12, 31)
    prev_month_end = None
    
    if 1 <= args.mode <= 12:
        report_end = datetime(today.year, args.mode, calendar.monthrange(today.year, args.mode)[1])
        # 計算上個月底
        pm = args.mode - 1
        py = today.year
        if pm == 0: pm = 12; py -= 1
        prev_month_end = datetime(py, pm, calendar.monthrange(py, pm)[1])

    try:
        if not os.path.exists(DOC_DIR): os.makedirs(DOC_DIR)
        
        # 2. SDK 同步
        inv_map = {}
        try:
            sdk = login_sdk()
            inv_raw = sdk.get_inventories()
            with open(INV_CACHE, 'wb') as f: pickle.dump(inv_raw, f)
            if args.mode != 0:
                s_sync = (report_end - timedelta(days=365)).strftime("%Y-%m-%d") if args.mode == -1 else f"{today.year}-{args.mode:02d}-01"
                res = sdk.get_transactions_by_date(s_sync, min(report_end, today).strftime("%Y-%m-%d"))
                if res: update_json_history(res)
            else: update_json_history([])
        except:
            if os.path.exists(JSON_PATH): update_json_history([])

        # 3. 載入庫存與 JSON
        if os.path.exists(INV_CACHE):
            with open(INV_CACHE, 'rb') as f:
                ir = pickle.load(f)
                for item in ir:
                    s_no = g(item, 'stk_no')
                    q = force_float(g(item, 'cost_qty'))
                    c_sum = abs(force_float(g(item, 'cost_sum')))
                    inv_map[s_no] = {"尚餘股數": q, "均價": c_sum / q if q > 0 else 0, "SDK現價": force_float(g(item, 'price_mkt'))}

        with open(JSON_PATH, 'r', encoding='utf-8') as f: history = json.load(f)

        # 4. 產生目前與上月報表
        rows, peak, cash_p, total_p = calculate_report(history, inv_map, report_end)
        if rows is None: return

        # 5. 輸出
        headers = ["編號", "公司", "購買金額", "賣出金額", "現金盈虧", "尚餘股數", "均價", "現價", "總盈虧"]
        widths = [8, 14, 12, 12, 12, 10, 10, 10, 12]
        print("\n" + "="*110 + f"\n  玉山證券 投資績效彙整報表 (至 {report_end.strftime('%Y-%m-%d')})\n" + "="*110)
        print("".join(pad_to_width(h, w) for h, w in zip(headers, widths)))
        print("-" * 110)
        for r in rows:
            line = pad_to_width(r["編號"], widths[0]) + pad_to_width(r["公司"], widths[1])
            line += pad_to_width(f"{r['購買金額']:,.0f}", widths[2]) + pad_to_width(f"{r['賣出金額']:,.0f}", widths[3])
            line += pad_to_width(f"{r['現金盈虧']:,.0f}", widths[4]) + pad_to_width(f"{r['尚餘股數']:,.0f}", widths[5])
            line += pad_to_width(f"{r['均價']:.2f}", widths[6]) + pad_to_width(f"{r['現價']:.2f}", widths[7])
            line += pad_to_width(f"{r['總盈虧']:,.0f}", widths[8])
            print(line)
        print("-" * 110)
        print(pad_to_width("總計", widths[0]) + pad_to_width("", widths[1]) + pad_to_width(f"{sum(r['購買金額'] for r in rows):,.0f}", widths[2]) + pad_to_width(f"{sum(r['賣出金額'] for r in rows):,.0f}", widths[3]) + pad_to_width(f"{cash_p:,.0f}", widths[4]) + pad_to_width("", widths[5]) + pad_to_width("", widths[6]) + pad_to_width("", widths[7]) + pad_to_width(f"{total_p:,.0f}", widths[8]))
        print("=" * 110)

        # 盈虧差額計算
        diff_str = ""
        if prev_month_end:
            _, _, _, prev_total = calculate_report(history, inv_map, prev_month_end)
            diff = total_p - prev_total
            diff_pct = (diff / peak * 100) if peak > 0 else 0
            diff_str = f"*與上月總盈虧差額: {diff:,.0f} 元 ({diff_pct:.2f}%)"

        cash_pct = (cash_p / peak * 100) if peak > 0 else 0
        final_pct = (total_p / peak * 100) if peak > 0 else 0
        print(f"該時段投入金額 (最高成本): {peak:,.0f} 元")
        print(f"累計現金盈虧 (已實現): {cash_p:,.0f} 元 ({cash_pct:.2f}%)")
        print(f"最終預估盈虧 (含持股): {total_p:,.0f} 元 ({final_pct:.2f}%)")
        if diff_str: print(diff_str)
        print("-" * 110 + "\n")

    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
