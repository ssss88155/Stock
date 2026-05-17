import json
import os
import sys
import pandas as pd
import unicodedata
from datetime import datetime, timedelta
import calendar
from collections import OrderedDict

# 嘗試設定輸出編碼為 UTF-8 以支援中文
try:
    if sys.stdout.encoding != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

# ANSI 樣式定義 (全域變數)
COLOR_UP = "\033[91m"     # 紅色
COLOR_DOWN = "\033[92m"   # 綠色
STYLE_BOLD = "\033[1m"    # 粗體
STYLE_UNDER = "\033[4m"   # 底線
STYLE_RESET = "\033[0m"

# Import existing momentum analysis logic
import analyze_momentum

# =================================================================
# 回合測試參數設定 (變數)
# =================================================================
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config', 'backtest_config.json')

def load_config():
    """載入回測參數設定"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] 載入設定檔失敗: {e}")
    return {}

_config = load_config()
STARTING_CASH = _config.get('STARTING_CASH', 1000000)        # 起始資金
DAILY_INVEST_POOL = _config.get('DAILY_INVEST_POOL', 300000)     # 每次購買日期預計投入的總金額
TOP_N = _config.get('TOP_N', 10)                     # 每次購買前 N 名
BUY_DATES = _config.get('BUY_DATES', ['2026-02-10', '2026-03-10', '2026-04-10'])  # 預定購買日期
MIN_LAST_POS_RATIO = _config.get('MIN_LAST_POS_RATIO', 0.20)      # 最後一名佔第一名的比例 (等差級數限制，不得低於 20%)

DATA_FILE = 'stock_data.json'
STOCKS_INFO_FILE = 'taiwan_stocks.csv'
EXPORT_PATH = os.path.join('temp_data', 'backtest_transactions.json')
# =================================================================

def calculate_allocations(k, total_pool, ratio):
    """
    計算等差級數分配金額
    使用 y = b - ax (其中 x 為排名 1, 2, ..., k)
    限制: y_k = ratio * y_1 且 sum(y) = total_pool
    """
    if k <= 0: return []
    if k == 1: return [total_pool]
    
    w1 = 1.0 / (k * (1.0 + ratio) / 2.0)
    d = w1 * (1.0 - ratio) / (k - 1.0)
    
    allocations = [(w1 - i * d) * total_pool for i in range(k)]
    return allocations

def get_display_width(s):
    width = 0
    for char in str(s):
        if unicodedata.east_asian_width(char) in ('W', 'F', 'A'):
            width += 2
        else:
            width += 1
    return width

def pad_to_width(s, width, align='left'):
    s = str(s)
    current_width = get_display_width(s)
    pad_size = max(0, width - current_width)
    if align == 'left':
        return s + ' ' * pad_size
    elif align == 'right':
        return ' ' * pad_size + s
    else:
        left_pad = pad_size // 2
        right_pad = pad_size - left_pad
        return ' ' * left_pad + s + ' ' * right_pad

def load_stock_names():
    names = {}
    path = os.path.join(os.path.dirname(__file__), STOCKS_INFO_FILE)
    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
            code_col = 'code' if 'code' in df.columns else df.columns[0]
            name_col = 'name' if 'name' in df.columns else df.columns[1]
            for _, row in df.iterrows():
                names[str(row[code_col])] = str(row[name_col])
        except Exception as e:
            print(f"[WARN] Error loading stock names: {e}")
    return names

def run_backtest():
    # 1. 載入資料
    data = analyze_momentum.load_data(DATA_FILE)
    stock_names = load_stock_names()
    
    if not data:
        print("無法載入資料，請檢查路徑。")
        return

    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    
    # 2. 初始化帳戶
    cash = STARTING_CASH
    portfolio = {} 
    transactions = [] # 用於內部邏輯
    json_history = OrderedDict() # 用於匯出
    
    # 累計投入金額 (最高成本)
    running_invested_capital = 0
    
    # 3. 模擬購買
    for buy_date in BUY_DATES:
        if buy_date not in all_dates:
            available = [d for d in all_dates if d >= buy_date]
            if not available: continue
            actual_buy_date = available[0]
        else:
            actual_buy_date = buy_date

        idx = all_dates.index(actual_buy_date)
        if idx < 20: continue
        start_date = all_dates[idx - 20]
        
        results = analyze_momentum.analyze_momentum(data, start_date, actual_buy_date)
        valid_results = [r for r in results if r['stock_id'] in data and actual_buy_date in data[r['stock_id']]['price']]
        top_stocks = valid_results[:TOP_N]
        
        num_to_buy = len(top_stocks)
        if num_to_buy == 0:
            continue

        target_allocations = calculate_allocations(num_to_buy, DAILY_INVEST_POOL, MIN_LAST_POS_RATIO)
        
        print(f"[INFO] {actual_buy_date} 進行購買分析... 預計池: {DAILY_INVEST_POOL:,.0f}, 剩餘現金: {cash:,.0f}")

        actual_pool_spent = 0
        date_key = actual_buy_date.replace('-', '')
        json_history[date_key] = []
        
        for i, res in enumerate(top_stocks):
            sid = res['stock_id']
            price = res['close']
            target_amount = target_allocations[i]
            
            if cash <= 0: break
            
            max_buyable = min(cash, target_amount)
            shares = max_buyable // price
            actual_cost = shares * price
            
            if shares > 0:
                fee = round(actual_cost * 0.001425) # 模擬手續費
                cash -= (actual_cost + fee)
                actual_pool_spent += (actual_cost + fee)
                running_invested_capital += (actual_cost + fee)
                
                if sid not in portfolio:
                    portfolio[sid] = {
                        'shares': 0, 
                        'total_cost': 0, 
                        'name': stock_names.get(sid, sid),
                        'buys': []  # 紀錄各次購買詳情
                    }
                
                portfolio[sid]['shares'] += shares
                portfolio[sid]['total_cost'] += (actual_cost + fee)
                portfolio[sid]['avg_price'] = portfolio[sid]['total_cost'] / portfolio[sid]['shares']
                
                portfolio[sid]['buys'].append({
                    'date': actual_buy_date,
                    'price': price,
                    'shares': shares,
                    'cost': actual_cost + fee
                })
                
                tx_entry = {
                    'date': actual_buy_date,
                    'stock_id': sid,
                    'side': 'B',
                    'shares': shares,
                    'price': price,
                    'cost': actual_cost + fee
                }
                transactions.append(tx_entry)
                
                # 匯出格式
                json_entry = {
                    "stk_no": sid,
                    "stk_na": portfolio[sid]['name'],
                    "side": "B",
                    "price_avg": float(price),
                    "qty": float(shares),
                    "amount": float(actual_cost),
                    "fee": float(fee),
                    "profit": 0.0
                }
                json_history[date_key].append(json_entry)
                
                print(f"  - 排名 {i+1} 預計 {target_amount:,.0f} -> 買入 {sid}: {shares} 股 @ {price:.2f}, 實際花費: {actual_cost + fee:,.0f}")
        
        # 在當天最後一筆交易加入 snapshot
        if json_history[date_key]:
            json_history[date_key][-1]["invested_capital_snapshot"] = float(running_invested_capital)
            
        print(f"  => 該次實際總花費 (含費): {actual_pool_spent:,.0f}")

    # 4. 匯出 JSON
    export_dir = os.path.dirname(EXPORT_PATH)
    if export_dir and not os.path.exists(export_dir):
        os.makedirs(export_dir)
        
    # 排序日期
    sorted_history = OrderedDict()
    for k in sorted(json_history.keys(), reverse=True):
        sorted_history[k] = json_history[k]
        
    with open(EXPORT_PATH, 'w', encoding='utf-8') as f:
        json.dump(sorted_history, f, ensure_ascii=False, indent=2)
    print(f"\n[INFO] 交易紀錄已匯出至: {EXPORT_PATH}")

    # 5. 結算報表
    final_date = all_dates[-1]
    report_rows = []
    
    for sid, pos in portfolio.items():
        current_price = 0
        if final_date in data[sid]['price']:
            current_price = data[sid]['price'][final_date]['close']
        else:
            s_dates = sorted(data[sid]['price'].keys())
            if s_dates:
                current_price = data[sid]['price'][s_dates[-1]]['close']
        
        unrealized_pl = (current_price - pos['avg_price']) * pos['shares']
        
        report_rows.append({
            "編號": sid,
            "公司": pos['name'],
            "最初購買時間": pos['buys'][0]['date'] if pos['buys'] else "---",
            "購買金額": pos['total_cost'],
            "賣出金額": 0,
            "現金盈虧": 0,
            "尚餘股數": pos['shares'],
            "均價": pos['avg_price'],
            "現價": current_price,
            "總盈虧": unrealized_pl
        })

    months = sorted(list(set(d[:7] for d in all_dates if d >= BUY_DATES[0])))
    monthly_stats = []
    prev_equity = STARTING_CASH
    peak_invested = 0
    
    for m in months:
        m_dates = [d for d in all_dates if d.startswith(m)]
        if not m_dates: continue
        last_d = m_dates[-1]
        
        m_cash = STARTING_CASH
        m_cash -= sum(t['cost'] for t in transactions if t['date'] <= last_d)
        
        m_equity = m_cash
        current_invested = 0
        for sid, pos in portfolio.items():
            shares_at_date = sum(t['shares'] for t in transactions if t['date'] <= last_d and t['stock_id'] == sid)
            if shares_at_date > 0:
                p_at_date = 0
                if last_d in data[sid]['price']:
                    p_at_date = data[sid]['price'][last_d]['close']
                else:
                    valid_p_dates = [d for d in data[sid]['price'].keys() if d <= last_d]
                    if valid_p_dates: p_at_date = data[sid]['price'][max(valid_p_dates)]['close']
                
                m_equity += shares_at_date * p_at_date
                cost_at_date = sum(t['cost'] for t in transactions if t['date'] <= last_d and t['stock_id'] == sid)
                current_invested += cost_at_date
        
        if current_invested > peak_invested:
            peak_invested = current_invested
            
        diff = m_equity - prev_equity
        ratio = (diff / peak_invested * 100) if peak_invested > 0 else 0
        
        monthly_stats.append({
            "月份": m,
            "總盈虧差額": diff,
            "總投入金額": peak_invested,
            "比例": ratio
        })
        prev_equity = m_equity

    # --- 輸出報表 ---
    def get_color_pl(val, text=None, highlight=False):
        if text is None: text = f"{val:,.0f}"
        color = ""
        if val > 0.1: color = COLOR_UP
        elif val < -0.1: color = COLOR_DOWN
        
        style = (STYLE_BOLD + STYLE_UNDER) if highlight else ""
        return f"{style}{color}{text}{STYLE_RESET}" if (color or style) else text

    def get_color_ratio(ratio, text=None, highlight=False):
        if text is None: text = f"{ratio:.0f}%"
        color = ""
        if ratio > 0.1: color = COLOR_UP
        elif ratio < -0.1: color = COLOR_DOWN
        
        style = (STYLE_BOLD + STYLE_UNDER) if highlight else ""
        return f"{style}{color}{text}{STYLE_RESET}" if (color or style) else text

    print("\n" + "="*140)
    print(f"  投資績效明細表 (至 {final_date})")
    print("="*140)
    h_cols = ["編號", "公司", "最初購買時間", "購買金額", "賣出金額", "現金盈虧", "尚餘股數", "均價", "現價", "總盈虧"]
    h_wids = [8, 14, 15, 12, 12, 12, 10, 10, 10, 12]
    print("".join(pad_to_width(h, w, 'center') for h, w in zip(h_cols, h_wids)))
    print("-" * 140)
    
    total_pl = 0
    for r in report_rows:
        line = pad_to_width(r["編號"], h_wids[0], 'left')
        line += pad_to_width(r["公司"], h_wids[1], 'left')
        line += pad_to_width(r["最初購買時間"], h_wids[2], 'center')
        line += pad_to_width(f"{r['購買金額']:,.0f}", h_wids[3], 'right')
        line += pad_to_width(f"{r['賣出金額']:,.0f}", h_wids[4], 'right')
        line += pad_to_width(f"{r['現金盈虧']:,.0f}", h_wids[5], 'right')
        line += pad_to_width(f"{r['尚餘股數']:,.1f}", h_wids[6], 'right')
        line += pad_to_width(f"{r['均價']:.0f}", h_wids[7], 'right')
        line += pad_to_width(f"{r['現價']:.0f}", h_wids[8], 'right')
        
        pl_text = pad_to_width(f"{r['總盈虧']:,.0f}", h_wids[9], 'right')
        line += get_color_pl(r['總盈虧'], pl_text)
        print(line)
        total_pl += r['總盈虧']
    
    print("-" * 140)
    print(f"該時段投入金額 (最高成本): {peak_invested:,.0f} 元")
    print(f"累計現金盈虧 (已實現): 0 元 (0%)")
    
    pl_ratio = (total_pl/peak_invested*100) if peak_invested > 0 else 0
    print(f"最終預估盈虧 (含持股): {get_color_pl(total_pl, f'{total_pl:,.0f}')} 元 ({get_color_ratio(pl_ratio)})")
    print("-" * 125 + "\n")

    # 新增：各標的購買時程及相對於最初買入價的波動
    print("="*120)
    print("  各標的購買時程及波動分析 (相對於最初購買價)")
    print("="*120)
    
    # 找出所有出現過的購買日期
    all_buy_dates = sorted(list(set(t['date'] for t in transactions)))
    # 包含最新日期
    latest_data_date = all_dates[-1]
    display_dates = all_buy_dates[:]
    if latest_data_date not in display_dates:
        display_dates.append(latest_data_date)

    header = pad_to_width("編號", 8) + pad_to_width("公司", 12)
    for d in display_dates:
        label = d
        if d == latest_data_date: label = f"今日({d})"
        header += pad_to_width(label, 15, 'center')
    print(header)
    print("-" * (20 + 15 * len(display_dates)))
    
    for sid, pos in portfolio.items():
        line = pad_to_width(sid, 8)
        line += pad_to_width(pos['name'], 12)
        
        first_buy_date = pos['buys'][0]['date'] if pos['buys'] else "9999-99-99"
        first_buy_price = pos['buys'][0]['price'] if pos['buys'] else 0
        buy_dates_map = {b['date']: b['price'] for b in pos['buys']}
        
        for d in display_dates:
            # 只顯示最初買入之後的價格
            if d < first_buy_date:
                line += pad_to_width("---", 15, 'right')
                continue
                
            price = 0
            if d in data[sid]['price']:
                price = data[sid]['price'][d]['close']
                
            if price > 0:
                diff_ratio = (price - first_buy_price) / first_buy_price * 100 if first_buy_price > 0 else 0
                price_str = f"{price:.0f}"
                
                # 最初買入日期不顯示 (0%)，多空一格
                if d == first_buy_date:
                    combined = f"{price_str} "
                else:
                    ratio_str = f"({abs(diff_ratio):.0f}%)"
                    combined = f"{price_str}{ratio_str}"
                
                # 只有後續買入（非第一次）才加底線高亮 (今日價格不加底線除非今日也有買)
                is_buy = d in buy_dates_map
                is_highlight = is_buy and (d != first_buy_date)
                
                styled_val = get_color_ratio(diff_ratio, combined, highlight=is_highlight)
                # 確保補白不被包含在樣式內
                line += " " * (15 - len(combined)) + styled_val
            else:
                line += pad_to_width("---", 15, 'right')
        print(line)
    print("-" * (20 + 15 * len(display_dates)) + "\n")


    print("="*55)
    print("  各月份投資績效變動表")
    print("="*55)
    m_headers = ["月份", "總盈虧差額", "總投入金額", "比例 (%)"]
    m_widths = [11, 14, 14, 12]
    print("".join(pad_to_width(h, w, 'center') for h, w in zip(m_headers, m_widths)))
    print("-" * 55)
    for r in monthly_stats:
        line = pad_to_width(r["月份"], m_widths[0], 'left')
        line += pad_to_width(f"{r['總盈虧差額']:,.0f}", m_widths[1], 'right')
        line += pad_to_width(f"{r['總投入金額']:,.0f}", m_widths[2], 'right')
        
        ratio_text = pad_to_width(f"{r['比例']:.0f}%", m_widths[3], 'right')
        line += get_color_ratio(r['比例'], ratio_text)
        
        if r['月份'] == months[-1]:
            print(f"\033[93m*{line}\033[0m")
        else:
            print(line)
    print("-" * 55)

if __name__ == "__main__":
    run_backtest()
