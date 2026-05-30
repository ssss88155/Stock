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
MOMENTUM_DAYS = 20             # 延長動能觀察期，捕捉波段主升段
MOMENTUM_THRESHOLD = 0.10     # 提高門檻，漲幅超過 10% 會標記
MIN_TRADING_VALUE = 30000000  # 每日成交金額門檻 (預設3000萬)

# 2. 權重分配 (總和建議 100)
WEIGHT_GAIN = 40              # 恢復部分漲幅權重，捕捉轉強動能
WEIGHT_VOLUME = 10            # 交易量突破權重
WEIGHT_FOREIGN = 10           # 外資挹注權重
WEIGHT_SITC = 10              # 投信挹注權重
WEIGHT_VCP = 10               # VCP 波動收斂權重
WEIGHT_BREAKOUT = 10          # 提高壓力線突破權重
WEIGHT_HANDOVER = 40          # 加大換手盤整權重

MIN_SCORE_TO_PRINT = 60       # 提高門檻，只看最強勢標的

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

# 5. 換手盤整參數
CONSOLIDATION_DAYS = 10       # 盤整期間縮短，更靈敏
CONSOLIDATION_RANGE = 0.15    # 盤整區間稍微放大 (15% 以內)
HANDOVER_VOL_RATIO = 0.8      # 盤整期間成交量維持 80% 均量即可
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
    
    # 新增：量縮檢查 (Volume Dry-up)
    # 最後一段的平均成交量應小於前兩段
    vols1 = [price_data[d].get('Trading_Volume', 0) for d in lookback_dates[:segment_size]]
    vols3 = [price_data[d].get('Trading_Volume', 0) for d in lookback_dates[segment_size*2:]]
    if vols1 and vols3:
        avg_v1 = sum(vols1) / len(vols1)
        avg_v3 = sum(vols3) / len(vols3)
        if avg_v3 < avg_v1 * 0.8: # 量縮 20% 以上
            tightness_score += 20
    
    return is_tightening or (r1 > r3 * 2), min(100, tightness_score)

def check_handover_consolidation(price_data, sorted_dates, idx):
    """
    換手盤整判斷：
    1. 價格在一段時間內波動極小 (盤整)
    2. 成交量維持一定水準，沒有明顯縮量 (換手)
    """
    if idx < CONSOLIDATION_DAYS + 20:
        return False, 0
        
    lookback_dates = sorted_dates[idx - CONSOLIDATION_DAYS : idx + 1]
    prices = [price_data[d]['close'] for d in lookback_dates]
    vols = [price_data[d].get('Trading_Volume', 0) for d in lookback_dates]
    
    # 盤整區間判斷
    max_p, min_p = max(prices), min(prices)
    price_range = (max_p - min_p) / min_p if min_p > 0 else 1.0
    is_consolidating = price_range <= CONSOLIDATION_RANGE
    
    # 換手判斷 (成交量相對於更長期的均量)
    long_vols = [price_data[sorted_dates[i]].get('Trading_Volume', 0) for i in range(idx - CONSOLIDATION_DAYS - 20, idx - CONSOLIDATION_DAYS)]
    avg_long_vol = sum(long_vols) / len(long_vols) if long_vols else 1
    avg_recent_vol = sum(vols) / len(vols) if vols else 0
    vol_ratio = avg_recent_vol / avg_long_vol if avg_long_vol > 0 else 0
    
    # 換手評分：區間越窄且量能維持越好，分數越高
    handover_score = 0
    if is_consolidating:
        # 價格越平穩分數越高 (最多 50 分)
        handover_score += max(0, (1 - (price_range / CONSOLIDATION_RANGE)) * 50)
        # 量能維持越好分數越高 (最多 50 分)
        handover_score += min(50, (vol_ratio / HANDOVER_VOL_RATIO) * 50)
        
    return is_consolidating and vol_ratio >= 0.7, handover_score

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
        return "consensus", 1.5 # 同步買超加成提高到 1.5x
    if (f_net > 0 and s_net < 0) or (f_net < 0 and s_net > 0):
        # 如果對幹且金額大，標記衝突
        if abs(f_net) > 500000 and abs(s_net) > 500000:
            return "conflict", 0.7 # 衝突減損稍微放寬 0.5 -> 0.7
    return "neutral", 1.0

def load_stock_data_wrapper(filename='stock_data.json'):
    return load_stock_data(filename, __file__)

# --- 技術指標計算 ---

def calculate_ema(prices, periods):
    """計算指數移動平均線 (EMA)"""
    if len(prices) < periods:
        return prices[-1] if prices else 0
    
    alpha = 2 / (periods + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * alpha + ema * (1 - alpha)
    return ema

def calculate_macd(price_data, sorted_dates, idx):
    """
    計算 MACD 指標 (12, 26, 9)
    回傳: DIF, MACD_Signal, Histogram (OSC)
    """
    # 至少需要 26+9 = 35 天的數據來計算相對穩定的 MACD
    LOOKBACK = 60
    if idx < LOOKBACK:
        return 0, 0, 0
    
    lookback_dates = sorted_dates[idx - LOOKBACK : idx + 1]
    prices = [price_data[d]['close'] for d in lookback_dates]
    
    # 1. 計算 DIF (EMA12 - EMA26)
    # 為了計算 Signal Line (EMA9 of DIF)，我們需要一段時間的 DIF
    dif_history = []
    for i in range(26, len(prices) + 1):
        window = prices[:i]
        ema12 = calculate_ema(window, 12)
        ema26 = calculate_ema(window, 26)
        dif_history.append(ema12 - ema26)
    
    if len(dif_history) < 9:
        return dif_history[-1], 0, dif_history[-1], 0, 0, 0
    
    # 2. 計算 MACD Signal (EMA9 of DIF)
    macd_signal = calculate_ema(dif_history, 9)
    
    # 3. 計算 Histogram (OSC)
    dif = dif_history[-1]
    osc = dif - macd_signal
    
    # 為了判斷趨勢，我們也需要「昨日」的資料
    prev_dif = dif_history[-2]
    # 計算昨日的 Signal Line
    prev_macd_signal = calculate_ema(dif_history[:-1], 9)
    prev_osc = prev_dif - prev_macd_signal
    
    return dif, macd_signal, osc, prev_dif, prev_macd_signal, prev_osc

# --- 核心機制函數 ---

# [Upgrade] 連續帶量機制：過濾單日誘多雜訊，要求今日量比>2.0且昨日量比>1.2
def check_volume_breakthrough(price_data, sorted_dates, idx):
    if idx < 2: return False, 0
    actual_lookback = min(idx, VOL_AVG_DAYS)
    
    current_vol = price_data[sorted_dates[idx]].get('Trading_Volume', 0)
    prev_vol = price_data[sorted_dates[idx-1]].get('Trading_Volume', 0)
    
    lookback_vols = [price_data[sorted_dates[i]].get('Trading_Volume', 0) for i in range(idx - actual_lookback - 1, idx - 1)]
    avg_vol = sum(lookback_vols) / len(lookback_vols) if lookback_vols else 0
    if avg_vol == 0: return False, 0
    
    ratio = current_vol / avg_vol
    prev_ratio = prev_vol / avg_vol
    
    # 修改：要求連續兩天帶量，確保動能具備連續性
    is_breakthrough = (ratio >= VOL_BREAKTHROUGH_RATIO) and (prev_ratio >= 1.2)
    return is_breakthrough, ratio

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

def calculate_score(details, weights=None):
    # 如果沒傳入權重，使用全域預設值
    w_gain = weights.get('WEIGHT_GAIN', WEIGHT_GAIN) if weights else WEIGHT_GAIN
    w_vol = weights.get('WEIGHT_VOLUME', WEIGHT_VOLUME) if weights else WEIGHT_VOLUME
    w_foreign = weights.get('WEIGHT_FOREIGN', WEIGHT_FOREIGN) if weights else WEIGHT_FOREIGN
    w_sitc = weights.get('WEIGHT_SITC', WEIGHT_SITC) if weights else WEIGHT_SITC
    w_vcp = weights.get('WEIGHT_VCP', WEIGHT_VCP) if weights else WEIGHT_VCP
    w_breakout = weights.get('WEIGHT_BREAKOUT', WEIGHT_BREAKOUT) if weights else WEIGHT_BREAKOUT
    w_handover = weights.get('WEIGHT_HANDOVER', WEIGHT_HANDOVER) if weights else WEIGHT_HANDOVER

    score = 0
    # 1. 漲幅評分
    score += (min(100, (details['gain'] / 0.05) * 100) if details['gain'] > 0 else 0) * w_gain / 100
    
    # 2. 交易量突破評分
    score += (min(100, (details['vol_ratio'] / VOL_BREAKTHROUGH_RATIO) * 100)) * w_vol / 100
    
    # 3. 外資評分 (依連買天數與佔比)
    foreign_score = min(100, details['foreign_days'] * 20)
    score += foreign_score * w_foreign / 100
    
    # 4. 投信評分
    score += (min(100, (details['sitc_ratio'] / 1.5) * 100)) * w_sitc / 100
    
    # 5. VCP 形態評分
    score += (details['vcp_score'] if details['vcp_ok'] else 0) * w_vcp / 100
    
    # 6. 換手盤整評分 (新)
    score += (details['handover_score'] if details['handover_ok'] else 0) * w_handover / 100
    
    # 7. 壓力突破評分
    if details['breakout_ok']: 
        score += w_breakout
        
    # 法人共識乘數
    score *= details['inst_multiplier']
    
    return score

# --- 主分析函數 ---

def analyze_momentum(data, start_date, end_date, weights=None):
    results = []
    industry_map = load_industry_data()
    
    min_score = weights.get('MIN_SCORE_TO_PRINT', MIN_SCORE_TO_PRINT) if weights else MIN_SCORE_TO_PRINT

    # 計算大盤 (0050) 同期漲幅作為基準
    market_gain = 0
    if '0050' in data:
        p0050 = data['0050'].get('price', {})
        if start_date in p0050 and end_date in p0050:
            market_gain = (p0050[end_date]['close'] - p0050[start_date]['close']) / p0050[start_date]['close']

    # 第一輪：計算原始分數
    min_trading_val = weights.get('MIN_TRADING_VALUE', MIN_TRADING_VALUE) if weights else MIN_TRADING_VALUE
    
    for stock_id, details in data.items():
        if stock_id == '0050': continue # 跳過大盤本身
        price_data = details.get('price', {})
        inst_data = details.get('institutional', {})
        if start_date not in price_data or end_date not in price_data: continue
        current_price = price_data[end_date]['close']
        current_vol = price_data[end_date].get('Trading_Volume', 0)
        trading_value = current_price * current_vol
        if trading_value < min_trading_val: continue
        
        start_close = price_data[start_date]['close']
        if not start_close: continue
        gain = (current_price - start_close) / start_close
        if gain < MIN_GAIN_REQUIRED: continue
        
        # 新增：過熱過濾 (Overextended)
        # 如果漲幅已經過大 (例如 20 天漲超過 40%)，則不建議買入，除非是換手盤整
        is_overextended = gain > 0.40
        
        if stock_id in _SORTED_DATES_CACHE: sorted_dates = _SORTED_DATES_CACHE[stock_id]
        else:
            sorted_dates = sorted(price_data.keys())
            _SORTED_DATES_CACHE[stock_id] = sorted_dates
        idx = sorted_dates.index(end_date)
        vol_ok, vol_ratio = check_volume_breakthrough(price_data, sorted_dates, idx)
        sitc_ok, sitc_ratio = check_sitc_momentum(inst_data, sorted_dates, idx)
        foreign_ok, foreign_days = check_foreign_streak(inst_data, sorted_dates, idx)
        vcp_ok, vcp_score = check_vcp_pattern(price_data, sorted_dates, idx)
        handover_ok, handover_score = check_handover_consolidation(price_data, sorted_dates, idx)
        breakout_ok, res_level = check_resistance_breakout(price_data, sorted_dates, idx)
        inst_status, inst_multiplier = check_institutional_consensus(inst_data, end_date)
        
        # [Upgrade] 593%演算法升級 (第二門檻)並減少亂買：MACD 與量能持有的依據
        dif, macd_sig, osc, prev_dif, prev_macd_sig, prev_osc = calculate_macd(price_data, sorted_dates, idx)
        
        # 條件 1: 綠柱(負值)準備要回到0、看起來要到正的時候 (柱狀體大於昨日)
        osc_improving = (osc > prev_osc)
        # 條件 2: DIF 準備要往上 和 MACD線交叉 (準備黃金交叉或已交叉)
        macd_golden_cross = (dif > macd_sig) or (dif > prev_dif and (macd_sig - dif) < abs(dif * 0.05))
        # 條件 3: 成交量沒有明顯萎縮 (維持在 5 日均量的 80% 以上)
        vol_stable = False
        if idx >= 5:
            avg_vol_5 = sum([price_data[sorted_dates[i]].get('Trading_Volume', 0) for i in range(idx-5, idx)]) / 5
            if current_vol >= avg_vol_5 * 0.8:
                vol_stable = True
        
        # 綜合判定安全持有
        safety_hold = osc_improving and macd_golden_cross and vol_stable
        # 作為減少亂買的第二門檻信號
        macd_buy_signal = osc_improving and macd_golden_cross
        
        res = {
            'stock_id': stock_id, 'name': details.get('name', ''),
            'industry': industry_map.get(stock_id, '其他'),
            'close': current_price, 'gain': gain, 'vol_ratio': vol_ratio,
            'sitc_ratio': sitc_ratio, 'foreign_days': foreign_days,
            'vcp_ok': vcp_ok, 'vcp_score': vcp_score, 
            'handover_ok': handover_ok, 'handover_score': handover_score,
            'breakout_ok': breakout_ok,
            'inst_multiplier': inst_multiplier, 'inst_status': inst_status,
            'raw_volume': current_vol, 'trading_value': trading_value, 'resistance': res_level,
            'relative_strength': gain - market_gain,
            'safety_hold': safety_hold, # [Upgrade] MACD+量能安全持有旗標
            'macd_buy_signal': macd_buy_signal, # [Upgrade] 593%演算法升級 (第二門檻)
            'macd_details': {'osc': osc, 'dif': dif, 'macd_sig': macd_sig}
        }
        res['score'] = calculate_score(res, weights=weights)
        
        # [Upgrade] 593%演算法升級：減少亂買 (第二門檻)
        if not res['macd_buy_signal']:
            res['score'] *= 0.5 # 未達 MACD 轉強條件，分數減半，降低亂買機率
            
        # 新增：共識門檻過濾 (Mandatory Consensus)
        # 只有當至少 3 項以上指標同時達標時，才考慮買入
        consensus_count = 0
        if res['vol_ratio'] >= 2.0: consensus_count += 1
        if res['sitc_ratio'] >= 1.5: consensus_count += 1
        if res['foreign_days'] >= 3: consensus_count += 1
        if res['vcp_ok']: consensus_count += 1
        if res['handover_ok']: consensus_count += 1
        if res['breakout_ok']: consensus_count += 1
        if res['inst_status'] == "consensus": consensus_count += 1
        
        min_consensus = weights.get('MIN_CONSENSUS_COUNT', 0) if weights else 0
        if consensus_count < min_consensus:
            res['score'] = 0 # 不達標則歸零
        
        # 強勢過濾：如果相對於大盤是弱勢 (RS < 0)，分數大幅打折
        # 但如果是「換手盤整」標的，則稍多保留，因為盤整期通常相對強度較低
        if res['relative_strength'] < 0:
            if not res['handover_ok']:
                res['score'] *= 0.3
            else:
                res['score'] *= 0.6 # 換手盤整標的打 6 折
        elif res['relative_strength'] > 0.10:
            res['score'] *= 2.0 # 超額報酬 > 10% 給予翻倍加成
        elif res['relative_strength'] > 0.05:
            res['score'] *= 1.5 # 超額報酬 > 5% 給予 1.5x 加成
        results.append(res)
    
    # 第二輪：產業集群加成 (Sector Momentum Bonus)
    industry_scores = {}
    for res in results:
        ind = res['industry']
        if res['score'] >= 60: # 門檻
            industry_scores[ind] = industry_scores.get(ind, 0) + 1
            
    # 對於在強勢產業中的標的給予 1.1x ~ 1.2x 的加成
    for res in results:
        ind_count = industry_scores.get(res['industry'], 0)
        if ind_count >= 3:
            res['score'] *= 1.15
            res['industry_bonus'] = True
        else:
            res['industry_bonus'] = False

    # 第三輪：過濾與排序
    candidates = [r for r in results if r['score'] >= min_score]
    
    # [Upgrade] 產業集群過濾門檻：僅買入當日高分標的中，所屬產業排名前 N 大的標的 (確保在主場作戰)
    industry_filter_n = weights.get('INDUSTRY_FILTER_TOP_N') if weights else None
    
    if industry_filter_n and candidates:
        # 統計候選標的的產業分布
        cand_ind_count = {}
        for r in candidates:
            ind = r['industry']
            cand_ind_count[ind] = cand_ind_count.get(ind, 0) + 1
        
        # 取得前 N 名產業 (至少要有 1 檔以上才算)
        sorted_cand_ind = sorted(cand_ind_count.items(), key=lambda x: x[1], reverse=True)
        top_industries = [ind for ind, count in sorted_cand_ind[:industry_filter_n] if count >= 1]
        
        # 僅保留屬於前 N 名產業的標的
        final_results = [r for r in candidates if r['industry'] in top_industries]
    else:
        final_results = candidates

    final_results.sort(key=lambda x: (x['score'], x['gain']), reverse=True)
    return final_results

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
        if res['handover_ok']: note += "換手盤整 "
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
