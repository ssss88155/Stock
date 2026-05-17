import json
import os
import sys
import argparse
from datetime import datetime

# 將 lib 目錄加入 Python 路徑
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
from common_lib import Color, pad_string, truncate_string, load_stock_data, get_script_dir

# =================================================================
# 策略參數與權重設定 (您可以根據需求自行修改)
# =================================================================
# 1. 基本門檻與過濾
MIN_GAIN_REQUIRED = 0.00      # 至少要正報酬才顯示
MOMENTUM_DAYS = 4             # 幾天內...
MOMENTUM_THRESHOLD = 0.05     # ...漲幅超過幾% 會標記 !
MIN_TRADING_VALUE = 30000000  # 每日成交金額門檻 (預設3000萬)

# 2. 權重分配 (總和建議 100)
WEIGHT_GAIN = 10              # 當日/波段漲幅權重
WEIGHT_VOLUME = 15            # 交易量突破權重 (量比)
WEIGHT_FOREIGN = 30           # 外資挹注權重 (最高)
WEIGHT_SITC = 15              # 投信挹注權重 (降低)
WEIGHT_VCP = 20               # VCP 波動收斂權重 (新增)
WEIGHT_BREAKOUT = 10          # 壓力線突破權重

MIN_SCORE_TO_PRINT = 40       # 總分超過此值才印出 (因權重調整，提高門檻)

# 3. 各項機制變數
VOL_AVG_DAYS = 5
VOL_BREAKTHROUGH_RATIO = 2.0

SITC_AVG_DAYS = 10
SITC_MULTI_RATIO = 1.5
SITC_MIN_BUY_SHARES = 100000

FOREIGN_STREAK_DAYS = 3       # 連買幾天開始標記
DEALER_INFLOW_THRESHOLD = 500000

# 4. VCP 參數
VCP_LOOKBACK = 60             # 回顧天數
VCP_MIN_CONTRACTIONS = 2      # 至少要幾次收斂
# =================================================================

# --- 全域快取 ---
_SORTED_DATES_CACHE = {}
_INDUSTRY_DATA = None

def load_industry_data():
    """載入台灣股票產業資訊 (CSV)"""
    global _INDUSTRY_DATA
    if _INDUSTRY_DATA is not None:
        return _INDUSTRY_DATA
    
    path = os.path.join(get_script_dir(__file__), 'taiwan_stocks.csv')
    # 嘗試不同路徑
    if not os.path.exists(path):
        path = r"C:\jupyter_notebook\ai_twstock\taiwan_stocks.csv"
        
    industry_map = {}
    if os.path.exists(path):
        import csv
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    industry_map[row['code']] = row.get('industry', '未知')
        except Exception as e:
            print(f"[DEBUG] CSV Load Error: {e}")
    _INDUSTRY_DATA = industry_map
    return industry_map

def check_vcp_pattern(price_data, sorted_dates, idx):
    """
    VCP (Volatility Contraction Pattern) 簡易判斷
    檢查股價在回顧區間內，震幅是否逐漸收斂
    """
    if idx < VCP_LOOKBACK:
        return False, 0
        
    lookback_dates = sorted_dates[idx - VCP_LOOKBACK : idx + 1]
    prices = [price_data[d]['close'] for d in lookback_dates]
    
    # 找局部高低點來估算震幅收斂
    # 簡化算法：將區間切成三段，計算每段的震幅 (Max-Min)/Min
    segment_size = len(prices) // 3
    if segment_size < 5: return False, 0
    
    v1 = prices[:segment_size]
    v2 = prices[segment_size:segment_size*2]
    v3 = prices[segment_size*2:]
    
    def get_range(v):
        if not v or min(v) == 0: return 0
        return (max(v) - min(v)) / min(v)
    
    r1, r2, r3 = get_range(v1), get_range(v2), get_range(v3)
    
    # 判斷收斂：r1 > r2 > r3 (或者 r1, r2 都比 r3 大許多)
    is_tightening = r1 > r2 and r2 > r3
    
    # 收斂評分：r3 越小分數越高 (r3 < 5% 是理想狀態)
    tightness_score = max(0, 100 * (1 - (r3 / 0.15))) if r3 < 0.15 else 0
    
    return is_tightening or (r1 > r3 * 2), tightness_score

def check_institutional_consensus(inst_data, date):
    """
    檢查法人共識
    1. 同步買超 (Consensus) -> 加分
    2. 對幹 (Conflict) -> 減分
    """
    d = inst_data.get(date, {})
    f = d.get('Foreign_Investor', {})
    s = d.get('Investment_Trust', {})
    
    f_net = f.get('buy', 0) - f.get('sell', 0)
    s_net = s.get('buy', 0) - s.get('sell', 0)
    
    if f_net > 0 and s_net > 0:
        return "consensus", 1.2 # 加成係數
    if (f_net > 0 and s_net < 0) or (f_net < 0 and s_net > 0):
        # 如果對幹且金額大，標記衝突
        if abs(f_net) > 500000 and abs(s_net) > 500000:
            return "conflict", 0.5 # 減半係數
    return "neutral", 1.0

def load_stock_data_wrapper(filename='stock_data.json'):
    return load_stock_data(filename, __file__)

# --- 核心機制函數 ---

def check_volume_breakthrough(price_data, sorted_dates, idx):
    if idx < 1: return False, 0
    actual_lookback = min(idx, VOL_AVG_DAYS)
    current_vol = price_data[sorted_dates[idx]].get('Trading_Volume', 0)
    prev_vols = [price_data[sorted_dates[i]].get('Trading_Volume', 0) for i in range(idx - actual_lookback, idx)]
    avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0
    if avg_vol == 0: return False, 0
    ratio = current_vol / avg_vol
    return ratio >= VOL_BREAKTHROUGH_RATIO, ratio

def check_sitc_momentum(inst_data, sorted_dates, idx):
    if idx < 1: return False, 0
    actual_lookback = min(idx, SITC_AVG_DAYS)
    def get_net(i):
        d = inst_data.get(sorted_dates[i], {}).get('Investment_Trust', {})
        return d.get('buy', 0) - d.get('sell', 0)
    current_net = get_net(idx)
    if current_net < SITC_MIN_BUY_SHARES: return False, 0
    prev_nets = [abs(get_net(i)) for i in range(idx - actual_lookback, idx)]
    avg_net = sum(prev_nets) / len(prev_nets) if prev_nets else 0
    effective_avg = max(avg_net, SITC_MIN_BUY_SHARES / 2)
    ratio = current_net / effective_avg
    return ratio >= SITC_MULTI_RATIO, ratio

def check_price_streak(price_data, sorted_dates, idx):
    streak = 0
    for i in range(idx, 0, -1):
        cur = price_data[sorted_dates[i]]['close']
        prev = price_data[sorted_dates[i-1]]['close']
        if cur > prev: streak += 1
        else: break
    return streak

def check_foreign_streak(inst_data, sorted_dates, idx):
    streak = 0
    for i in range(idx, -1, -1):
        d = inst_data.get(sorted_dates[i], {}).get('Foreign_Investor', {})
        if (d.get('buy', 0) - d.get('sell', 0)) > 0: streak += 1
        else: break
    return streak >= FOREIGN_STREAK_DAYS, streak

def check_dealer_inflow(inst_data, sorted_dates, idx):
    d = inst_data.get(sorted_dates[idx], {}).get('Dealer_self', {})
    net = d.get('buy', 0) - d.get('sell', 0)
    return net >= DEALER_INFLOW_THRESHOLD, net

def check_resistance_breakout(price_data, sorted_dates, idx):
    if idx < 1: return False, 0
    RESISTANCE_LOOKBACK = 180
    actual_lookback = min(idx, RESISTANCE_LOOKBACK)
    current_close = price_data[sorted_dates[idx]]['close']
    lookback_prices = [price_data[sorted_dates[i]]['max'] for i in range(idx - actual_lookback, idx)]
    resistance = max(lookback_prices) if lookback_prices else 0
    is_breakout = current_close >= resistance and resistance > 0
    return is_breakout, resistance

def calculate_score(details):
    score = 0
    # 1. 漲幅評分
    score += (min(100, (details['gain'] / 0.05) * 100) if details['gain'] > 0 else 0) * WEIGHT_GAIN / 100
    
    # 2. 交易量突破評分
    score += (min(100, (details['vol_ratio'] / VOL_BREAKTHROUGH_RATIO) * 100)) * WEIGHT_VOLUME / 100
    
    # 3. 外資評分 (依連買天數與佔比)
    foreign_score = min(100, details['foreign_days'] * 20)
    score += foreign_score * WEIGHT_FOREIGN / 100
    
    # 4. 投信評分
    score += (min(100, (details['sitc_ratio'] / 1.5) * 100)) * WEIGHT_SITC / 100
    
    # 5. VCP 形態評分
    score += (details['vcp_score'] if details['vcp_ok'] else 0) * WEIGHT_VCP / 100
    
    # 6. 壓力突破評分
    if details['breakout_ok']: 
        score += WEIGHT_BREAKOUT
        
    # 法人共識乘數
    score *= details['inst_multiplier']
    
    return score

# --- 主分析函數 ---

def analyze_momentum(data, start_date, end_date):
    results = []
    industry_map = load_industry_data()
    
    for stock_id, details in data.items():
        price_data = details.get('price', {})
        inst_data = details.get('institutional', {})
        
        if start_date not in price_data or end_date not in price_data:
            continue
            
        # 0. 流動性濾網 (成交金額 = 股價 * 成交量)
        current_price = price_data[end_date]['close']
        current_vol = price_data[end_date].get('Trading_Volume', 0)
        trading_value = current_price * current_vol
        if trading_value < MIN_TRADING_VALUE:
            continue

        start_close = price_data[start_date]['close']
        if not start_close: continue
        gain = (current_price - start_close) / start_close
        if gain < MIN_GAIN_REQUIRED: continue
            
        if stock_id in _SORTED_DATES_CACHE:
            sorted_dates = _SORTED_DATES_CACHE[stock_id]
        else:
            sorted_dates = sorted(price_data.keys())
            _SORTED_DATES_CACHE[stock_id] = sorted_dates
            
        idx = sorted_dates.index(end_date)
        
        # 核心技術與籌碼檢查
        vol_ok, vol_ratio = check_volume_breakthrough(price_data, sorted_dates, idx)
        sitc_ok, sitc_ratio = check_sitc_momentum(inst_data, sorted_dates, idx)
        foreign_ok, foreign_days = check_foreign_streak(inst_data, sorted_dates, idx)
        vcp_ok, vcp_score = check_vcp_pattern(price_data, sorted_dates, idx)
        breakout_ok, res_level = check_resistance_breakout(price_data, sorted_dates, idx)
        
        # 法人共識/衝突檢查
        inst_status, inst_multiplier = check_institutional_consensus(inst_data, end_date)
        
        res = {
            'stock_id': stock_id, 
            'name': details.get('name', ''),
            'industry': industry_map.get(stock_id, '其他'),
            'close': current_price, 
            'gain': gain, 
            'vol_ratio': vol_ratio,
            'sitc_ratio': sitc_ratio, 
            'foreign_days': foreign_days,
            'vcp_ok': vcp_ok,
            'vcp_score': vcp_score,
            'breakout_ok': breakout_ok,
            'inst_multiplier': inst_multiplier,
            'inst_status': inst_status,
            'raw_volume': current_vol,
            'trading_value': trading_value,
            'resistance': res_level
        }
        res['score'] = calculate_score(res)
        
        if res['score'] >= MIN_SCORE_TO_PRINT:
            results.append(res)
                
    results.sort(key=lambda x: (x['score'], x['gain']), reverse=True)
    return results

def main():
    parser = argparse.ArgumentParser(description='Analyze Taiwan stock momentum.')
    parser.add_argument('filename', nargs='?', default='stock_data.json', help='The JSON file to analyze (default: stock_data.json)')
    args = parser.parse_args()

    data = load_stock_data_wrapper(args.filename)
    if not data:
        print(f"[DEBUG] No data loaded from {args.filename}.")
        return
    
    print(f"[DEBUG] Loaded data for {len(data)} stocks.")
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    if len(all_dates) < 2:
        print(f"[DEBUG] Not enough dates found. Count: {len(all_dates)}. Dates: {all_dates}")
        return
    
    end_date = all_dates[-1]
    start_date = all_dates[-20]
    print(f"[DEBUG] Analyzing from {start_date} to {end_date}")
    
    print(f"\n--- 綜合加權評分動能報告 ({end_date}) ---")
    print(f"資料來源：{args.filename}")
    print(f"篩選門檻：總分 > {MIN_SCORE_TO_PRINT}, 流動性 > {MIN_TRADING_VALUE/10000:,.0f}萬")
    print(f"權重分配：外資{WEIGHT_FOREIGN}%, VCP{WEIGHT_VCP}%, 投信{WEIGHT_SITC}%, 量比{WEIGHT_VOLUME}%, 突破{WEIGHT_BREAKOUT}%, 漲幅{WEIGHT_GAIN}%")
    
    # 欄位寬度設定 (中文字佔 2 單位)
    headers = ["代號", "產業", "現價", "總分", "漲幅", "量比", "外資", "投信", "備註"]
    widths = [8, 12, 8, 6, 8, 6, 6, 6, 30]
    
    separator = "-" * (sum(widths) + len(widths) * 3)
    print(separator)
    
    # 列印表頭
    header_line = " | ".join(pad_string(h, w) for h, w in zip(headers, widths))
    print(header_line)
    print(separator)
    
    results = analyze_momentum(data, start_date, end_date)
    
    # 族群統計
    industry_count = {}
    
    # 先跑一圈統計強勢族群
    for res in results:
        ind = res['industry']
        industry_count[ind] = industry_count.get(ind, 0) + 1
        
    # 取得前二高產業
    sorted_industries = sorted(industry_count.items(), key=lambda x: x[1], reverse=True)
    top1_industry = sorted_industries[0][0] if len(sorted_industries) > 0 else None
    top2_industry = sorted_industries[1][0] if len(sorted_industries) > 1 else None

    for res in results:
        ind = res['industry']
        # 產業字數處理：先截斷，再補齊到固定長度 12
        display_industry = pad_string(truncate_string(ind, 12), 12)
        
        # 根據排名上色 (注意：上色要在 pad_string 之後，否則會影響寬度計算)
        if ind == top1_industry:
            display_industry = Color.wrap(display_industry, Color.RED)
        elif ind == top2_industry:
            display_industry = Color.wrap(display_industry, Color.ORANGE)
        
        note = ""
        if res['inst_status'] == "consensus": note += "法人共識 "
        if res['inst_status'] == "conflict": note += "法人對幹 "
        if res['vcp_ok']: note += "VCP收斂 "
        if res['breakout_ok']: note += "突破壓力 "
        
        # 建立每一列的資料項
        # 注意：industry 已經處理過 padding 與 color，所以 items 中直接使用，後續不再對其 pad_string
        line_items = [
            pad_string(res['stock_id'], 8),
            display_industry,
            pad_string(f"{res['close']:.2f}", 8),
            pad_string(f"{res['score']:.0f}", 6),
            pad_string(f"{res['gain']:.1%}", 8),
            pad_string(f"{res['vol_ratio']:.1f}", 6),
            pad_string(f"{res['foreign_days']}天", 6),
            pad_string(f"{res['sitc_ratio']:.1f}", 6),
            pad_string(note, 30)
        ]
        print(" | ".join(line_items))

    # 列印族群統計
    if industry_count:
        print(f"\n--- 強勢族群統計 ---")
        for ind, count in sorted_industries[:5]: # 只印前五名
            if count >= 2:
                msg = f"{ind}: {count} 檔符合條件"
                if ind == top1_industry:
                    print(Color.wrap(msg, Color.RED))
                elif ind == top2_industry:
                    print(Color.wrap(msg, Color.ORANGE))
                else:
                    print(msg)

if __name__ == "__main__":
    main()
