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

def parse_date(d_str):
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try: return datetime.strptime(d_str, fmt)
        except: continue
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

    print(f"\n[模式] 0:離線 | -1:同步一年 | 1-12:同步該月資料。目前輸入: {args.mode}")
    
    report_start = datetime(2000, 1, 1)
    report_end = datetime(2099, 12, 31)
    is_monthly = False
    
    if 1 <= args.mode <= 12:
        is_monthly = True
        y = datetime.now().year
        ld = calendar.monthrange(y, args.mode)[1]
        report_start = datetime(y, args.mode, 1)
        report_end = datetime(y, args.mode, ld)

    try:
        if not os.path.exists(DOC_DIR): os.makedirs(DOC_DIR)
        
        inv_map = {}
        # 1. SDK 同步
        try:
            sdk = login_sdk()
            inv_raw = sdk.get_inventories()
            with open(INV_CACHE, 'wb') as f: pickle.dump(inv_raw, f)
            
            if args.mode == -1:
                for i in range(12):
                    s = (datetime.now() - timedelta(days=(i+1)*30)).strftime("%Y-%m-%d")
                    e = (datetime.now() - timedelta(days=i*30)).strftime("%Y-%m-%d")
                    try:
                        res = sdk.get_transactions_by_date(s, e)
                        if res: update_json_history(res)
                    except: continue
            elif is_monthly:
                s_str = report_start.strftime("%Y-%m-%d")
                e_str = min(report_end, datetime.now()).strftime("%Y-%m-%d")
                res = sdk.get_transactions_by_date(s_str, e_str)
                if res: update_json_history(res)
        except: pass

        # 2. 庫存與歷史價格模擬
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

        # 3. 數據讀取與計算
        if not os.path.exists(JSON_PATH): return
        with open(JSON_PATH, 'r', encoding='utf-8') as f: history = json.load(f)

        # 展平歷史數據並標註日期
        all_tx_list = []
        for d_str, tasks in history.items():
            dt = parse_date(d_str)
            if not dt: continue
            for t in tasks:
                t['dt'] = dt
                all_tx_list.append(t)
        
        df_all = pd.DataFrame(all_tx_list).sort_values('dt')
        
        # 過濾時段
        period_df = df_all[(df_all['dt'] >= report_start) & (df_all['dt'] <= report_end)]
        cum_before_df = df_all[df_all['dt'] <= report_end]

        if period_df.empty and is_monthly:
            print(f"⚠️ {report_start.strftime('%Y-%m')} 期間無交易紀錄")
            return

        # 計算 Peak Capital (最高投入金額)
        # 我們需要追蹤累積的 (Buy - Sell)
        df_all['net_flow'] = df_all.apply(lambda x: x['amount'] if x['side']=='B' else -x['amount'], axis=1)
        df_all['cum_flow'] = df_all['net_flow'].cumsum()
        
        # 該時段內的最高累積投入
        period_flows = df_all[(df_all['dt'] >= report_start) & (df_all['dt'] <= report_end)]
        peak_capital_period = period_flows['cum_flow'].max() if not period_flows.empty else 0
        peak_capital_cum = cum_before_df.apply(lambda x: x['amount'] if x['side']=='B' else -x['amount'], axis=1).cumsum().max() if not cum_before_df.empty else 0

        report_rows = []
        for s_no, gp in period_df.groupby('stk_no'):
            inv = inv_map.get(s_no, {"尚餘股數": 0, "均價": 0, "現價": 0, "未實現": 0, "總成本": 0})
            
            # 如果是歷史月份，嘗試從該月最後一筆成交抓取「現價」參考值
            display_price = inv["現價"]
            if is_monthly and report_end < datetime.now().replace(hour=0, minute=0, second=0):
                # 抓取該月最後一筆成交價作為參考 (或者用 inventory，但 user 說不要最新的)
                # 由於無法輕易取得歷史收盤，我們暫時標註
                pass

            report_rows.append({
                "編號": s_no, "公司": gp['stk_na'].iloc[-1],
                "購買金額": gp[gp['side']=='B']['amount'].sum(),
                "賣出金額": gp[gp['side']=='S']['amount'].sum(),
                "現金盈虧": gp['profit'].sum(),
                "尚餘股數": inv["尚餘股數"], "均價": inv["均價"], "現價": display_price,
                "總盈虧": gp['profit'].sum() + inv["未實現"]
            })

        # 全時段模式才顯示庫存
        if not is_monthly:
            for s_no, inv in inv_map.items():
                if not any(r['編號'] == s_no for r in report_rows):
                    report_rows.append({
                        "編號": s_no, "公司": "(庫存)", "購買金額": 0, "賣出金額": 0, "現金盈虧": 0,
                        "尚餘股數": inv["尚餘股數"], "均價": inv["均價"], "現價": inv["現價"], "總盈虧": inv["未實現"]
                    })

        # --- 渲染 ---
        headers = ["編號", "公司", "購買金額", "賣出金額", "現金盈虧", "尚餘股數", "均價", "現價", "總盈虧"]
        widths = [8, 14, 12, 12, 12, 10, 10, 10, 12]
        print("\n" + "="*110 + f"\n  投資績效報表 ({report_start.strftime('%Y-%m-%d')} ~ {report_end.strftime('%Y-%m-%d')})\n" + "="*110)
        print("".join(pad_to_width(h, w) for h, w in zip(headers, widths)))
        print("-" * 110)
        for r in report_rows:
            line = pad_to_width(r["編號"], widths[0]) + pad_to_width(r["公司"], widths[1])
            line += pad_to_width(f"{r['購買金額']:,.0f}", widths[2]) + pad_to_width(f"{r['賣出金額']:,.0f}", widths[3])
            line += pad_to_width(f"{r['現金盈虧']:,.0f}", widths[4]) + pad_to_width(f"{r['尚餘股數']:,.0f}", widths[5])
            line += pad_to_width(f"{r['均價']:.2f}", widths[6]) + pad_to_width(f"{r['現價']:.2f}", widths[7])
            line += pad_to_width(f"{r['總盈虧']:,.0f}", widths[8])
            print(line)

        s_buy = sum(r["購買金額"] for r in report_rows)
        s_cash = sum(r["現金盈虧"] for r in report_rows)
        s_total = sum(r["總盈虧"] for r in report_rows)
        print("-" * 110)
        print(pad_to_width("總計", widths[0]) + pad_to_width("", widths[1]) + pad_to_width(f"{s_buy:,.0f}", widths[2]) + pad_to_width(f"{sum(r['賣出金額'] for r in report_rows):,.0f}", widths[3]) + pad_to_width(f"{s_cash:,.0f}", widths[4]) + pad_to_width("", widths[5]) + pad_to_width("", widths[6]) + pad_to_width("", widths[7]) + pad_to_width(f"{s_total:,.0f}", widths[8]))
        print("=" * 110)

        # 績效總結
        # 分母採用該時段或累計的「最高投入金額」以符合 user 的投資概念
        cash_pct = (s_cash / peak_capital_period * 100) if peak_capital_period > 0 else 0
        final_pct = (s_total / peak_capital_period * 100) if peak_capital_period > 0 else 0
        
        # 如果是全時段，使用累計最高投入
        if not is_monthly:
            cash_pct = (s_cash / peak_capital_cum * 100) if peak_capital_cum > 0 else 0
            final_pct = (s_total / peak_capital_cum * 100) if peak_capital_cum > 0 else 0

        print(f"該時段投入金額 (最高): {peak_capital_period:,.0f} 元 ({peak_capital_cum:,.0f})")
        print(f"累計現金盈虧 (已實現): {s_cash:,.0f} 元 ({cash_pct:.2f}%)")
        print(f"最終預估盈虧 (含持股): {s_total:,.0f} 元 ({final_pct:.2f}%)")
        if is_monthly: print(f"註：現價與未實現損益仍採最新庫存數據，歷史收盤價需額外訂閱行情 API。")
        print("-" * 110 + "\n")

    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
