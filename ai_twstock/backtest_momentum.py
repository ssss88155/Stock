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

# 賣出系統參數
TAKE_PROFIT_HALF_THRESHOLD = _config.get('TAKE_PROFIT_HALF_THRESHOLD', 0.10) # 獲利多少%出清一半
MOMENTUM_EXIT_THRESHOLD = _config.get('MOMENTUM_EXIT_THRESHOLD', 30)         # 動能減退到多少全出

DATA_FILE = 'stock_data.json'
STOCKS_INFO_FILE = 'taiwan_stocks.csv'
EXPORT_PATH = os.path.join('temp_data', 'backtest_transactions.json')
EXCEL_EXPORT_PATH = os.path.join('temp_data', 'backtest_report.xlsx')
# =================================================================

def export_to_excel(report_rows, volatility_data, monthly_stats, export_path):
    """將回測結果匯出至 Excel，包含自動欄寬與紅綠配色"""
    try:
        from openpyxl.styles import Font, Alignment
        from openpyxl.utils import get_column_letter

        # 確保目錄存在
        os.makedirs(os.path.dirname(export_path), exist_ok=True)
        
        # 轉換波動分析資料 (從 tuple 提取顯示字串與顏色判斷值)
        vol_display_data = []
        vol_color_mask = [] # 儲存顏色資訊
        
        for row in volatility_data:
            display_row = {}
            color_row = {}
            for k, v in row.items():
                if isinstance(v, tuple):
                    display_row[k] = v[0]
                    color_row[k] = v[1] # ratio
                else:
                    display_row[k] = v
                    color_row[k] = None
            vol_display_data.append(display_row)
            vol_color_mask.append(color_row)

        with pd.ExcelWriter(export_path, engine='openpyxl') as writer:
            # 1. 波動分析 (移動到第一張工作表)
            df_vol = pd.DataFrame(vol_display_data)
            df_vol.to_excel(writer, sheet_name='波動分析', index=False)
            
            # 2. 投資績效明細表
            df_perf = pd.DataFrame(report_rows)
            df_perf.to_excel(writer, sheet_name='投資績效明細', index=False)
            
            # 3. 月份績效
            df_month = pd.DataFrame(monthly_stats)
            df_month.to_excel(writer, sheet_name='月份績效', index=False)
            
            # --- 開始樣式設定 ---
            workbook = writer.book
            
            # A. 設定「波動分析」樣式
            ws_vol = writer.sheets['波動分析']
            ws_vol.freeze_panes = 'C2'
            
            for col_idx, column_cells in enumerate(ws_vol.columns, 1):
                max_length = 0
                column_letter = get_column_letter(col_idx)
                header_val = ws_vol.cell(row=1, column=col_idx).value
                
                for cell in column_cells:
                    try:
                        if cell.value:
                            val_str = str(cell.value)
                            if len(val_str) > max_length:
                                max_length = len(val_str)
                            
                            # 配色邏輯: 使用預存的 color_mask
                            if cell.row > 1:
                                ratio = vol_color_mask[cell.row - 2].get(header_val)
                                if ratio is not None:
                                    if ratio > 0.0001: # 漲
                                        cell.font = Font(color="FF0000", bold=True)
                                    elif ratio < -0.0001: # 跌
                                        cell.font = Font(color="00AA00", bold=True)
                    except: pass
                # 欄寬設定，針對中文字串調整
                ws_vol.column_dimensions[column_letter].width = max_length * 1.5 + 2

            # B. 設定「投資績效明細」樣式
            ws_perf = writer.sheets['投資績效明細']
            for col_idx, column_cells in enumerate(ws_perf.columns, 1):
                max_length = 0
                for cell in column_cells:
                    if cell.value:
                        l = len(str(cell.value))
                        if l > max_length: max_length = l
                    
                    header_val = ws_perf.cell(row=1, column=col_idx).value
                    if header_val in ["總盈虧", "現金盈虧"] and cell.row > 1:
                        try:
                            val = float(cell.value)
                            if val > 0: cell.font = Font(color="FF0000")
                            elif val < 0: cell.font = Font(color="00AA00")
                        except: pass
                ws_perf.column_dimensions[get_column_letter(col_idx)].width = max_length * 1.2 + 2

            # C. 設定「月份績效」樣式
            ws_month = writer.sheets['月份績效']
            for col_idx, column_cells in enumerate(ws_month.columns, 1):
                max_length = 0
                for cell in column_cells:
                    if cell.value:
                        l = len(str(cell.value))
                        if l > max_length: max_length = l
                    
                    header_val = ws_month.cell(row=1, column=col_idx).value
                    if header_val in ["總盈虧差額", "比例"] and cell.row > 1:
                        try:
                            val = float(cell.value)
                            if val > 0: cell.font = Font(color="FF0000")
                            elif val < 0: cell.font = Font(color="00AA00")
                        except: pass
                ws_month.column_dimensions[get_column_letter(col_idx)].width = max_length * 1.2 + 2
            
        print(f"[INFO] Excel 報表 (含正確紅綠配色與自動欄寬) 已匯出至: {export_path}")
    except Exception as e:
        print(f"[WARN] 匯出 Excel 失敗: {e}\n{traceback.format_exc() if 'traceback' in globals() else ''}")

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
    
    # 3. 模擬交易 (逐日檢查賣出，特定日期買入)
    actual_buy_dates = {}
    for bd in BUY_DATES:
        target = bd
        if target not in all_dates:
            available = [d for d in all_dates if d >= target]
            if available: target = available[0]
            else: continue
        actual_buy_dates[target] = bd

    # 取得回測範圍
    first_buy_target = min(actual_buy_dates.keys())
    start_idx_for_loop = all_dates.index(first_buy_target)
    
    for idx in range(start_idx_for_loop, len(all_dates)):
        current_date = all_dates[idx]
        date_key = current_date.replace('-', '')
        
        # --- A. 每日檢查賣出條件 (如果有持股) ---
        has_holdings = any(p['shares'] > 0 for p in portfolio.values())
        if has_holdings:
            # 取得今日動能分析 (用於全賣出判斷)
            start_date_mom = all_dates[idx - 20] if idx >= 20 else all_dates[0]
            results = analyze_momentum.analyze_momentum(data, start_date_mom, current_date)
            mom_scores = {r['stock_id']: r['score'] for r in results}
            
            sids = list(portfolio.keys())
            for sid in sids:
                pos = portfolio[sid]
                if pos['shares'] <= 0: continue
                if current_date not in data[sid]['price']: continue
                
                curr_price = data[sid]['price'][current_date]['close']
                # 計算相對於均價的獲利
                profit_ratio = (curr_price - pos['avg_price']) / pos['avg_price']
                
                # 1. 獲利出清一半 (達標且未曾出清一半)
                if profit_ratio >= TAKE_PROFIT_HALF_THRESHOLD and not pos.get('half_sold', False):
                    shares_to_sell = pos['shares'] // 2
                    if shares_to_sell > 0:
                        rev = shares_to_sell * curr_price
                        s_fee = round(rev * 0.001425)
                        s_tax = round(rev * 0.003) # 交易稅
                        net_rev = rev - s_fee - s_tax
                        
                        cash += net_rev
                        # 紀錄賣出
                        pos['shares'] -= shares_to_sell
                        pos['realized_pl'] = pos.get('realized_pl', 0) + (curr_price - pos['avg_price']) * shares_to_sell - s_fee - s_tax
                        pos['total_sold_revenue'] = pos.get('total_sold_revenue', 0) + net_rev
                        pos['half_sold'] = True
                        
                        transactions.append({
                            'date': current_date,
                            'stock_id': sid,
                            'side': 'S',
                            'shares': shares_to_sell,
                            'price': curr_price,
                            'revenue': net_rev
                        })
                        
                        if date_key not in json_history: json_history[date_key] = []
                        json_history[date_key].append({
                            "stk_no": sid,
                            "stk_na": pos['name'],
                            "side": "S",
                            "price_avg": float(curr_price),
                            "qty": float(shares_to_sell),
                            "amount": float(rev),
                            "fee": float(s_fee + s_tax),
                            "profit": float((curr_price - pos['avg_price']) * shares_to_sell)
                        })
                        print(f"  [賣出一半] {current_date} {sid} {pos['name']} 獲利達標 {profit_ratio:.1%}, 賣出 {shares_to_sell} 股 @ {curr_price:.2f}")

                # 2. 動能減退全部出清 (暫時註解掉，因為報告太多: 動能減退 0 < 30 的部分了)
                # curr_score = mom_scores.get(sid, 0)
                # if curr_score < MOMENTUM_EXIT_THRESHOLD:
                #     shares_to_sell = pos['shares']
                #     if shares_to_sell > 0:
                #         rev = shares_to_sell * curr_price
                #         s_fee = round(rev * 0.001425)
                #         s_tax = round(rev * 0.003)
                #         net_rev = rev - s_fee - s_tax
                #         
                #         cash += net_rev
                #         pos['realized_pl'] = pos.get('realized_pl', 0) + (curr_price - pos['avg_price']) * shares_to_sell - s_fee - s_tax
                #         pos['total_sold_revenue'] = pos.get('total_sold_revenue', 0) + net_rev
                #         pos['shares'] = 0
                #         
                #         transactions.append({
                #             'date': current_date,
                #             'stock_id': sid,
                #             'side': 'S',
                #             'shares': shares_to_sell,
                #             'price': curr_price,
                #             'revenue': net_rev
                #         })
                #         
                #         if date_key not in json_history: json_history[date_key] = []
                #         json_history[date_key].append({
                #             "stk_no": sid,
                #             "stk_na": pos['name'],
                #             "side": "S",
                #             "price_avg": float(curr_price),
                #             "qty": float(shares_to_sell),
                #             "amount": float(rev),
                #             "fee": float(s_fee + s_tax),
                #             "profit": float((curr_price - pos['avg_price']) * shares_to_sell)
                #         })
                #         print(f"  [全部出清] {current_date} {sid} {pos['name']} 動能減退 {curr_score:.0f} < {MOMENTUM_EXIT_THRESHOLD}, 賣出全部 {shares_to_sell} 股 @ {curr_price:.2f}")

        # --- B. 檢查買入條件 ---
        if current_date in actual_buy_dates:
            if idx < 20: continue
            start_date_buy = all_dates[idx - 20]
            
            results = analyze_momentum.analyze_momentum(data, start_date_buy, current_date)
            valid_results = [r for r in results if r['stock_id'] in data and current_date in data[r['stock_id']]['price']]
            top_stocks = valid_results[:TOP_N]
            
            num_to_buy = len(top_stocks)
            if num_to_buy == 0:
                continue

            target_allocations = calculate_allocations(num_to_buy, DAILY_INVEST_POOL, MIN_LAST_POS_RATIO)
            
            print(f"[INFO] {current_date} 進行購買分析... 預計池: {DAILY_INVEST_POOL:,.0f}, 剩餘現金: {cash:,.0f}")

            actual_pool_spent = 0
            if date_key not in json_history: json_history[date_key] = []
            
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
                            'buys': [],
                            'realized_pl': 0,
                            'total_sold_revenue': 0
                        }
                    
                    portfolio[sid]['shares'] += shares
                    portfolio[sid]['total_cost'] += (actual_cost + fee)
                    portfolio[sid]['avg_price'] = portfolio[sid]['total_cost'] / (sum(b['shares'] for b in portfolio[sid]['buys']) + shares)
                    
                    portfolio[sid]['buys'].append({
                        'date': current_date,
                        'price': price,
                        'shares': shares,
                        'cost': actual_cost + fee
                    })
                    
                    tx_entry = {
                        'date': current_date,
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
        
        realized_pl = pos.get('realized_pl', 0)
        unrealized_pl = (current_price - pos['avg_price']) * pos['shares']
        total_pl_for_sid = realized_pl + unrealized_pl
        
        report_rows.append({
            "編號": sid,
            "公司": pos['name'],
            "最初購買時間": pos['buys'][0]['date'] if pos['buys'] else "---",
            "購買金額": pos['total_cost'],
            "賣出金額": pos.get('total_sold_revenue', 0),
            "現金盈虧": realized_pl,
            "尚餘股數": pos['shares'],
            "均價": pos['avg_price'],
            "現價": current_price,
            "總盈虧": total_pl_for_sid
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
        for t in transactions:
            if t['date'] <= last_d:
                if t['side'] == 'B': m_cash -= t['cost']
                elif t['side'] == 'S': m_cash += t.get('revenue', 0)
        
        m_equity = m_cash
        current_invested = 0
        for sid, pos in portfolio.items():
            shares_at_date = 0
            for t in transactions:
                if t['date'] <= last_d and t['stock_id'] == sid:
                    if t['side'] == 'B': shares_at_date += t['shares']
                    elif t['side'] == 'S': shares_at_date -= t['shares']
            
            if shares_at_date > 0:
                p_at_date = 0
                if last_d in data[sid]['price']:
                    p_at_date = data[sid]['price'][last_d]['close']
                else:
                    valid_p_dates = [d for d in data[sid]['price'].keys() if d <= last_d]
                    if valid_p_dates: p_at_date = data[sid]['price'][max(valid_p_dates)]['close']
                
                m_equity += shares_at_date * p_at_date
                # 使用成本基準作為投入金額
                current_invested += pos['avg_price'] * shares_at_date
        
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
    
    total_pl_acc = 0
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
        total_pl_acc += r['總盈虧']
    
    print("-" * 140)
    # 計算加總
    total_buy_amt = sum(r['購買金額'] for r in report_rows)
    total_sell_amt = sum(r['賣出金額'] for r in report_rows)
    total_realized_pl_sum = sum(r['現金盈虧'] for r in report_rows)
    total_shares_sum = sum(r['尚餘股數'] for r in report_rows)
    
    total_line = pad_to_width("總計", h_wids[0], 'left')
    total_line += pad_to_width("", h_wids[1], 'left')
    total_line += pad_to_width("", h_wids[2], 'center')
    total_line += pad_to_width(f"{total_buy_amt:,.0f}", h_wids[3], 'right')
    total_line += pad_to_width(f"{total_sell_amt:,.0f}", h_wids[4], 'right')
    total_line += pad_to_width(f"{total_realized_pl_sum:,.0f}", h_wids[5], 'right')
    total_line += pad_to_width(f"{total_shares_sum:,.1f}", h_wids[6], 'right')
    total_line += pad_to_width("", h_wids[7], 'right')
    total_line += pad_to_width("", h_wids[8], 'right')
    
    pl_total_text = pad_to_width(f"{total_pl_acc:,.0f}", h_wids[9], 'right')
    total_line += get_color_pl(total_pl_acc, pl_total_text)
    print(total_line)
    
    print("-" * 140)
    print(f"該時段投入金額 (持股成本峰值): {peak_invested:,.0f} 元")
    total_realized = sum(r['現金盈虧'] for r in report_rows)
    realized_ratio = (total_realized / peak_invested * 100) if peak_invested > 0 else 0
    print(f"累計現金盈虧 (已實現): {get_color_pl(total_realized)} 元 ({get_color_ratio(realized_ratio)})")
    
    pl_ratio = (total_pl_acc/peak_invested*100) if peak_invested > 0 else 0
    print(f"最終預估盈虧 (含持股): {get_color_pl(total_pl_acc, f'{total_pl_acc:,.0f}')} 元 ({get_color_ratio(pl_ratio)})")
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
    
    vol_analysis_rows = []
    for sid, pos in portfolio.items():
        line = pad_to_width(sid, 8)
        line += pad_to_width(pos['name'], 12)
        
        vol_row = {"編號": sid, "公司": pos['name']}
        
        first_buy_date = pos['buys'][0]['date'] if pos['buys'] else "9999-99-99"
        first_buy_price = pos['buys'][0]['price'] if pos['buys'] else 0
        buy_dates_map = {b['date']: b['price'] for b in pos['buys']}
        
        for d in display_dates:
            label = d
            if d == latest_data_date: label = f"今日({d})"
            
            # 只顯示最初買入之後的價格
            if d < first_buy_date:
                line += pad_to_width("---", 15, 'right')
                vol_row[label] = "---"
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
                
                # 儲存為 tuple 以便 Excel 匯出時判斷顏色
                vol_row[label] = (combined, diff_ratio)
                
                # 只有後續買入（非第一次）才加底線高亮 (今日價格不加底線除非今日也有買)
                is_buy = d in buy_dates_map
                is_highlight = is_buy and (d != first_buy_date)
                
                styled_val = get_color_ratio(diff_ratio, combined, highlight=is_highlight)
                # 確保補白不被包含在樣式內
                line += " " * (15 - len(combined)) + styled_val
            else:
                line += pad_to_width("---", 15, 'right')
                vol_row[label] = ("---", 0)
        print(line)
        vol_analysis_rows.append(vol_row)
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

    # 匯出至 Excel
    export_to_excel(report_rows, vol_analysis_rows, monthly_stats, EXCEL_EXPORT_PATH)

if __name__ == "__main__":
    run_backtest()
