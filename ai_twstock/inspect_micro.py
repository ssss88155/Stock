import os
import json
import argparse
import pandas as pd
import sys
from datetime import datetime

# 將 lib 目錄加入 Python 路徑以使用 common_lib
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
from common_lib import Color, pad_string, get_display_width

def print_stock_micro(stock_id, start_date=None, end_date=None, trader_id=None):
    price_dir = r"C:\jupyter_notebook\ai_twstock\data_independent_price"
    micro_dir = r"C:\jupyter_notebook\ai_twstock\data_independent_microstructure"
    stocks_info_path = r"C:\jupyter_notebook\ai_twstock\taiwan_stocks.csv"
    
    # 1. 取得公司名稱
    stock_name = "未知"
    if os.path.exists(stocks_info_path):
        try:
            df_info = pd.read_csv(stocks_info_path)
            match = df_info[df_info.iloc[:, 0].astype(str) == str(stock_id)]
            if not match.empty:
                stock_name = match.iloc[0, 1]
        except:
            pass

    # 2. 資料讀取
    price_path = os.path.join(price_dir, f"{stock_id}.json")
    micro_path = os.path.join(micro_dir, f"{stock_id}.json")
    
    main_data = {}
    if os.path.exists(price_path):
        with open(price_path, 'r', encoding='utf-8') as f:
            main_data = json.load(f)
    
    sid_data = main_data.get(stock_id, main_data)
    price_map = sid_data.get('price', {})

    report = sid_data.get('trading_daily_report', {})
    if not report and os.path.exists(micro_path):
        with open(micro_path, 'r', encoding='utf-8') as f:
            m_data = json.load(f)
            m_sid_data = m_data.get(stock_id, m_data)
            report = m_sid_data.get('trading_daily_report', m_sid_data)

    if not report:
        print(f"找不到代號 {stock_id} 的分點交易紀錄。")
        return

    # 3. 日期過濾與排序
    sorted_dates = sorted(report.keys())
    if start_date:
        sorted_dates = [d for d in sorted_dates if d >= start_date]
    if end_date:
        sorted_dates = [d for d in sorted_dates if d <= end_date]

    if not sorted_dates:
        print("指定的時間範圍內無資料。")
        return

    # 4. 模式切換
    if trader_id:
        print(f"\n===== 股票代號: {stock_id} ({stock_name}) | 券商 {trader_id} 進出流水帳 =====")
        
        # 標題單位改為 (千萬)
        headers = ["日期", "買/賣量", "股數", "均價", "總金額(千萬)"]
        widths = [14, 15, 15, 10, 20]
        
        print("".join(pad_string(h, widths[i], 'center') for i, h in enumerate(headers)))
        print("-" * sum(widths))
        
        total_balance = 0
        total_net_qty = 0
        
        for date_str in sorted_dates:
            day_data = report[date_str]
            if not isinstance(day_data, dict): continue
            
            target_entry = None
            for b in day_data.get('top_buyers', []):
                if trader_id in b.get('trader', ''):
                    target_entry = {'qty': b.get('net', 0), 'avg_p': b.get('avg_p', 0), 'side': 'B'}
                    break
            if not target_entry:
                for s in day_data.get('top_sellers', []):
                    if trader_id in s.get('trader', ''):
                        target_entry = {'qty': s.get('net_s', 0), 'avg_p': s.get('avg_p', 0), 'side': 'S'}
                        break
            
            if target_entry:
                qty = abs(target_entry['qty']) # 買賣與股數都取絕對值
                avg_p = target_entry['avg_p']
                
                # 計算實際金額流向 (用於損益統計與正負顯示)
                raw_amount = (qty * avg_p) if target_entry['side'] == 'S' else -(qty * avg_p)
                total_balance += raw_amount
                total_net_qty += (qty if target_entry['side'] == 'S' else -qty)
                
                # 金額轉化為千萬單位
                amount_in_ten_mil = raw_amount / 10_000_000
                
                # 數值格式化 (保留一位小數)
                qty_str = f"{qty:,.1f}"
                avg_p_str = f"{avg_p:.1f}"
                amount_val_str = f"{amount_in_ten_mil:,.1f}"
                
                # 顏色處理
                color = Color.RED if raw_amount > 0 else (Color.GREEN if raw_amount < 0 else Color.END)
                
                # 組合字串
                line_str = pad_string(date_str, widths[0], 'left') + \
                           pad_string(qty_str, widths[1], 'right') + \
                           pad_string(qty_str, widths[2], 'right') + \
                           pad_string(avg_p_str, widths[3], 'right') + \
                           ' ' * max(1, (widths[4] - get_display_width(amount_val_str))) + Color.wrap(amount_val_str, color)
                
                sys.stdout.write(line_str + "\n")
        
        print("-" * sum(widths))
        final_balance_in_ten_mil = total_balance / 10_000_000
        final_balance_str = f"{final_balance_in_ten_mil:,.1f}"
        color_final = Color.RED if total_balance > 0 else (Color.GREEN if total_balance < 0 else Color.END)
        
        print(f"最終累積股數: {total_net_qty:,.1f}")
        print(f"進出貨現金餘額 (千萬): {Color.wrap(final_balance_str, color_final)}")
        
    else:
        # 摘要模式
        print(f"\n股票代號: {stock_id}   公司: {stock_name}")
        print("=" * 60)
        for date_str in sorted_dates:
            day_data = report[date_str]
            if not isinstance(day_data, dict): continue
            close_p = price_map.get(date_str, {}).get('close', "無資料")
            if isinstance(close_p, (int, float)): close_p = f"{close_p:.1f}"
            print(f"\n日期: {date_str}   當天收盤價: {close_p}")
            
            top_b = day_data.get('top_buyers', [])
            if top_b:
                print("--- 買超前五分點 ---")
                for i, b in enumerate(top_b[:5], 1):
                    t_info = b.get('trader', '未知/0000').split('/')
                    t_name = t_info[0]; t_id = t_info[1] if len(t_info) > 1 else "未知"
                    print(f"No.{i:02}: {t_name:<10} 代號: {t_id:<6} 購買量: {b.get('net', 0):<8.1f} 均價: {b.get('avg_p', 0):.1f}")
            
            top_s = day_data.get('top_sellers', [])
            if top_s:
                print("--- 賣超前五分點 ---")
                for i, s in enumerate(top_s[:5], 1):
                    t_info = s.get('trader', '未知/0000').split('/')
                    t_name = t_info[0]; t_id = t_info[1] if len(t_info) > 1 else "未知"
                    print(f"No.{i:02}: {t_name:<10} 代號: {t_id:<6} 賣出量: {s.get('net_s', 0):<8.1f} 均價: {s.get('avg_p', 0):.1f}")
            print("-" * 40)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stock_id")
    parser.add_argument("--start", help="起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", help="結束日期 (YYYY-MM-DD)")
    parser.add_argument("--trader", help="指定券商代號")
    args = parser.parse_args()
    print_stock_micro(args.stock_id, args.start, args.end, args.trader)
