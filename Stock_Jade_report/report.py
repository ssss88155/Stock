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
    """從本地資料夾抓取該個股在特定日期的收盤價"""
    stk_no = str(stk_no).lower()
    path = os.path.join(LOCAL_DATA_DIR, f"{stk_no}.json")
    if not os.path.exists(path):
        print(f"  [DEBUG] 找不到本地資料: {path}")
        return None
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 取得個股層級
        stk_data = data.get(stk_no.upper()) or data.get(stk_no)
        if not stk_data: return None
        
        prices = stk_data.get('price', {})
        if not prices: return None
        
        # 尋找目標日期或最接近的過去日期
        target_str = target_date_obj.strftime("%Y-%m-%d")
        if target_str in prices:
            return force_float(prices[target_str].get('close'))
        
        # 找最後一個小於目標日期的交易日
        available_dates = sorted([d for d in prices.keys() if d <= target_str], reverse=True)
        if available_dates:
            return force_float(prices[available_dates[0]].get('close'))
            
    except Exception as e:
        print(f"  [DEBUG] 讀取本地價格失敗 ({stk_no}): {e}")
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

    filter_start = datetime(2000, 1, 1)
    filter_end = datetime(2099, 12, 31)
    is_monthly = False
    
    if 1 <= args.mode <= 12:
        is_monthly = True
        y = datetime.now().year
        ld = calendar.monthrange(y, args.mode)[1]
        filter_start = datetime(y, args.mode, 1)
        filter_end = datetime(y, args.mode, ld)

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
                s_str = filter_start.strftime("%Y-%m-%d")
                e_str = min(filter_end, datetime.now()).strftime("%Y-%m-%d")
                res = sdk.get_transactions_by_date(s_str, e_str)
                if res: update_json_history(res)
        except: pass

        # 2. 庫存備份載入
        if os.path.exists(INV_CACHE):
            with open(INV_CACHE, 'rb') as f:
                ir = pickle.load(f)
                for item in ir:
                    s_no = g(item, 'stk_no')
                    q = force_float(g(item, 'cost_qty'))
                    c_sum = abs(force_float(g(item, 'cost_sum')))
                    inv_map[s_no] = {
                        "尚餘股數": q, "均價": c_sum / q if q > 0 else 0, "總成本": c_sum,
                        "SDK現價": force_float(g(item, 'price_mkt')), "未實現": force_float(g(item, 'make_a_sum'))
                    }

        # 3. 數據計算
        if not os.path.exists(JSON_PATH): return
        with open(JSON_PATH, 'r', encoding='utf-8') as f: history = json.load(f)

        all_tx_flat = []
        for d_str, tasks in history.items():
            dt = parse_date(d_str)
            if not dt: continue
            for t in tasks:
                t['dt'] = dt
                all_tx_flat.append(t)
        
        df_all = pd.DataFrame(all_tx_flat).sort_values('dt')
        
        # 過濾日期
        period_df = df_all[(df_all['dt'] >= filter_start) & (df_all['dt'] <= filter_end)]
        cum_before_df = df_all[df_all['dt'] <= filter_end]

        if period_df.empty and is_monthly:
            print(f"⚠️ {filter_start.strftime('%Y-%m')} 期間無交易紀錄")
            return

        # --- 計算 Peak Capital (最高投入金額) ---
        def calc_peak_capital(df):
            if df.empty: return 0
            df = df.sort_values('dt')
            # 建立每日彙整金額
            df['net_flow'] = df.apply(lambda x: x['amount'] if x['side']=='B' else -x['amount'], axis=1)
            daily_sum = df.groupby('dt')['net_flow'].sum().cumsum()
            return daily_sum.max()

        peak_capital_period = calc_peak_capital(period_df)
        peak_capital_cum = calc_peak_capital(cum_before_df)

        # 彙整每列數據
        report_rows = []
        for s_no, gp in period_df.groupby('stk_no'):
            inv = inv_map.get(s_no, {"尚餘股數": 0, "均價": 0, "SDK現價": 0, "未實現": 0, "總成本": 0})
            
            # --- 從本地資料抓取「當時現價」 ---
            # 若模式為單月，抓該月最後一天的價格；否則抓最新的價格
            price_date = filter_end if is_monthly else datetime.now()
            local_price = get_local_price(s_no, price_date)
            
            final_price = local_price if local_price is not None else inv["SDK現價"]
            
            # 計算該時段盈虧
            cash_p = gp['profit'].sum()
            
            report_rows.append({
                "編號": s_no, "公司": gp['stk_na'].iloc[-1],
                "購買金額": gp[gp['side']=='B']['amount'].sum(),
                "賣出金額": gp[gp['side']=='S']['amount'].sum(),
                "現金盈虧": cash_p, "尚餘股數": inv["尚餘股數"], "均價": inv["均價"],
                "現價": final_price, "總盈虧": cash_p + inv["未實現"] # 總盈虧暫採 SDK 未實現加總
            })

        # 非單月模式顯示所有庫存
        if not is_monthly:
            for s_no, inv in inv_map.items():
                if not any(r['編號'] == s_no for r in report_rows):
                    report_rows.append({
                        "編號": s_no, "公司": "(庫存)", "購買金額": 0, "賣出金額": 0, "現金盈虧": 0,
                        "尚餘股數": inv["尚餘股數"], "均價": inv["均價"], "現價": inv["SDK現價"],
                        "總盈虧": inv["未實現"]
                    })

        # --- 輸出表格 ---
        headers = ["編號", "公司", "購買金額", "賣出金額", "現金盈虧", "尚餘股數", "均價", "現價", "總盈虧"]
        widths = [8, 14, 12, 12, 12, 10, 10, 10, 12]
        print("\n" + "="*110 + f"\n  玉山證券 投資績效彙整報表 ({filter_start.strftime('%Y-%m-%d')} ~ {filter_end.strftime('%Y-%m-%d')})\n" + "="*110)
        print("".join(pad_to_width(h, w) for h, w in zip(headers, widths)))
        print("-" * 110)
        for r in report_rows:
            line = pad_to_width(r["編號"], widths[0]) + pad_to_width(r["公司"], widths[1])
            line += pad_to_width(f"{r['購買金額']:,.0f}", widths[2]) + pad_to_width(f"{r['賣出金額']:,.0f}", widths[3])
            line += pad_to_width(f"{r['現金盈虧']:,.0f}", widths[4]) + pad_to_width(f"{r['尚餘股數']:,.0f}", widths[5])
            line += pad_to_width(f"{r['均價']:.2f}", widths[6]) + pad_to_width(f"{r['現價']:.2f}", widths[7])
            line += pad_to_width(f"{r['總盈虧']:,.0f}", widths[8])
            print(line)

        # 總結
        print("-" * 110)
        s_buy = sum(r["購買金額"] for r in report_rows)
        s_cash = sum(r["現金盈虧"] for r in report_rows)
        s_total = sum(r["總盈虧"] for r in report_rows)
        print(pad_to_width("總計", widths[0]) + pad_to_width("", widths[1]) + pad_to_width(f"{s_buy:,.0f}", widths[2]) + pad_to_width(f"{sum(r['賣出金額'] for r in report_rows):,.0f}", widths[3]) + pad_to_width(f"{s_cash:,.0f}", widths[4]) + pad_to_width("", widths[5]) + pad_to_width("", widths[6]) + pad_to_width("", widths[7]) + pad_to_width(f"{s_total:,.0f}", widths[8]))
        print("=" * 110)

        # 比例計算
        cash_pct = (s_cash / peak_capital_period * 100) if peak_capital_period > 0 else 0
        final_pct = (s_total / peak_capital_period * 100) if peak_capital_period > 0 else 0
        if not is_monthly:
            cash_pct = (s_cash / peak_capital_cum * 100) if peak_capital_cum > 0 else 0
            final_pct = (s_total / peak_capital_cum * 100) if peak_capital_cum > 0 else 0

        print(f"該時段投入金額 (最高): {peak_capital_period:,.0f} 元 ({peak_capital_cum:,.0f})")
        print(f"累計現金盈虧 (已實現): {s_cash:,.0f} 元 ({cash_pct:.2f}%)")
        print(f"最終預估盈虧 (含持股): {s_total:,.0f} 元 ({final_pct:.2f}%)")
        print("-" * 110 + "\n")

    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
