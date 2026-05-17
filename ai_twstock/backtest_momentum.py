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
        
        # 轉換波動分析資料
        vol_display_data = []
        vol_color_mask = []
        
        for row in volatility_data:
            display_row = {}
            color_row = {}
            for k, v in row.items():
                if isinstance(v, tuple):
                    display_row[k] = v[0]
                    color_row[k] = v[1]
                else:
                    display_row[k] = v
                    color_row[k] = None
            vol_display_data.append(display_row)
            vol_color_mask.append(color_row)

        with pd.ExcelWriter(export_path, engine='openpyxl') as writer:
            df_vol = pd.DataFrame(vol_display_data)
            df_vol.to_excel(writer, sheet_name='波動分析', index=False)
            df_perf = pd.DataFrame(report_rows)
            df_perf.to_excel(writer, sheet_name='投資績效明細', index=False)
            df_month = pd.DataFrame(monthly_stats)
            df_month.to_excel(writer, sheet_name='月份績效', index=False)
            
            workbook = writer.book
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
                            if len(val_str) > max_length: max_length = len(val_str)
                            if cell.row > 1:
                                ratio = vol_color_mask[cell.row - 2].get(header_val)
                                if ratio is not None:
                                    if ratio > 0.0001: cell.font = Font(color="FF0000", bold=True)
                                    elif ratio < -0.0001: cell.font = Font(color="00AA00", bold=True)
                    except: pass
                ws_vol.column_dimensions[column_letter].width = max_length * 1.5 + 2

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
            
        print(f"[INFO] Excel 報表已匯出至: {export_path}")
    except Exception as e:
        print(f"[WARN] 匯出 Excel 失敗: {e}")

def calculate_allocations(k, total_pool, ratio):
    if k <= 0: return []
    if k == 1: return [total_pool]
    w1 = 1.0 / (k * (1.0 + ratio) / 2.0)
    d = w1 * (1.0 - ratio) / (k - 1.0)
    allocations = [(w1 - i * d) * total_pool for i in range(k)]
    return allocations

def get_display_width(s):
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
    elif align == 'right': return ' ' * pad_size + s
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
            for _, row in df.iterrows(): names[str(row[code_col])] = str(row[name_col])
        except Exception as e: print(f"[WARN] Error loading stock names: {e}")
    return names

def run_backtest(override_config=None, silent=False):
    # 1. 載入資料與設定
    data = analyze_momentum.load_stock_data_wrapper(DATA_FILE)
    stock_names = load_stock_names()
    _config = load_config()
    if override_config: _config.update(override_config)

    starting_cash = _config.get('STARTING_CASH', 1000000)
    daily_invest_pool = _config.get('DAILY_INVEST_POOL', 300000)
    top_n = _config.get('TOP_N', 10)
    buy_dates_config = _config.get('BUY_DATES', ['2026-02-10', '2026-03-10', '2026-04-10'])
    min_last_pos_ratio = _config.get('MIN_LAST_POS_RATIO', 0.20)
    buy_score_threshold = _config.get('BUY_SCORE_THRESHOLD', 0)
    
    take_profit_half_threshold = _config.get('TAKE_PROFIT_HALF_THRESHOLD', 0.10)
    momentum_exit_threshold = _config.get('MOMENTUM_EXIT_THRESHOLD', 30)
    stop_loss_threshold = _config.get('STOP_LOSS_THRESHOLD', -0.10)
    trailing_stop_threshold = _config.get('TRAILING_STOP_THRESHOLD', -0.15)

    if not data:
        if not silent: print("無法載入資料，請檢查路徑。")
        return None

    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    
    # 2. 初始化帳戶
    cash = starting_cash
    portfolio = {} 
    transactions = [] 
    json_history = OrderedDict() 
    running_invested_capital = 0
    
    # 3. 模擬交易
    weights = _config.get('WEIGHTS', None)
    is_daily = (buy_dates_config == "DAILY")
    
    # 計算市場廣度 (Market Breadth) 作為濾網
    def get_market_breadth(date_idx):
        if date_idx < 10: return 1.0
        target_date = all_dates[date_idx]
        above_ma = 0; total = 0
        for sid in data:
            prices = [data[sid]['price'][d]['close'] for d in all_dates[date_idx-10:date_idx+1] if d in data[sid]['price']]
            if len(prices) < 10: continue
            ma10 = sum(prices[:-1]) / 10
            if prices[-1] > ma10: above_ma += 1
            total += 1
        return above_ma / total if total > 0 else 1.0
    actual_buy_dates = {}
    if not is_daily:
        for bd in buy_dates_config:
            target = bd
            if target not in all_dates:
                available = [d for d in all_dates if d >= target]
                if available: target = available[0]
                else: continue
            actual_buy_dates[target] = bd

    if is_daily: start_idx_for_loop = 20
    else:
        if not actual_buy_dates: return None
        first_buy_target = min(actual_buy_dates.keys())
        start_idx_for_loop = all_dates.index(first_buy_target)
    
    for idx in range(start_idx_for_loop, len(all_dates)):
        current_date = all_dates[idx]
        date_key = current_date.replace('-', '')
        
        has_holdings = any(p['shares'] > 0 for p in portfolio.values())
        mom_scores = {}
        if has_holdings or is_daily or (current_date in actual_buy_dates):
            start_date_mom = all_dates[idx - 20] if idx >= 20 else all_dates[0]
            results = analyze_momentum.analyze_momentum(data, start_date_mom, current_date, weights=weights)
            mom_scores = {r['stock_id']: r['score'] for r in results}

        if has_holdings:
            sids = list(portfolio.keys())
            for sid in sids:
                pos = portfolio[sid]
                if pos['shares'] <= 0: continue
                if current_date not in data[sid]['price']: continue
                curr_price = data[sid]['price'][current_date]['close']
                if curr_price > pos.get('max_price', 0): pos['max_price'] = curr_price
                profit_ratio = (curr_price - pos['avg_price']) / pos['avg_price']
                drop_from_peak = (curr_price - pos['max_price']) / pos['max_price'] if pos.get('max_price', 0) > 0 else 0
                
                sell_reason = None
                is_full_exit = False
                if profit_ratio <= stop_loss_threshold:
                    sell_reason = f"停損 {profit_ratio:.1%}"; is_full_exit = True
                elif drop_from_peak <= trailing_stop_threshold:
                    sell_reason = f"移動停扣 {drop_from_peak:.1%}"; is_full_exit = True
                elif mom_scores.get(sid, 0) < momentum_exit_threshold:
                    sell_reason = f"動能減退 {mom_scores.get(sid, 0):.0f}"; is_full_exit = True

                if is_full_exit:
                    shares_to_sell = pos['shares']; rev = shares_to_sell * curr_price
                    s_fee = round(rev * 0.001425); s_tax = round(rev * 0.003); net_rev = rev - s_fee - s_tax; cash += net_rev
                    pos['realized_pl'] = pos.get('realized_pl', 0) + (curr_price - pos['avg_price']) * shares_to_sell - s_fee - s_tax
                    pos['total_sold_revenue'] = pos.get('total_sold_revenue', 0) + net_rev; pos['shares'] = 0
                    transactions.append({'date': current_date, 'stock_id': sid, 'side': 'S', 'shares': shares_to_sell, 'price': curr_price, 'revenue': net_rev})
                    if date_key not in json_history: json_history[date_key] = []
                    json_history[date_key].append({"stk_no": sid, "stk_na": pos['name'], "side": "S", "price_avg": float(curr_price), "qty": float(shares_to_sell), "amount": float(rev), "fee": float(s_fee + s_tax), "profit": float((curr_price - pos['avg_price']) * shares_to_sell)})
                    if not silent: print(f"  [全部出清] {current_date} {sid} {pos['name']} {sell_reason}")
                    continue

                if profit_ratio >= take_profit_half_threshold and not pos.get('half_sold', False):
                    shares_to_sell = pos['shares'] // 2
                    if shares_to_sell > 0:
                        rev = shares_to_sell * curr_price; s_fee = round(rev * 0.001425); s_tax = round(rev * 0.003)
                        net_rev = rev - s_fee - s_tax; cash += net_rev; pos['shares'] -= shares_to_sell
                        pos['realized_pl'] = pos.get('realized_pl', 0) + (curr_price - pos['avg_price']) * shares_to_sell - s_fee - s_tax
                        pos['total_sold_revenue'] = pos.get('total_sold_revenue', 0) + net_rev; pos['half_sold'] = True
                        transactions.append({'date': current_date, 'stock_id': sid, 'side': 'S', 'shares': shares_to_sell, 'price': curr_price, 'revenue': net_rev})
                        if date_key not in json_history: json_history[date_key] = []
                        json_history[date_key].append({"stk_no": sid, "stk_na": pos['name'], "side": "S", "price_avg": float(curr_price), "qty": float(shares_to_sell), "amount": float(rev), "fee": float(s_fee + s_tax), "profit": float((curr_price - pos['avg_price']) * shares_to_sell)})
                        if not silent: print(f"  [賣出一半] {current_date} {sid} {pos['name']} 獲利達標 {profit_ratio:.1%}")

        if is_daily or current_date in actual_buy_dates:
            if idx < 20: continue
            
            # 使用市場廣度作為過濾器 (Market Breadth Filter)
            breadth = get_market_breadth(idx)
            if breadth < 0.3: # 市場過於疲弱，不開新倉
                if not silent: print(f"  [SKIPPED] {current_date} Market Breadth too low: {breadth:.1%}")
                continue
                
            start_date_buy = all_dates[idx - 20]
            results_buy = analyze_momentum.analyze_momentum(data, start_date_buy, current_date)
            valid_results = [r for r in results_buy if r['stock_id'] in data and current_date in data[r['stock_id']]['price'] and r['score'] >= buy_score_threshold]
            top_stocks = valid_results[:top_n]
            num_to_buy = len(top_stocks)
            if num_to_buy > 0:
                # 根據市場廣度動態調整投資池
                effective_pool = daily_invest_pool * (1.2 if breadth > 0.7 else (0.5 if breadth < 0.5 else 1.0))
                target_allocations = calculate_allocations(num_to_buy, effective_pool, min_last_pos_ratio)
                if date_key not in json_history: json_history[date_key] = []
                for i, res in enumerate(top_stocks):
                    sid = res['stock_id']; price = res['close']; target_amount = target_allocations[i]
                    if cash <= 0: break
                    max_buyable = min(cash, target_amount); shares = max_buyable // price; actual_cost = shares * price
                    if shares > 0:
                        fee = round(actual_cost * 0.001425); cash -= (actual_cost + fee); running_invested_capital += (actual_cost + fee)
                        if sid not in portfolio:
                            portfolio[sid] = {'shares': 0, 'total_cost': 0, 'name': stock_names.get(sid, sid), 'buys': [], 'realized_pl': 0, 'total_sold_revenue': 0, 'max_price': price}
                        portfolio[sid]['shares'] += shares; portfolio[sid]['total_cost'] += (actual_cost + fee)
                        portfolio[sid]['avg_price'] = portfolio[sid]['total_cost'] / portfolio[sid]['shares']
                        portfolio[sid]['buys'].append({'date': current_date, 'price': price, 'shares': shares, 'cost': actual_cost + fee})
                        transactions.append({'date': current_date, 'stock_id': sid, 'side': 'B', 'shares': shares, 'price': price, 'cost': actual_cost + fee})
                        json_history[date_key].append({"stk_no": sid, "stk_na": portfolio[sid]['name'], "side": "B", "price_avg": float(price), "qty": float(shares), "amount": float(actual_cost), "fee": float(fee), "profit": 0.0})
                if json_history[date_key]: json_history[date_key][-1]["invested_capital_snapshot"] = float(running_invested_capital)

    # 5. 結算
    final_date = all_dates[-1]
    report_rows = []
    for sid, pos in portfolio.items():
        curr_price = data[sid]['price'][final_date]['close'] if final_date in data[sid]['price'] else (data[sid]['price'][max(data[sid]['price'].keys())]['close'] if data[sid]['price'] else 0)
        unrealized_pl = (curr_price - pos['avg_price']) * pos['shares']
        report_rows.append({"編號": sid, "公司": pos['name'], "總盈虧": pos['realized_pl'] + unrealized_pl, "購買金額": pos['total_cost']})
    
    total_pl = sum(r['總盈虧'] for r in report_rows)
    peak_invested = running_invested_capital if running_invested_capital > 0 else 1
    
    if not silent: print(f"\n[FINISH] {final_date} Total PL: {total_pl:,.0f}, ROI: {total_pl/peak_invested:.1%}")
    
    return {"total_pl": total_pl, "peak_invested": peak_invested, "roi": total_pl/peak_invested}

if __name__ == "__main__":
    run_backtest()
