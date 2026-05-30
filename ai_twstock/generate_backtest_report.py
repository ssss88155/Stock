import os
import json
import pandas as pd
import sys
import calendar
from datetime import datetime
from collections import OrderedDict

# 將 lib 目錄加入 Python 路徑
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
try:
    from common_lib import Color, pad_string, get_display_width
except ImportError:
    class Color:
        RED = "\033[91m"; GREEN = "\033[92m"; YELLOW = "\033[93m"; ORANGE = "\033[38;5;208m"
        BLUE = "\033[94m"; PURPLE = "\033[95m"; CYAN = "\033[96m"; DIM = "\033[2m"; RESET = "\033[0m"; WHITE = "\033[97m"
        @staticmethod
        def wrap(text, color): return f"{color}{text}{Color.RESET}"
    
    def get_display_width(s):
        import unicodedata
        width = 0
        for char in str(s):
            if unicodedata.east_asian_width(char) in ('W', 'F', 'A'): width += 2
            else: width += 1
        return width

    def pad_string(s, width, align='left'):
        s = str(s)
        current_width = get_display_width(s)
        pad_size = max(0, width - current_width)
        if align == 'left': return s + ' ' * pad_size
        elif align == 'right': return ' ' * pad_size + s
        else:
            left_pad = pad_size // 2
            right_pad = pad_size - left_pad
            return ' ' * left_pad + s + ' ' * right_pad

import backtest_momentum

def parse_date(d_str):
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try: return datetime.strptime(d_str, fmt)
        except: continue
    return None

def generate_report():
    output_file = r"C:\jupyter_notebook\ai_twstock\temp_data\monthly_report.txt"
    log_f = open(output_file, "w", encoding="utf-8")

    def log_print(msg, color=None):
        if color:
            print(Color.wrap(msg, color))
        else:
            print(msg)
        log_f.write(str(msg) + "\n")

    # 1. 載入最佳設定
    config_path = r"C:\jupyter_notebook\ai_twstock\temp_data\best_strategy_config.json"
    if not os.path.exists(config_path):
        log_print("找不到最佳設定檔，請先執行 optimize_strategy.py")
        return
    
    with open(config_path, 'r', encoding='utf-8') as f:
        best_cfg = json.load(f)

    log_print("正在執行最佳組合回測以生成報表...")
    res = backtest_momentum.run_backtest(override_config=best_cfg, silent=True)
    
    history = res['history']
    portfolio = res['portfolio']
    report_rows = res['report_rows']
    
    sorted_dates = sorted(history.keys())
    if not sorted_dates:
        log_print("無交易紀錄")
        return

    final_date_str = sorted_dates[-1]
    final_dt = parse_date(final_date_str)

    # --- Section 1: 詳細交易流水帳 (Moved to top) ---
    log_print("\n" + "="*100 + "\n  一、 詳細交易流水帳 (按日期排序)\n" + "="*100)
    tx_h = ["日期", "代號", "方向", "股數", "價格", "變動金額", "實現盈虧"]
    tx_w = [12, 8, 6, 10, 10, 15, 12]
    log_print("".join(pad_string(h, tx_w[i], 'center') for i, h in enumerate(tx_h)))
    log_print("-" * 100)

    for d in sorted(history.keys()):
        for entry in history[d]:
            if entry.get('side') == 'INFO': continue
            
            side_str = "買入" if entry['side'] == 'B' else "賣出"
            profit = entry.get('profit', 0)
            amount = entry.get('amount', 0)
            
            line_parts = [
                pad_string(d, tx_w[0], 'left'),
                pad_string(entry['stk_no'], tx_w[1], 'left'),
                pad_string(side_str, tx_w[2], 'center'),
                pad_string(f"{entry['qty']:,.0f}", tx_w[3], 'right'),
                pad_string(f"{entry['price_avg']:.2f}", tx_w[4], 'right'),
                pad_string(f"{amount:,.0f}", tx_w[5], 'right'),
                pad_string(f"{profit:,.0f}", tx_w[6], 'right')
            ]
            
            text = "".join(line_parts)
            if entry['side'] == 'B':
                print(text)
            else:
                if profit > 0: print(Color.wrap(text, Color.RED))
                elif profit < 0: print(Color.wrap(text, Color.GREEN))
                else: print(text)
            log_f.write(text + "\n")

    # --- Section 2: 持股狀況 ---
    log_print("\n" + "="*110 + f"\n  二、 當前持股狀況 (至 {final_dt.strftime('%Y-%m-%d')})\n" + "="*110)
    h_cols = ["編號", "公司", "購買金額", "賣出金額", "現金盈虧", "尚餘股數", "均價", "現價", "總盈虧"]
    h_wids = [8, 14, 12, 12, 12, 10, 10, 10, 12]
    log_print("".join(pad_string(h, h_wids[i], 'center') for i, h in enumerate(h_cols)))
    log_print("-" * 110)
    
    active_buy, active_sell, active_cash_pl, active_total_pl = 0, 0, 0, 0
    rows = []
    for r in report_rows:
        sid = r['編號']
        pos = portfolio[sid]
        cash_pl = pos.get('realized_pl', 0)
        shares = pos['shares']
        avg_p = pos['avg_price']
        total_pl_val = r['總盈虧']
        unrealized = total_pl_val - cash_pl
        curr_p = avg_p + (unrealized / shares) if shares > 0 else 0
        rows.append({
            "編號": sid, "公司": r['公司'], "購買金額": r['購買金額'],
            "賣出金額": pos.get('total_sold_revenue', 0), "現金盈虧": cash_pl,
            "尚餘股數": shares, "均價": avg_p, "現價": curr_p, "總盈虧": total_pl_val
        })

    rows.sort(key=lambda x: x["尚餘股數"] == 0)
    for r in rows:
        is_dim = (r["尚餘股數"] == 0)
        if not is_dim:
            active_buy += r['購買金額']; active_sell += r['賣出金額']
            active_cash_pl += r['現金盈虧']; active_total_pl += r['總盈虧']

        line = [
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
        text = "".join(line)
        if is_dim: log_print(Color.wrap(text, Color.DIM))
        else:
            if r["總盈虧"] < 0: line[8] = Color.wrap(line[8], Color.GREEN)
            elif r["總盈虧"] > 0: line[8] = Color.wrap(line[8], Color.RED)
            log_print("".join(line))

    log_print("-" * 110)
    sum_line = [
        pad_string("合計 (活躍持股)", h_wids[0] + h_wids[1], 'left'),
        pad_string(f"{active_buy:,.0f}", h_wids[2], 'right'),
        pad_string(f"{active_sell:,.0f}", h_wids[3], 'right'),
        pad_string(f"{active_cash_pl:,.0f}", h_wids[4], 'right'),
        pad_string("", h_wids[5] + h_wids[6] + h_wids[7], 'right'),
        pad_string(f"{active_total_pl:,.0f}", h_wids[8], 'right')
    ]
    if active_total_pl < 0: sum_line[5] = Color.wrap(sum_line[5], Color.GREEN)
    elif active_total_pl > 0: sum_line[5] = Color.wrap(sum_line[5], Color.RED)
    log_print("".join(sum_line))

    # --- Section 3: 最終結果與月份摘要 ---
    log_print("\n" + "="*55 + "\n  三、 最終投資結果與月份摘要\n" + "="*55)
    peak_cap = max([history[d][-1].get('invested_capital_snapshot', 0) for d in history])
    log_print(f"最終累積資產 (Ending Equity): {res['total_pl'] + best_cfg['STARTING_CASH']:,.0f}")
    log_print(f"最終資產報酬率 (ROI): {res['roi']:.2%}")
    log_print(f"大多頭期間最高水位 (Equity Peak): {peak_cap:,.0f}")
    log_print("-" * 55)

    m_h = ["月份", "總投入資產", "當月損益", "月報酬率"]
    m_w = [12, 15, 14, 12]
    log_print("".join(pad_string(h, m_w[i], 'center') for i, h in enumerate(m_h)))
    log_print("-" * 55)

    month_data = OrderedDict()
    for d in sorted_dates:
        clean_d = d.replace('-', '')
        m_key = f"{clean_d[:4]}-{clean_d[4:6]}"
        equity = 0
        if history[d]: equity = history[d][-1].get('invested_capital_snapshot', 0)
        if equity > 0: month_data[m_key] = equity
    
    prev_equity = best_cfg['STARTING_CASH']
    for m, eq in month_data.items():
        diff = eq - prev_equity
        pct = (diff / prev_equity * 100) if prev_equity > 0 else 0
        line = pad_string(m, m_w[0], 'left') + pad_string(f"{eq:,.0f}", m_w[1], 'right') + \
               pad_string(f"{diff:,.0f}", m_w[2], 'right') + pad_string(f"{pct:.2f}%", m_w[3], 'right')
        if diff > 0: log_print(Color.wrap(line, Color.RED))
        elif diff < 0: log_print(Color.wrap(line, Color.GREEN))
        else: log_print(line)
        prev_equity = eq
    
    log_print("-" * 55)
    final_msg = f"\n報表已儲存至: {output_file}"
    print(final_msg)
    log_f.write(final_msg + "\n")
    log_f.close()

if __name__ == "__main__":
    generate_report()
