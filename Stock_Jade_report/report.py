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

# ANSI 顏色
YELLOW = "\033[93m"
RESET = "\033[0m"

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
        entry = {"stk_no": g(tx, 'stk_no'), "stk_na": g(tx, 'stk_na'), "side": g(tx, 'buy_sell'), "amount": force_float(g(tx, 'price_qty')), "fee": fee, "tax": tax, "profit": force_float(g(tx, 'make'))}
        if not any(h['stk_no'] == entry['stk_no'] and h['amount'] == entry['amount'] and h['side'] == entry['side'] for h in history[t_date]):
            history[t_date].append(entry)
    sorted_dates = sorted([k for k in history.keys() if k != 'Unknown'])
    rc = 0
    for d in sorted_dates:
        for e in history[d]:
            if e['side'] == 'B': rc += (e['amount'] + e['fee'])
            else: rc -= (e['amount'] - e.get('fee',0) - e.get('tax',0) - e['profit'])
        history[d][-1]["invested_capital_snapshot"] = max(0, rc)
    final = OrderedDict()
    for d in sorted(sorted_dates, reverse=True): final[d] = history[d]
    if 'Unknown' in history: final['Unknown'] = history['Unknown']
    with open(JSON_PATH, 'w', encoding='utf-8') as f: json.dump(final, f, ensure_ascii=False, indent=2)

def get_stats_for_date(history, inv_map, target_end_date):
    all_tx = []
    peak_cap = 0
    for d_str, tasks in history.items():
        dt = parse_date(d_str)
        if dt and dt <= target_end_date:
            all_tx.extend(tasks)
            cap = tasks[-1].get('invested_capital_snapshot', 0)
            if cap > peak_cap: peak_cap = cap
    if not all_tx: return None, 0, 0
    
    total_cash_p = 0
    total_unrealized = 0
    df = pd.DataFrame(all_tx)
    for s_no, gp in df.groupby('stk_no'):
        inv = inv_map.get(s_no, {"尚餘股數": 0, "均價": 0, "SDK現價": 0})
        p_date = target_end_date if target_end_date < datetime.now() else datetime.now()
        local_p = get_local_price(s_no, p_date)
        fp = local_p if local_p is not None else inv["SDK現價"]
        cash_p = gp['profit'].sum()
        unrealized = (fp - inv["均價"]) * inv["尚餘股數"] if inv["尚餘股數"] > 0 else 0
        total_cash_p += cash_p
        total_unrealized += unrealized
    return df, total_cash_p + total_unrealized, peak_cap

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', type=int, nargs='?', default=0)
    args = parser.parse_args()

    today = datetime.now()
    try:
        if not os.path.exists(DOC_DIR): os.makedirs(DOC_DIR)
        
        # 1. SDK 同步
        if args.mode != 0:
            try:
                sdk = login_sdk()
                inv_raw = sdk.get_inventories()
                with open(INV_CACHE, 'wb') as f: 
                    pickle.dump(inv_raw, f)
                
                s_sync = (today - timedelta(days=365)).strftime("%Y-%m-%d") if args.mode == -1 else f"{today.year}-{args.mode:02d}-01"
                res = sdk.get_transactions_by_date(s_sync, today.strftime("%Y-%m-%d"))
                if res: update_json_history(res)
            except Exception: pass
        else:
            if os.path.exists(JSON_PATH): update_json_history([])

        # 2. 數據載入
        inv_map = {}
        if os.path.exists(INV_CACHE):
            with open(INV_CACHE, 'rb') as f:
                for item in pickle.load(f):
                    s_no = g(item, 'stk_no')
                    q = force_float(g(item, 'cost_qty'))
                    c_sum = abs(force_float(g(item, 'cost_sum')))
                    inv_map[s_no] = {"尚餘股數": q, "均價": c_sum / q if q > 0 else 0, "SDK現價": force_float(g(item, 'price_mkt'))}

        if not os.path.exists(JSON_PATH): return
        with open(JSON_PATH, 'r', encoding='utf-8') as f: history = json.load(f)

        # --- 3. 月份變動表 ---
        target_month = args.mode if 1 <= args.mode <= 12 else today.month
        months_to_show = list(range(2, target_month + 1))
        
        monthly_report = []
        prev_total_pl = 0
        for m in range(1, target_month + 1):
            m_end = datetime(today.year, m, calendar.monthrange(today.year, m)[1])
            _, total_pl, peak = get_stats_for_date(history, inv_map, m_end)
            diff = total_pl - prev_total_pl
            diff_pct = (diff / peak * 100) if peak > 0 else 0
            if m in months_to_show:
                m_label = f"{today.year}-{m:02d}"
                if m == target_month: m_label = f"*{m_label}"
                monthly_report.append({"月份": m_label, "總投入": peak, "差額": diff, "比例": diff_pct})
            prev_total_pl = total_pl

        print("\n" + "="*50 + "\n  各月份投資績效變動表\n" + "="*50)
        m_headers = ["月份", "總盈虧差額", "總投入金額", "比例 (%)"]
        m_widths = [9, 12, 12, 10]
        print("".join(pad_to_width(h, w) for h, w in zip(m_headers, m_widths)))
        print("-" * 50)
        for r in monthly_report:
            line = pad_to_width(r["月份"], m_widths[0])
            line += pad_to_width(f"{r['差額']:,.0f}", m_widths[1])
            line += pad_to_width(f"{r['總投入']:,.0f}", m_widths[2])
            line += pad_to_width(f"{r['比例']:.2f}%", m_widths[3])
            if '*' in r["月份"]: print(f"{YELLOW}{line}{RESET}")
            else: print(line)
        print("-" * 50)

        # --- 4. 詳細對帳表 ---
        rep_end = datetime(today.year, target_month, calendar.monthrange(today.year, target_month)[1])
        df_p, current_total_pl, current_peak = get_stats_for_date(history, inv_map, rep_end)
        if df_p is not None:
            rows = []
            for s_no, gp in df_p.groupby('stk_no'):
                inv = inv_map.get(s_no, {"尚餘股數": 0, "均價": 0, "SDK現價": 0})
                lp = get_local_price(s_no, rep_end if rep_end < today else today); fp = lp if lp is not None else inv["SDK現價"]
                cash_p = gp['profit'].sum(); unrealized = (fp - inv["均價"]) * inv["尚餘股數"] if inv["尚餘股數"] > 0 else 0
                rows.append({"編號": s_no, "公司": gp['stk_na'].iloc[-1], "購買金額": gp[gp['side']=='B']['amount'].sum(), "賣出金額": gp[gp['side']=='S']['amount'].sum(), "現金盈虧": cash_p, "尚餘股數": inv["尚餘股數"], "均價": inv["均價"], "現價": fp, "總盈虧": cash_p + unrealized})
            
            print("\n" + "="*110 + f"\n  投資績效明細表 (2020-01-01 ~ {rep_end.strftime('%Y-%m-%d')})\n" + "="*110)
            h_cols = ["編號", "公司", "購買金額", "賣出金額", "現金盈虧", "尚餘股數", "均價", "現價", "總盈虧"]
            h_wids = [8, 14, 12, 12, 12, 10, 10, 10, 12]
            print("".join(pad_to_width(h, w) for h, w in zip(h_cols, h_wids)))
            print("-" * 110)
            for r in rows:
                print("".join(pad_to_width(r[k] if isinstance(r[k], str) else f"{r[k]:,.0f}" if '金額' in k or '盈虧' in k else f"{r[k]:.2f}" if '價' in k else f"{r[k]}", w) for k, w in zip(h_cols, h_wids)))
            print("-" * 110)
            s_cash = sum(r['現金盈虧'] for r in rows)
            print(f"該時段投入金額 (最高成本): {current_peak:,.0f} 元")
            print(f"累計現金盈虧 (已實現): {s_cash:,.0f} 元 ({(s_cash/current_peak*100):.2f}%)")
            print(f"最終預估盈虧 (含持股): {current_total_pl:,.0f} 元 ({(current_total_pl/current_peak*100):.2f}%)")
            print("-" * 110 + "\n")

    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
