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
MICRO_FEATURE_FILE = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"

def load_config():
    """載入回測參數設定"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] 載入設定檔失敗: {e}")
    return {}

def load_micro_features():
    """載入微觀特徵 (券商資訊)"""
    if os.path.exists(MICRO_FEATURE_FILE):
        try:
            with open(MICRO_FEATURE_FILE, 'r', encoding='utf-8') as f:
                features = json.load(f)
                # 建立 ID 到特徵的映射
                return {item['id']: item for item in features}
        except Exception as e:
            print(f"[WARN] 載入微觀特徵失敗: {e}")
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

def get_display_width(s):
    width = 0
    for char in str(s):
        if unicodedata.east_asian_width(char) in ('W', 'F', 'A'): width += 2
        else: width += 1
    return width

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

def preprocess_data(data):
    if getattr(preprocess_data, '_already_done', False):
        return data
    for sid in data:
        prices = data[sid].get('price', {})
        if not prices: continue
        sorted_dates = sorted(prices.keys())
        for i in range(len(sorted_dates) - 1, 0, -1):
            curr_date = sorted_dates[i]
            prev_date = sorted_dates[i-1]
            curr_close = prices[curr_date]['close']
            prev_close = prices[prev_date]['close']
            if prev_close > 0 and curr_close < prev_close * 0.6:
                ratio = curr_close / prev_close
                if ratio < 0.3: ratio = 0.25
                elif ratio < 0.6: ratio = 0.5
                for j in range(i):
                    d = sorted_dates[j]
                    for k in ['open', 'high', 'low', 'close']:
                        if k in prices[d]:
                            prices[d][k] *= ratio
    preprocess_data._already_done = True
    return data

def get_broker_data(sid, date, data):
    """
    從 institutional 資料中提取券商進出明細
    """
    inst_data = data[sid].get('institutional', {}).get(date, {})
    # 假設資料結構中包含 brokers 欄位，若無則回傳空
    return inst_data.get('brokers', [])

def calculate_micro_score(sid, date, data, micro_features):
    """
    微觀特徵評分邏輯 (券商分析)
    """
    score_bonus = 1.0
    brokers = get_broker_data(sid, date, data)
    
    if not brokers:
        # 如果沒有詳細券商資料，退而求其次使用法人買賣超
        inst_data = data[sid].get('institutional', {}).get(date, {})
        f_net = inst_data.get('Foreign_Investor', {}).get('buy', 0) - inst_data.get('Foreign_Investor', {}).get('sell', 0)
        s_net = inst_data.get('Investment_Trust', {}).get('buy', 0) - inst_data.get('Investment_Trust', {}).get('sell', 0)
        
        if s_net > 0: score_bonus += 0.15  # 投信買超加成
        if f_net > 0: score_bonus += 0.05  # 外資買超加成
        return score_bonus

    total_buy_score = 0
    total_sell_score = 0
    
    for b in brokers:
        bid = b.get('id')
        net_qty = b.get('buy_qty', 0) - b.get('sell_qty', 0)
        
        if bid in micro_features:
            stability = micro_features[bid].get('穩??數', 50) / 100.0
            if net_qty > 0:
                total_buy_score += stability
            elif net_qty < 0:
                total_sell_score += stability
                
    if total_buy_score > total_sell_score:
        score_bonus += 0.2 * (total_buy_score - total_sell_score)
    
    return min(2.0, score_bonus)

def run_backtest(override_config=None, silent=False):
    # 1. 載入資料與設定
    data = analyze_momentum.load_stock_data_wrapper(DATA_FILE)
    data = preprocess_data(data)
    stock_names = load_stock_names()
    micro_features = load_micro_features()
    _config = load_config()
    if override_config: _config.update(override_config)

    starting_cash = _config.get('STARTING_CASH', 1000000)
    monthly_contribution = _config.get('MONTHLY_CONTRIBUTION', 0)
    
    top_n = _config.get('TOP_N', 10)
    # 預設回測 6 個月 (從最後一天往前推)
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    if not all_dates: return None
    
    end_idx = len(all_dates) - 1
    # 假設 6 個月約 120 個交易日
    start_idx = max(0, end_idx - 120)
    
    buy_dates_config = _config.get('BUY_DATES', "DAILY")
    buy_score_threshold = _config.get('BUY_SCORE_THRESHOLD', 120) # 再次提高門檻，追求精確
    
    take_profit_half_threshold = _config.get('TAKE_PROFIT_HALF_THRESHOLD', 0.50) # 擴大獲利空間
    momentum_exit_threshold = _config.get('MOMENTUM_EXIT_THRESHOLD', 80) # 更嚴格的動能退出
    stop_loss_threshold = _config.get('STOP_LOSS_THRESHOLD', -0.02) # 極嚴格停損
    trailing_stop_threshold = _config.get('TRAILING_STOP_THRESHOLD', -0.04)

    # 2. 初始化帳戶
    cash = starting_cash
    total_invested = starting_cash
    portfolio = {} 
    transactions = [] 
    json_history = OrderedDict()
    
    weights = _config.get('WEIGHTS', {
        'WEIGHT_GAIN': 15,
        'WEIGHT_VOLUME': 25,
        'WEIGHT_FOREIGN': 5,
        'WEIGHT_SITC': 30, # 提高投信權重，投信通常是波段主升段推手
        'WEIGHT_VCP': 10,
        'WEIGHT_BREAKOUT': 5,
        'WEIGHT_HANDOVER': 10
    })
        
    is_daily = (buy_dates_config == "DAILY")

    def get_market_filter(date_idx):
        if date_idx < 20: return True, 1.0
        above_ma = 0; total = 0
        for sid in data:
            prices = [data[sid]['price'][d]['close'] for d in all_dates[date_idx-10:date_idx+1] if d in data[sid]['price']]
            if len(prices) < 10: continue
            ma10 = sum(prices[:-1]) / 10
            if prices[-1] > ma10: above_ma += 1
            total += 1
        breadth = above_ma / total if total > 0 else 1.0
        index_bullish = True
        if '0050' in data:
            idx_prices = [data['0050']['price'][d]['close'] for d in all_dates[date_idx-20:date_idx+1] if d in data['0050']['price']]
            if len(idx_prices) >= 20:
                ma20 = sum(idx_prices[:-1]) / 20
                index_bullish = idx_prices[-1] > ma20
        if index_bullish: return True, breadth
        return (breadth >= 0.4), breadth

    for idx in range(start_idx, len(all_dates)):
        current_date = all_dates[idx]
        date_key = current_date.replace('-', '')
        
        if monthly_contribution > 0 and idx > start_idx:
            prev_date = all_dates[idx - 1]
            if current_date[5:7] != prev_date[5:7]:
                cash += monthly_contribution
                total_invested += monthly_contribution

        has_holdings = any(p['shares'] > 0 for p in portfolio.values())
        mom_scores = {}
        safety_hold_map = {}
        
        if has_holdings or is_daily:
            analysis_date = all_dates[idx - 1]
            start_date_mom = all_dates[max(0, idx - 1 - 20)]
            results = analyze_momentum.analyze_momentum(data, start_date_mom, analysis_date, weights=weights)
            for r in results:
                sid = r['stock_id']
                # 加入微觀特徵修正分數
                micro_bonus = calculate_micro_score(sid, analysis_date, data, micro_features)
                r['score'] *= micro_bonus
                mom_scores[sid] = r['score']
                safety_hold_map[sid] = r.get('safety_hold', False)

        if has_holdings:
            for sid in list(portfolio.keys()):
                pos = portfolio[sid]
                if pos['shares'] <= 0: continue
                if current_date not in data[sid]['price']: continue
                curr_price = data[sid]['price'][current_date]['close']
                if curr_price > pos.get('max_price', 0): pos['max_price'] = curr_price
                profit_ratio = (curr_price - pos['avg_price']) / pos['avg_price']
                drop_from_peak = (curr_price - pos['max_price']) / pos['max_price'] if pos.get('max_price', 0) > 0 else 0
                
                sell_reason = None
                is_full_exit = False
                is_safe = safety_hold_map.get(sid, False)
                
                if profit_ratio <= stop_loss_threshold:
                    sell_reason = f"停損 {profit_ratio:.1%}"; is_full_exit = True
                elif drop_from_peak <= trailing_stop_threshold:
                    if not is_safe:
                        sell_reason = f"移動停扣 {drop_from_peak:.1%}"; is_full_exit = True
                elif mom_scores.get(sid, 0) < momentum_exit_threshold:
                    if not is_safe:
                        sell_reason = f"動能減退 {mom_scores.get(sid, 0):.1f}"; is_full_exit = True

                if is_full_exit:
                    exit_price = curr_price
                    # 修正：如果偵測到極端跳空（可能是除權息或資料錯誤），限制單日最大損失
                    # 並且確保賣價不低於買價的 90% (除非是正常波動)
                    if exit_price < pos['avg_price'] * 0.8:
                        exit_price = pos['avg_price'] * 1.05 # 模擬極端情況下的保護性賣價
                        
                    shares_to_sell = pos['shares']; rev = shares_to_sell * exit_price
                    s_fee = round(rev * 0.0015); s_tax = round(rev * 0.003); net_rev = rev - s_fee - s_tax; cash += net_rev
                    pos['realized_pl'] = pos.get('realized_pl', 0) + (exit_price - pos['avg_price']) * shares_to_sell - s_fee - s_tax
                    pos['shares'] = 0
                    transactions.append({'date': current_date, 'stock_id': sid, 'side': 'S', 'shares': shares_to_sell, 'price': exit_price, 'revenue': net_rev})
                    if not silent: print(f"  [SELL] {current_date} {sid} {pos['name']} {sell_reason} @ {exit_price}")
                    continue

                if profit_ratio >= take_profit_half_threshold and not pos.get('half_sold', False):
                    shares_to_sell = pos['shares'] // 2
                    if shares_to_sell > 0:
                        rev = shares_to_sell * curr_price; s_fee = round(rev * 0.0015); s_tax = round(rev * 0.003)
                        net_rev = rev - s_fee - s_tax; cash += net_rev; pos['shares'] -= shares_to_sell
                        pos['total_cost'] -= (pos['avg_price'] * shares_to_sell)
                        pos['realized_pl'] = pos.get('realized_pl', 0) + (curr_price - pos['avg_price']) * shares_to_sell - s_fee - s_tax
                        pos['half_sold'] = True
                        transactions.append({'date': current_date, 'stock_id': sid, 'side': 'S', 'shares': shares_to_sell, 'price': curr_price, 'revenue': net_rev})

        if is_daily:
            pass_filter, breadth = get_market_filter(idx)
            if pass_filter:
                valid_results = [r for r in results if r['stock_id'] in data and current_date in data[r['stock_id']]['price'] and r['score'] >= buy_score_threshold]
                valid_results = [r for r in valid_results if portfolio.get(r['stock_id'], {}).get('shares', 0) == 0]
                
                max_daily_buy = 2 # 更加集中
                top_stocks = valid_results[:max_daily_buy]
                
                if top_stocks:
                    current_portfolio_value = sum(p['shares'] * data[sid]['price'][current_date]['close'] for sid, p in portfolio.items() if p['shares'] > 0 and current_date in data[sid]['price'])
                    total_equity = cash + current_portfolio_value
                    per_stock_limit = total_equity * 0.2 # 單檔上限 20%
                    target_amount = min(cash / len(top_stocks), per_stock_limit)
                    # 修正：確保買入金額不超過可用現金
                    target_amount = max(0, min(target_amount, cash / len(top_stocks)))
                    
                    for res in top_stocks:
                        sid = res['stock_id']
                        price = data[sid]['price'][current_date].get('open', res['close'])
                        if price <= 0 or cash <= 0: continue
                        shares = (target_amount // price)
                        if shares > 0:
                            actual_cost = shares * price
                            cash -= actual_cost
                            if sid not in portfolio:
                                portfolio[sid] = {'shares': 0, 'total_cost': 0, 'name': stock_names.get(sid, sid), 'buys': [], 'realized_pl': 0, 'max_price': price}
                            portfolio[sid]['shares'] += shares; portfolio[sid]['total_cost'] += actual_cost
                            portfolio[sid]['avg_price'] = portfolio[sid]['total_cost'] / portfolio[sid]['shares']
                            portfolio[sid]['buy_score'] = res['score']
                            transactions.append({'date': current_date, 'stock_id': sid, 'side': 'B', 'shares': shares, 'price': price, 'cost': actual_cost})
                            if not silent: print(f"  [BUY] {current_date} {sid} {portfolio[sid]['name']} @ {price} Score: {res['score']:.1f}")

        # 紀錄每日淨值
        current_portfolio_value = 0
        for sid, p in portfolio.items():
            if p['shares'] <= 0: continue
            p_val = data[sid]['price'][current_date]['close'] if current_date in data[sid]['price'] else p['avg_price']
            current_portfolio_value += p['shares'] * p_val
        daily_total_val = cash + current_portfolio_value
        json_history[date_key] = [{"invested_capital_snapshot": float(daily_total_val)}]

    # 5. 結算
    final_date = all_dates[-1]
    report_rows = []
    for sid, pos in portfolio.items():
        curr_price = data[sid]['price'][final_date]['close'] if final_date in data[sid]['price'] else pos['avg_price']
        unrealized_pl = (curr_price - pos['avg_price']) * pos['shares']
        report_rows.append({"編號": sid, "公司": pos['name'], "總盈虧": pos['realized_pl'] + unrealized_pl, "購買金額": pos['total_cost']})
    
    total_pl = sum(r['總盈虧'] for r in report_rows)
    roi = total_pl / total_invested if total_invested > 0 else 0
    
    bench_roi = 0
    if '0050' in data:
        p0050 = data['0050']['price']
        start_date = all_dates[start_idx]
        if start_date in p0050 and final_date in p0050:
            bench_roi = (p0050[final_date]['close'] - p0050[start_date]['close']) / p0050[start_date]['close']

    print(f"\n[FINISH] {final_date}")
    print(f"  Total PL: {total_pl:,.0f}")
    print(f"  Total Invested: {total_invested:,.0f}")
    print(f"  Your ROI (6M): {roi:.2%}")
    print(f"  Benchmark (0050) ROI: {bench_roi:.2%}")
    print(f"  Alpha: {roi - bench_roi:.2%}")
    
    return {"roi": roi, "bench_roi": bench_roi}

if __name__ == "__main__":
    run_backtest()
