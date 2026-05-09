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

# [全域報表範圍參數] - 預設顯示範圍
DEFAULT_START = "2000-01-01"
DEFAULT_END = "2099-12-31"

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
        if not any(h['stk_no'] == entry['stk_no'] and h['amount'] == entry['amount'] and h['side'] == entry['side'] for h in history[t_date]):
            history[t_date].append(entry)

    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', type=int, nargs='?', default=0, help='模式 (0:不抓, -1:同步一年, 1-12:同步該月)')
    args = parser.parse_args()

    print(f"\n[模式] 0:離線 | -1:同步一年 | 1-12:同步該月。目前模式: {args.mode}")
    
    # 報表過濾範圍
    report_start = DEFAULT_START
    report_end = DEFAULT_END
    if 1 <= args.mode <= 12:
        y = datetime.now().year
        ld = calendar.monthrange(y, args.mode)[1]
        report_start = f"{y}-{args.mode:02d}-01"
        report_end = f"{y}-{args.mode:02d}-{ld:02d}"
    
    try:
        if not os.path.exists(DOC_DIR): os.makedirs(DOC_DIR)
        inv_map = {}
        
        # 1. SDK 同步與庫存抓取
        try:
            sdk = login_sdk()
            # 抓即時庫存並快取
            inv_raw = sdk.get_inventories()
            with open(INV_CACHE, 'wb') as f: pickle.dump(inv_raw, f)
            
            if args.mode == -1:
                print("[DEBUG] 正在同步年度交易...")
                for i in range(12):
                    e_chunk = datetime.now() - timedelta(days=i*30)
                    s_chunk = e_chunk - timedelta(days=30)
                    try:
                        res = sdk.get_transactions_by_date(s_chunk.strftime("%Y-%m-%d"), e_chunk.strftime("%Y-%m-%d"))
                        if res: update_json_history(res)
                    except: continue
            elif 1 <= args.mode <= 12:
                today_str = datetime.now().strftime("%Y-%m-%d")
                actual_end = min(report_end, today_str)
                print(f"[DEBUG] 正在同步 {report_start} ~ {actual_end}...")
                res = sdk.get_transactions_by_date(report_start, actual_end)
                if res: update_json_history(res)
        except Exception as e:
            if args.mode != 0: print(f"[DEBUG] SDK 同步失敗: {e}")

        # 2. 載入庫存數據 (快取)
        if os.path.exists(INV_CACHE):
            with open(INV_CACHE, 'rb') as f:
                ir = pickle.load(f)
                for item in ir:
                    s_no = g(item, 'stk_no')
                    q = force_float(g(item, 'cost_qty'))
                    c_sum = abs(force_float(g(item, 'cost_sum')))
                    inv_map[s_no] = {
                        "尚餘股數": q, "均價": c_sum / q if q > 0 else 0, "總成本": c_sum,
                        "現價": force_float(g(item, 'price_mkt')), "未實現": force_float(g(item, 'make_a_sum'))
                    }

        # 3. 讀取 JSON 並處理
        if not os.path.exists(JSON_PATH):
            print("⚠️ 找不到 transactions.json，請先使用參數 -1 同步資料")
            return
        with open(JSON_PATH, 'r', encoding='utf-8') as f: history = json.load(f)

        all_tx_flat = []
        for d, tasks in history.items():
            cd = d.replace('/', '-').replace('.', '-')
            for t in tasks:
                t['clean_date'] = cd
                all_tx_flat.append(t)
        
        df_h = pd.DataFrame(all_tx_flat)
        if df_h.empty:
            print("⚠️ 資料庫為空")
            return

        # 彙整報表資料
        # A. 該時間段內的交易 (決定表格內容)
        period_df = df_h[(df_h['clean_date'] >= report_start) & (df_h['clean_date'] <= report_end)]
        # B. 截至該時間段結束時的累計 (決定括號內的數值)
        cumulative_df = df_h[df_h['clean_date'] <= report_end]

        report_rows = []
        if not period_df.empty:
            for s_no, gp in period_df.groupby('stk_no'):
                inv = inv_map.get(s_no, {"尚餘股數": 0, "均價": 0, "現價": 0, "未實現": 0, "總成本": 0})
                report_rows.append({
                    "編號": s_no, "公司": gp['stk_na'].iloc[-1],
                    "購買金額": gp[gp['side']=='B']['amount'].sum(),
                    "賣出金額": gp[gp['side']=='S']['amount'].sum(),
                    "現金盈虧": gp['profit'].sum(),
                    "尚餘股數": inv["尚餘股數"], "均價": inv["均價"], "現價": inv["現價"],
                    "總盈虧": gp['profit'].sum() + inv["未實現"]
                })

        # --- 表格渲染 ---
        headers = ["編號", "公司", "購買金額", "賣出金額", "現金盈虧", "尚餘股數", "均價", "現價", "總盈虧"]
        widths = [8, 14, 12, 12, 12, 10, 10, 10, 12]
        print("\n" + "="*110 + f"\n  玉山證券 投資績效彙整報表 ({report_start} ~ {report_end})\n" + "="*110)
        print("".join(pad_to_width(h, w) for h, w in zip(headers, widths)))
        print("-" * 110)
        
        for r in report_rows:
            line = pad_to_width(r["編號"], widths[0]) + pad_to_width(r["公司"], widths[1])
            line += pad_to_width(f"{r['購買金額']:,.0f}", widths[2]) + pad_to_width(f"{r['賣出金額']:,.0f}", widths[3])
            line += pad_to_width(f"{r['現金盈虧']:,.0f}", widths[4]) + pad_to_width(f"{r['尚餘股數']:,.0f}", widths[5])
            line += pad_to_width(f"{r['均價']:.2f}", widths[6]) + pad_to_width(f"{r['現價']:.2f}", widths[7])
            line += pad_to_width(f"{r['總盈虧']:,.0f}", widths[8])
            print(line)

        # 總計列
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

        # --- 最終彙整資訊 ---
        # 該時段投入金額 (買入-賣出)
        period_net_invest = s_buy - s_sell
        
        # 累計至該月底的投入金額
        cum_buy = cumulative_df[cumulative_df['side']=='B']['amount'].sum()
        cum_sell = cumulative_df[cumulative_df['side']=='S']['amount'].sum()
        cum_invest = cum_buy - cum_sell
        
        # 盈虧比例計算 (以該時段/累計買入總額為分母較準確)
        cash_pct = (s_cash / s_buy * 100) if s_buy > 0 else 0
        total_p_base = sum(force_float(inv.get('總成本')) for inv in inv_map.values()) + cum_buy
        final_pct = (s_total / s_buy * 100) if s_buy > 0 else 0
        
        # 修正後的顯示格式
        print(f"該時段投入金額: {period_net_invest:,.0f} 元 ({cum_invest:,.0f})")
        print(f"累計現金盈虧 (已實現): {s_cash:,.0f} 元 ({cash_pct:.2f}%)")
        print(f"最終預估盈虧 (含持股): {s_total:,.0f} 元 ({final_pct:.2f}%)")
        print("-" * 110 + "\n")

    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
