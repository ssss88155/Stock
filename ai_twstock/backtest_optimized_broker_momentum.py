import json
import os
import sys
import pandas as pd
from datetime import datetime, timedelta
import calendar
from collections import OrderedDict, defaultdict
import numpy as np

# 嘗試設定輸出編碼為 UTF-8 以支援中文
try:
    if sys.stdout.encoding != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

# Import existing momentum analysis logic
import analyze_momentum

# =================================================================
# 優化券商動量回測參數設定
# =================================================================
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config', 'backtest_config.json')
BROKER_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data_independent_microstructure')

def load_config():
    """載入回測參數設定"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] 載入設定檔失敗: {e}")
    return {}

def load_broker_data(stock_id):
    """載入特定股票的分點券商資料"""
    broker_file = os.path.join(BROKER_DATA_DIR, f"{stock_id}.json")
    if os.path.exists(broker_file):
        try:
            with open(broker_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] 載入券商資料失敗 {stock_id}: {e}")
    return {}

# 定義主要外資券商 (基於常見的外資券商代碼)
FOREIGN_BROKERS = {
    '港麥格理', '瑞銀', '摩根大通', '美林', '台灣摩根', '美商高盛', 
    '港商野村', '法銀巴黎', '大和國泰', '花旗環球', '上海匯豐',
    '瑞士信貸', '德意志', '荷銀', '里昂', '麥格理'
}

# 定義主要投信券商
SITC_BROKERS = {
    '群益', '凱基', '永豐金', '富邦', '國泰', '統一', '元大', 
    '台新證券', '新光', '日盛', '兆豐', '第一金'
}

DATA_FILE = 'stock_data.json'
STOCKS_INFO_FILE = 'taiwan_stocks.csv'

def classify_broker(broker_name):
    """分類券商類型"""
    if any(foreign in broker_name for foreign in FOREIGN_BROKERS):
        return 'foreign'
    elif any(sitc in broker_name for sitc in SITC_BROKERS):
        return 'domestic_major'
    else:
        return 'domestic_minor'

def calculate_enhanced_broker_score(stock_id, date, broker_data, price_data):
    """
    計算增強版券商動量評分
    
    核心策略優化：
    1. 外資 + 投信同步買進 = 超強訊號 (加成)
    2. 外資賣出但投信大量承接 = 轉機訊號
    3. 連續性分析：3日券商行為趨勢
    4. 價格敏感度：願意高價買進的券商信心
    5. 成交量集中度：主力控盤程度
    """
    
    if 'trading_daily_report' not in broker_data:
        return 0, {}
    
    daily_reports = broker_data['trading_daily_report']
    if date not in daily_reports:
        return 0, {}
    
    report = daily_reports[date]
    
    # 初始化評分組件
    score_components = {
        'foreign_momentum': 0,      # 外資動量 (35分)
        'domestic_momentum': 0,     # 本土券商動量 (30分)
        'price_confidence': 0,      # 價格信心 (15分)
        'volume_concentration': 0,  # 成交量集中度 (10分)
        'continuity_bonus': 0,      # 連續性加分 (10分)
        'synergy_bonus': 0          # 協同效應加分 (額外20分)
    }
    
    # 獲取當前價格
    current_price = price_data.get(date, {}).get('close', 0)
    if current_price == 0:
        return 0, score_components
    
    # 1. 分析當日買方力道
    foreign_net_buy = 0
    domestic_major_net_buy = 0
    total_buy_value = 0
    high_price_buyers = 0
    foreign_buyers = []
    domestic_buyers = []
    
    # 分析 top_buyers
    if 'top_buyers' in report:
        for buyer in report['top_buyers']:
            trader_name = buyer.get('trader', '')
            net_amount = buyer.get('net', 0)
            avg_price = buyer.get('avg_p', current_price)
            
            broker_type = classify_broker(trader_name)
            
            if broker_type == 'foreign':
                foreign_net_buy += net_amount
                foreign_buyers.append((trader_name, net_amount, avg_price))
            elif broker_type == 'domestic_major':
                domestic_major_net_buy += net_amount
                domestic_buyers.append((trader_name, net_amount, avg_price))
            
            total_buy_value += net_amount * avg_price
            
            # 高價買進信心指標 (比收盤價高0.3%以上)
            if avg_price > current_price * 1.003:
                high_price_buyers += 1
    
    # 2. 分析賣方壓力
    foreign_net_sell = 0
    domestic_major_net_sell = 0
    
    if 'top_sellers' in report:
        for seller in report['top_sellers']:
            trader_name = seller.get('trader', '')
            net_amount = seller.get('net_s', 0)
            
            broker_type = classify_broker(trader_name)
            
            if broker_type == 'foreign':
                foreign_net_sell += net_amount
            elif broker_type == 'domestic_major':
                domestic_major_net_sell += net_amount
    
    # 3. 計算各項評分
    
    # 外資動量評分 (35分)
    foreign_net = foreign_net_buy - foreign_net_sell
    if foreign_net > 0:
        # 外資買超，根據金額給分
        score_components['foreign_momentum'] = min(35, foreign_net / 500000 * 10)
    else:
        # 外資賣超，輕微扣分
        score_components['foreign_momentum'] = max(-10, foreign_net / 1000000 * 5)
    
    # 本土大券商動量評分 (30分)
    domestic_net = domestic_major_net_buy - domestic_major_net_sell
    if domestic_net > 0:
        score_components['domestic_momentum'] = min(30, domestic_net / 300000 * 8)
    
    # 價格信心評分 (15分)
    if high_price_buyers > 0:
        score_components['price_confidence'] = min(15, high_price_buyers * 3)
    
    # 成交量集中度評分 (10分)
    if total_buy_value > 0:
        daily_volume = price_data.get(date, {}).get('Trading_Volume', 0)
        if daily_volume > 0:
            concentration = (total_buy_value / (daily_volume * current_price))
            score_components['volume_concentration'] = min(10, concentration * 20)
    
    # 4. 連續性加分 (檢查前3天的券商行為)
    continuity_score = calculate_continuity_bonus_enhanced(stock_id, date, broker_data, daily_reports)
    score_components['continuity_bonus'] = continuity_score
    
    # 5. 協同效應加分 (外資+投信同步買進的額外加成)
    if foreign_net > 0 and domestic_net > 0:
        # 外資和投信都買超，給予協同加分
        synergy_strength = min(foreign_net, domestic_net) / 500000
        score_components['synergy_bonus'] = min(20, synergy_strength * 15)
    elif foreign_net < 0 and domestic_net > domestic_major_net_sell * 1.5:
        # 外資賣出但投信大量承接，轉機訊號
        takeover_strength = domestic_net / abs(foreign_net) if foreign_net != 0 else 1
        score_components['synergy_bonus'] = min(15, takeover_strength * 10)
    
    total_score = sum(score_components.values())
    return total_score, score_components

def calculate_continuity_bonus_enhanced(stock_id, current_date, broker_data, daily_reports):
    """計算增強版連續性加分"""
    try:
        all_dates = sorted(daily_reports.keys())
        current_idx = all_dates.index(current_date)
        
        if current_idx < 2:  # 需要至少3天數據
            return 0
        
        # 檢查前3天的外資和本土大券商行為
        foreign_trend = []
        domestic_trend = []
        
        for i in range(max(0, current_idx-2), current_idx+1):
            date = all_dates[i]
            report = daily_reports[date]
            
            foreign_net = 0
            domestic_net = 0
            
            # 計算當日外資和本土券商淨買賣
            if 'top_buyers' in report:
                for buyer in report['top_buyers']:
                    trader_name = buyer.get('trader', '')
                    net_amount = buyer.get('net', 0)
                    broker_type = classify_broker(trader_name)
                    
                    if broker_type == 'foreign':
                        foreign_net += net_amount
                    elif broker_type == 'domestic_major':
                        domestic_net += net_amount
            
            if 'top_sellers' in report:
                for seller in report['top_sellers']:
                    trader_name = seller.get('trader', '')
                    net_amount = seller.get('net_s', 0)
                    broker_type = classify_broker(trader_name)
                    
                    if broker_type == 'foreign':
                        foreign_net -= net_amount
                    elif broker_type == 'domestic_major':
                        domestic_net -= net_amount
            
            foreign_trend.append(1 if foreign_net > 100000 else -1 if foreign_net < -100000 else 0)
            domestic_trend.append(1 if domestic_net > 100000 else -1 if domestic_net < -100000 else 0)
        
        # 計算連續性加分
        bonus = 0
        
        # 外資連續買進 (3天都買超)
        if all(x > 0 for x in foreign_trend):
            bonus += 8
        
        # 本土券商連續買進 (3天都買超)
        if all(x > 0 for x in domestic_trend):
            bonus += 6
        
        # 外資轉向 (前面賣出，最近買進)
        if foreign_trend[-1] > 0 and any(x < 0 for x in foreign_trend[:-1]):
            bonus += 5
        
        # 投信接手 (外資賣出但投信連續買進)
        if foreign_trend[-1] < 0 and all(x > 0 for x in domestic_trend):
            bonus += 10  # 轉機訊號，給更高分
        
        return min(10, bonus)
        
    except Exception as e:
        return 0

def preprocess_data(data):
    """預處理股票資料，確保資料完整性"""
    processed_data = {}
    
    for sid, stock_data in data.items():
        if 'price' not in stock_data or not stock_data['price']:
            continue
            
        # 確保有足夠的歷史資料
        price_dates = list(stock_data['price'].keys())
        if len(price_dates) < 60:  # 至少需要60天資料
            continue
            
        processed_data[sid] = stock_data
    
    return processed_data

def load_stock_names():
    """載入股票名稱對照表"""
    names = {}
    if os.path.exists(STOCKS_INFO_FILE):
        try:
            import csv
            with open(STOCKS_INFO_FILE, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    names[row['code']] = row.get('name', row['code'])
        except Exception as e:
            print(f"[WARN] 載入股票名稱失敗: {e}")
    return names

def run_optimized_broker_backtest(override_config=None, silent=False):
    """執行優化券商動量回測"""
    
    # 1. 載入資料與設定
    data = analyze_momentum.load_stock_data_wrapper(DATA_FILE)
    data = preprocess_data(data)
    stock_names = load_stock_names()
    _config = load_config()
    if override_config: 
        _config.update(override_config)

    starting_cash = _config.get('STARTING_CASH', 1000000)
    
    # 優化參數設定
    top_n = 5  # 減少持股數量，提高集中度
    
    # 回測期間設定 (12個月)
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    if not all_dates: 
        return None
    
    end_idx = len(all_dates) - 1
    start_idx = max(0, end_idx - 250)  # 約12個月交易日
    
    # 更積極的參數設定
    buy_score_threshold = 60  # 降低門檻，增加交易機會
    take_profit_threshold = 0.20  # 20%獲利了結
    stop_loss_threshold = -0.06  # 6%停損
    trailing_stop_threshold = -0.04  # 4%追蹤停損

    # 2. 初始化帳戶
    cash = starting_cash
    total_invested = starting_cash
    portfolio = {} 
    transactions = [] 
    
    def should_buy_today(date_idx):
        """每週選股一次 (週一)"""
        date_obj = datetime.strptime(all_dates[date_idx], '%Y-%m-%d')
        return date_obj.weekday() == 0  # 0 = 週一

    def get_market_filter(date_idx):
        """市場環境過濾器"""
        if date_idx < 20: 
            return True, 1.0
        
        # 檢查大盤趨勢 (使用0050)
        if '0050' in data:
            idx_prices = [data['0050']['price'][d]['close'] for d in all_dates[date_idx-20:date_idx+1] 
                         if d in data['0050']['price']]
            if len(idx_prices) >= 20:
                ma20 = sum(idx_prices[:-1]) / 20
                ma5 = sum(idx_prices[-5:]) / 5
                # 短均線在長均線之上 = 多頭市場
                return ma5 > ma20, 1.0
        
        return True, 1.0

    # 3. 主要回測迴圈
    for date_idx in range(start_idx, len(all_dates)):
        current_date = all_dates[date_idx]
        
        # 更新投資組合價值
        portfolio_value = cash
        for sid, position in portfolio.items():
            if current_date in data[sid]['price']:
                current_price = data[sid]['price'][current_date]['close']
                portfolio_value += position['shares'] * current_price

        # 檢查賣出條件
        to_sell = []
        for sid, position in portfolio.items():
            if current_date not in data[sid]['price']:
                continue
                
            current_price = data[sid]['price'][current_date]['close']
            gain = (current_price - position['avg_cost']) / position['avg_cost']
            
            # 更新最高價格 (用於追蹤停損)
            if current_price > position.get('highest_price', position['avg_cost']):
                position['highest_price'] = current_price
            
            # 賣出條件判斷
            sell_reason = None
            
            # 1. 獲利了結
            if gain >= take_profit_threshold:
                sell_reason = f"獲利了結 (+{gain:.1%})"
            
            # 2. 停損
            elif gain <= stop_loss_threshold:
                sell_reason = f"停損 ({gain:.1%})"
            
            # 3. 追蹤停損
            elif position.get('highest_price'):
                drawdown = (current_price - position['highest_price']) / position['highest_price']
                if drawdown <= trailing_stop_threshold:
                    sell_reason = f"追蹤停損 ({drawdown:.1%})"
            
            if sell_reason:
                to_sell.append((sid, sell_reason))

        # 執行賣出
        for sid, reason in to_sell:
            position = portfolio[sid]
            sell_shares = position['shares']
            current_price = data[sid]['price'][current_date]['close']
            sell_value = sell_shares * current_price * 0.998  # 扣除交易成本
            cash += sell_value
            
            gain = (current_price - position['avg_cost']) / position['avg_cost']
            
            transactions.append({
                'date': current_date,
                'action': 'SELL',
                'stock_id': sid,
                'stock_name': stock_names.get(sid, sid),
                'shares': sell_shares,
                'price': current_price,
                'value': sell_value,
                'gain': gain,
                'reason': reason
            })
            
            del portfolio[sid]
            
            if not silent:
                print(f"[{current_date}] 賣出 {sid} {sell_shares}股 @ {current_price:.2f} ({reason})")

        # 檢查買進條件
        if should_buy_today(date_idx):
            market_ok, _ = get_market_filter(date_idx)
            
            if market_ok and len(portfolio) < top_n:
                # 計算所有股票的券商動量評分
                candidates = []
                
                for sid in list(data.keys())[:200]:  # 限制範圍提高效率
                    if sid in portfolio:  # 已持有的跳過
                        continue
                    if current_date not in data[sid]['price']:
                        continue
                    
                    # 基本過濾條件
                    price_info = data[sid]['price'][current_date]
                    if price_info['close'] < 15 or price_info.get('Trading_Volume', 0) < 1000:
                        continue
                    
                    # 載入券商資料並計算評分
                    broker_data = load_broker_data(sid)
                    if not broker_data:
                        continue
                    
                    score, components = calculate_enhanced_broker_score(sid, current_date, broker_data, data[sid]['price'])
                    
                    if score >= buy_score_threshold:
                        candidates.append({
                            'sid': sid,
                            'score': score,
                            'price': price_info['close'],
                            'components': components
                        })
                
                # 選擇評分最高的股票買進
                candidates.sort(key=lambda x: x['score'], reverse=True)
                
                available_slots = top_n - len(portfolio)
                buy_budget = cash / available_slots if available_slots > 0 else 0
                
                for candidate in candidates[:available_slots]:
                    if cash < buy_budget * 0.5:  # 現金不足
                        break
                    
                    sid = candidate['sid']
                    price = candidate['price']
                    score = candidate['score']
                    
                    # 計算買進股數
                    target_value = min(buy_budget, cash * 0.8)
                    shares = int(target_value / price / 1000) * 1000  # 以千股為單位
                    
                    if shares >= 1000:  # 至少買1張
                        buy_value = shares * price * 1.002  # 加上交易成本
                        
                        if buy_value <= cash:
                            cash -= buy_value
                            
                            # 記錄交易
                            transactions.append({
                                'date': current_date,
                                'action': 'BUY',
                                'stock_id': sid,
                                'stock_name': stock_names.get(sid, sid),
                                'shares': shares,
                                'price': price,
                                'value': buy_value,
                                'score': score,
                                'components': candidate['components']
                            })
                            
                            # 更新持股
                            portfolio[sid] = {
                                'shares': shares,
                                'avg_cost': price,
                                'buy_date': current_date,
                                'highest_price': price
                            }
                            
                            if not silent:
                                print(f"[{current_date}] 買進 {sid} {shares}股 @ {price:.2f} (評分:{score:.0f})")

    # 4. 計算最終績效
    final_value = cash
    for sid, position in portfolio.items():
        if all_dates[-1] in data[sid]['price']:
            final_price = data[sid]['price'][all_dates[-1]]['close']
            final_value += position['shares'] * final_price

    # 計算年化報酬率
    days = (datetime.strptime(all_dates[-1], '%Y-%m-%d') - datetime.strptime(all_dates[start_idx], '%Y-%m-%d')).days
    years = days / 365.25
    total_return = (final_value - total_invested) / total_invested
    annualized_return = (1 + total_return) ** (1/years) - 1 if years > 0 else 0
    
    # 計算0050基準績效
    benchmark_return = 0
    benchmark_annualized = 0
    if '0050' in data:
        # 找到有效的開始和結束日期
        start_date = all_dates[start_idx]
        end_date = all_dates[-1]
        
        # 確保日期存在於0050資料中
        available_dates = sorted(data['0050']['price'].keys())
        
        # 找最接近的開始日期
        start_price_date = None
        for date in available_dates:
            if date >= start_date:
                start_price_date = date
                break
        if not start_price_date:
            start_price_date = available_dates[-1]
        
        # 找最接近的結束日期
        end_price_date = None
        for date in reversed(available_dates):
            if date <= end_date:
                end_price_date = date
                break
        if not end_price_date:
            end_price_date = available_dates[0]
        
        if start_price_date and end_price_date:
            start_price = data['0050']['price'][start_price_date]['close']
            end_price = data['0050']['price'][end_price_date]['close']
            benchmark_return = (end_price - start_price) / start_price
            benchmark_annualized = (1 + benchmark_return) ** (1/years) - 1 if years > 0 else 0

    if not silent:
        print(f"\n=== 優化券商動量回測結果 ===")
        print(f"回測期間: {all_dates[start_idx]} ~ {all_dates[-1]} ({days}天)")
        print(f"初始資金: {starting_cash:,.0f}")
        print(f"最終價值: {final_value:,.0f}")
        print(f"總報酬率: {total_return:.2%}")
        print(f"年化報酬率: {annualized_return:.2%}")
        print(f"0050基準年化: {benchmark_annualized:.2%}")
        print(f"超額年化報酬: {(annualized_return - benchmark_annualized):.2%}")
        print(f"交易次數: {len(transactions)}")
        
        # 目標檢查
        target_return = 1.39  # 139%
        if annualized_return > target_return:
            print(f"[SUCCESS] 達成目標！年化報酬率 {annualized_return:.2%} > 目標 {target_return:.0%}")
        else:
            print(f"[INFO] 未達目標，年化報酬率 {annualized_return:.2%} < 目標 {target_return:.0%}")

    return {
        'total_return': total_return,
        'annualized_return': annualized_return,
        'benchmark_return': benchmark_return,
        'benchmark_annualized': benchmark_annualized,
        'excess_return': annualized_return - benchmark_annualized,
        'final_value': final_value,
        'transactions': transactions,
        'days': days,
        'target_achieved': annualized_return > 1.39
    }

if __name__ == "__main__":
    print("執行優化券商動量回測...")
    result = run_optimized_broker_backtest()
    if result:
        print(f"\n最終結果:")
        print(f"年化報酬率: {result['annualized_return']:.2%}")
        print(f"基準年化報酬率: {result['benchmark_annualized']:.2%}")
        print(f"超額年化報酬: {result['excess_return']:.2%}")
        print(f"是否達成139%目標: {'是' if result['target_achieved'] else '否'}")