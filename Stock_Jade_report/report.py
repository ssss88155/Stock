import os
import pandas as pd
import json
import keyring
import argparse
import calendar
import pickle
import sys
from datetime import datetime, timedelta
from collections import OrderedDict
from configparser import ConfigParser
from esun_trade.sdk import SDK
from esun_marketdata.util import TRADE_SDK_ACCOUNT_KEY, TRADE_SDK_CERT_KEY, setup_keyring

# 將 lib 目錄加入 Python 路徑
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
from common_lib import Color, pad_string, get_display_width

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
    help_text = (
        "玉山證券投資績效報告工具\n"
        "參數用途說明：\n"
        "  [0]    : (預設) 讀取本地快取資料，不連接 SDK (省時)\n"
        "  [-1]   : 【唯一連線模式】連接 SDK 更新最新庫存與成交紀錄\n"
        "  [1-12] : 分析指定月份 (不自動更新資料，若需更新請用 -1)\n"
    )
    
    parser = argparse.ArgumentParser(description='玉山證券投資績效報告工具', formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('mode', type=int, nargs='?', default=0, help='執行模式')
    args = parser.parse_args()

    # 執行時立刻印出功能說明
    print("-" * 60)
    print(help_text)
    print("-" * 60)

    today = datetime.now()
    try:
        if not os.path.exists(DOC_DIR): os.makedirs(DOC_DIR)
        
        # 嚴格限制：只有 -1 才同步 SDK
        if args.mode == -1:
            try:
                print(f"[INFO] 正在連接玉山 SDK 同步即時資料...")
                sdk = login_sdk()
                
                # 更新庫存
                inv_raw = sdk.get_inventories()
                with open(INV_CACHE, 'wb') as f: 
                    pickle.dump(inv_raw, f)
                
                # 同步成交紀錄 (處理日期限制)
                s_sync = (today - timedelta(days=90)).strftime("%Y-%m-%d")
                e_sync = today.strftime("%Y-%m-%d")
                try:
                    res = sdk.get_transactions_by_date(s_sync, e_sync)
                except ValueError as ve:
                    if "AW00002" in str(ve):
                        print("[INFO] 偵測到 SDK 日期範圍限制，嘗試同步最近 30 天...")
                        s_sync = (today - timedelta(days=30)).strftime("%Y-%m-%d")
                        res = sdk.get_transactions_by_date(s_sync, e_sync)
                    else: raise ve
                    
                if res: 
                    update_json_history(res)
                    print(f"[SUCCESS] 資料更新成功，同步 {len(res)} 筆紀錄。")
                else:
                    print(f"[INFO] SDK 同步完成，區間內無新成交紀錄。")
                    update_json_history([])
            except Exception as e:
                print(f"[ERROR] SDK 同步失敗: {e}，將使用本地快取。")
                if os.path.exists(JSON_PATH): update_json_history([])
        else:
            print(f"[INFO] 執行模式 {args.mode}：不連接 SDK，讀取本地快取。")
            if os.path.exists(JSON_PATH): 
                update_json_history([])

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

        target_month = args.mode if 1 <= args.mode <= 12 else today.month
        
        # 找出分析月份有交易的股票
        this_month_start = datetime(today.year, target_month, 1)
        this_month_end = datetime(today.year, target_month, calendar.monthrange(today.year, target_month)[1])
        traded_this_month = set()
        for d_str, tasks in history.items():
            dt = parse_date(d_str)
            if dt and this_month_start <= dt <= this_month_end:
                for t in tasks: traded_this_month.add(t['stk_no'])

        rep_end = datetime(today.year, target_month, calendar.monthrange(today.year, target_month)[1])
        df_p, current_total_pl, current_peak = get_stats_for_date(history, inv_map, rep_end)

        if df_p is not None:
            rows = []
            for s_no, gp in df_p.groupby('stk_no'):
                inv = inv_map.get(s_no, {"尚餘股數": 0, "均價": 0, "SDK現價": 0})
                lp = get_local_price(s_no, rep_end if rep_end < today else today); fp = lp if lp is not None else inv["SDK現價"]
                cash_p = gp['profit'].sum(); unrealized = (fp - inv["均價"]) * inv["尚餘股數"] if inv["尚餘股數"] > 0 else 0
                rows.append({"編號": s_no, "公司": gp['stk_na'].iloc[-1], "購買金額": gp[gp['side']=='B']['amount'].sum(), "賣出金額": gp[gp['side']=='S']['amount'].sum(), "現金盈虧": cash_p, "尚餘股數": inv["尚餘股數"], "均價": inv["均價"], "現價": fp, "總盈虧": cash_p + unrealized})
            
            rows.sort(key=lambda x: x["尚餘股數"] == 0)
            print("\n" + "="*110 + f"\n  投資績效明細表 (至 {rep_end.strftime('%Y-%m-%d')})\n" + "="*110)
            h_cols = ["編號", "公司", "購買金額", "賣出金額", "現金盈虧", "尚餘股數", "均價", "現價", "總盈虧"]
            h_wids = [8, 14, 12, 12, 12, 10, 10, 10, 12]
            print("".join(pad_string(h, w, 'center') for h, w in zip(h_cols, h_wids)))
            print("-" * 110)
            total_buy = 0
            total_sell = 0
            total_cash_pl = 0
            total_pl = 0
            for r in rows:
                # 只有當 (尚餘股數為 0) 且 (本月完全沒交易) 時才變淡 (Color.DIM)
                is_dim = (r["尚餘股數"] == 0 and r["編號"] not in traded_this_month)
                
                if not is_dim:
                    total_buy += r['購買金額']
                    total_sell += r['賣出金額']
                    total_cash_pl += r['現金盈虧']
                    total_pl += r['總盈虧']

                line_parts = [
                    pad_string(r["編號"], h_wids[0], 'left'),
                    pad_string(r["公司"], h_wids[1], 'left'),
                    pad_string(f"{r['購買金額']:,.0f}", h_wids[2], 'right'),
                    pad_string(f"{r['賣出金額']:,.0f}", h_wids[3], 'right'),
                    pad_string(f"{r['現金盈虧']:,.0f}", h_wids[4], 'right'),
                    pad_string(f"{r['尚餘股數']:,.1f}", h_wids[5], 'right'),
                    pad_string(f"{r['均價']:.2f}", h_wids[6], 'right'),
                    pad_string(f"{r['現價']:.2f}", h_wids[7], 'right'),
                    pad_string(f"{r['總盈虧']:,.0f}", h_wids[8], 'right')
                ]
                
                if is_dim:
                    print(Color.wrap("".join(line_parts), Color.DIM))
                else:
                    # 總盈虧配色：負數綠色，正數紅色
                    if r["總盈虧"] < 0:
                        line_parts[8] = Color.wrap(line_parts[8], Color.GREEN)
                    elif r["總盈虧"] > 0:
                        line_parts[8] = Color.wrap(line_parts[8], Color.RED)
                    print("".join(line_parts))

            print("-" * 110)
            # 總結列 (僅計算非灰色/活躍項目)
            sum_line_parts = [
                pad_string("合計 (活躍)", h_wids[0] + h_wids[1], 'left'),
                pad_string(f"{total_buy:,.0f}", h_wids[2], 'right'),
                pad_string(f"{total_sell:,.0f}", h_wids[3], 'right'),
                pad_string(f"{total_cash_pl:,.0f}", h_wids[4], 'right'),
                pad_string("", h_wids[5] + h_wids[6] + h_wids[7], 'right'),
                pad_string(f"{total_pl:,.0f}", h_wids[8], 'right')
            ]
            if total_pl < 0:
                sum_line_parts[5] = Color.wrap(sum_line_parts[5], Color.GREEN)
            elif total_pl > 0:
                sum_line_parts[5] = Color.wrap(sum_line_parts[5], Color.RED)
            print("".join(sum_line_parts))
            print("-" * 110)
            
            # 使用活躍項目的加總更新下方統計資料
            s_cash = total_cash_pl
            print(f"該時段投入金額 (最高成本): {current_peak:,.0f} 元")
            print(f"累計現金盈虧 (已實現): {s_cash:,.0f} 元 ({(s_cash/current_peak*100):.2f}%)")
            print(f"最終預估盈虧 (活躍持股): {total_pl:,.0f} 元 ({(total_pl/current_peak*100):.2f}%)")
            print("-" * 110 + "\n")

        # --- 月份變動表 ---
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

        print("="*55 + "\n  各月份投資績效變動表\n" + "="*55)
        m_headers = ["月份", "總盈虧差額", "總投入金額", "比例 (%)"]
        m_widths = [11, 14, 14, 12]
        print("".join(pad_string(h, w, 'center') for h, w in zip(m_headers, m_widths)))
        print("-" * 55)
        for r in monthly_report:
            line = pad_string(r["月份"], m_widths[0], 'left')
            line += pad_string(f"{r['差額']:,.0f}", m_widths[1], 'right')
            line += pad_string(f"{r['總投入']:,.0f}", m_widths[2], 'right')
            line += pad_string(f"{r['比例']:.2f}%", m_widths[3], 'right')
            if '*' in r["月份"]: print(Color.wrap(line, Color.YELLOW))
            else: print(line)
        print("-" * 55)

    except Exception:
        import traceback; traceback.print_exc()

if __name__ == "__main__":
    main()
