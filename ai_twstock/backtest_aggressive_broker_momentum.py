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
# 激進券商動量回測參數設定 - 目標年化139%
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

def calculate_aggressive_broker_score(stock_id, date, broker_data, price_data):
    """
    計算激進版券商動量評分 - 專注於強勢突破訊號
    
    核心策略：
    1. 超級強勢訊號：外資+投信+自營三方同步大量買進
    2. 轉機訊號：外資大賣但投信瘋狂承接 (底部反轉)
    3. 突破訊號：連續多日大額買進 + 高價成交意願
    4. 動能訊號：成交量暴增 + 主力集中度高
    """
    
    if 'trading_daily_report' not in broker_data:
        return 0, {}
    
    daily_reports = broker_data['trading_daily_report']
    if date not in daily_reports:
        return 0, {}
    
    report = daily_reports[date]
    
    # 初始化評分組件 - 更激進的評分標準
    score_components = {
        'super_momentum': 0,        # 超級動量 (50分)
        'turnaround_signal': 0,     # 轉機訊號 (40分) 
        'breakout_signal': 0,       # 突破訊號 (30分)
        'volume_explosion': 0,      # 成交量爆發 (20分)
        'price_conviction': 0,      # 價格信念 (15分)
        'continuity_power': 0       # 連續性力道 (15分)
    }
    
    # 獲取當前價格和成交量
    current_price = price_data.get(date, {}).get('close', 0)
    current_volume = price_data.get(date, {}).get('Trading_Volume', 0)
    if current_price == 0:
        return 0, score_components
    
    # 1. 分析買方力道 - 更細緻的分類
    foreign_net_buy = 0
    domestic_major_net_buy = 0
    domestic_minor_net_buy = 0
    total_buy_amount = 0
    ultra_high_price_buyers = 0  # 超高價買進 (>1%)
    high_price_buyers = 0        # 高價買進 (>0.5%)
    
    # 分析 top_buyers
    if 'top_buyers' in report:
        for buyer in report['top_buyers']:
            trader_name = buyer.get('trader', '')
            net_amount = buyer.get('net', 0)
            avg_price = buyer.get('avg_p', current_price)
            
            broker_type = classify_broker(trader_name)
            
            if broker_type == 'foreign':
                foreign_net_buy += net_amount
            elif broker_type == 'domestic_major':
                domestic_major_net_buy += net_amount
            else:
                domestic_minor_net_buy += net_amount
            
            total_buy_amount += net_amount
            
            # 價格信念分析 - 更嚴格標準
            price_premium = (avg_price - current_price) / current_price
            if price_premium > 0.01:  # 超過1%
                ultra_high_price_buyers += 1
            elif price_premium > 0.005:  # 超過0.5%
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
    
    # 3. 計算各項評分 - 激進標準
    
    foreign_net = foreign_net_buy - foreign_net_sell
    domestic_net = domestic_major_net_buy - domestic_major_net_sell
    
    # 超級動量評分 (50分) - 三方同步買進
    if foreign_net > 0 and domestic_net > 0 and domestic_minor_net_buy > 0:
        # 三方都買超，計算協同強度
        min_net = min(foreign_net, domestic_net, domestic_minor_net_buy)
        synergy_strength = min_net / 200000  # 20萬股為基準
        score_components['super_momentum'] = min(50, synergy_strength * 25)
        
        # 如果外資和投信都大量買進，額外加成
        if foreign_net > 1000000 and domestic_net > 500000:
            score_components['super_momentum'] += 20
    
    # 轉機訊號評分 (40分) - 外資賣出但投信瘋狂承接
    elif foreign_net < -500000 and domestic_net > abs(foreign_net) * 1.2:
        # 投信承接力道超過外資賣壓的1.2倍
        takeover_ratio = domestic_net / abs(foreign_net)
        score_components['turnaround_signal'] = min(40, takeover_ratio * 15)
        
        # 如果承接量特別大，額外加成
        if domestic_net > 1500000:
            score_components['turnaround_signal'] += 15
    
    # 突破訊號評分 (30分) - 單方面強勢買進
    elif foreign_net > 1000000 or domestic_net > 800000:
        breakthrough_power = max(foreign_net / 1000000, domestic_net / 800000)
        score_components['breakout_signal'] = min(30, breakthrough_power * 20)
    
    # 成交量爆發評分 (20分)
    if current_volume > 0 and total_buy_amount > 0:
        # 計算主力買盤佔總成交量比例
        buy_concentration = (total_buy_amount * current_price) / (current_volume * current_price)
        if buy_concentration > 0.3:  # 主力買盤超過30%
            score_components['volume_explosion'] = min(20, buy_concentration * 40)
    
    # 價格信念評分 (15分)
    conviction_score = ultra_high_price_buyers * 8 + high_price_buyers * 3
    score_components['price_conviction'] = min(15, conviction_score)
    
    # 連續性力道評分 (15分)
    continuity_score = calculate_aggressive_continuity(stock_id, date, broker_data, daily_reports)
    score_components['continuity_power'] = continuity_score
    
    total_score = sum(score_components.values())
    return total_score, score_components

def calculate_aggressive_continuity(stock_id, current_date, broker_data, daily_reports):
    """計算激進版連續性評分"""
    try:
        all_dates = sorted(daily_reports.keys())
        current_idx = all_dates.index(current_date)
        
        if current_idx < 4:  # 需要至少5天數據
            return 0
        
        # 檢查前5天的券商行為趨勢
        foreign_trend = []
        domestic_trend = []
        volume_trend = []
        
        for i in range(max(0, current_idx-4), current_idx+1):
            date = all_dates[i]
            report = daily_reports[date]
            
            foreign_net = 0
            domestic_net = 0
            total_amount = 0
            
            # 計算當日券商淨買賣
            if 'top_buyers' in report:
                for buyer in report['top_buyers']:
                    trader_name = buyer.get('trader', '')
                    net_amount = buyer.get('net', 0)
                    broker_type = classify_broker(trader_name)
                    
                    total_amount += net_amount
                    
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
            
            # 更嚴格的趨勢判斷標準
            foreign_trend.append(2 if foreign_net > 500000 else 1 if foreign_net > 100000 else -1 if foreign_net < -100000 else 0)
            domestic_trend.append(2 if domestic_net > 300000 else 1 if domestic_net > 100000 else -1 if domestic_net < -100000 else 0)
            volume_trend.append(2 if total_amount > 1000000 else 1 if total_amount > 500000 else 0)
        
        # 計算連續性加分 - 更激進的標準
        bonus = 0
        
        # 外資連續強勢買進 (5天都大量買超)
        if all(x >= 2 for x in foreign_trend):
            bonus += 15
        elif all(x >= 1 for x in foreign_trend):
            bonus += 8
        
        # 投信連續強勢買進
        if all(x >= 2 for x in domestic_trend):
            bonus += 12
        elif all(x >= 1 for x in domestic_trend):
            bonus += 6
        
        # 成交量連續放大
        if all(x >= 1 for x in volume_trend):
            bonus += 5
        
        # 轉機加速訊號 (外資從賣轉買，投信持續買進)
        if foreign_trend[-1] >= 1 and any(x < 0 for x in foreign_trend[:-1]) and all(x >= 1 for x in domestic_trend):
            bonus += 20  # 轉機訊號給最高分
        
        return min(15, bonus)
        
    except Exception as e:
        return 0

def preprocess_data(data):
    """預處理股票資料"""
    processed_data = {}
    
    for sid, stock_data in data.items():
        if 'price' not in stock_data or not stock_data['price']:
            continue
            
        # 確保有足夠的歷史資料
        price_dates = list(stock_data['price'].keys())
        if len(price_dates) < 60:
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

def run_aggressive_broker_backtest(override_config=None, silent=False):
    """執行激進券商動量回測 - 目標年化139%"""
    
    # 1. 載入資料與設定
    data = analyze_momentum.load_stock_data_wrapper(DATA_FILE)
    data = preprocess_data(data)
    stock_names = load_stock_names()
    _config = load_config()
    if override_config: 
        _config.update(override_config)

    starting_cash = _config.get('STARTING_CASH', 1000000)
    
    # 激進參數設定 - 追求高報酬
    top_n = 3  # 極度集中持股，只持有3檔最強股票
    
    # 回測期間設定 (6個月，更短期更激進)
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    if not all_dates: 
        return None
    
    end_idx = len(all_dates) - 1
    start_idx = max(0, end_idx - 120)  # 約6個月交易日
    
    # 激進的買賣參數
    buy_score_threshold = 100  # 提高門檻，只買最強的
    take_profit_threshold = 0.50  # 50%獲利了結 (更貪心)
    stop_loss_threshold = -0.15  # 15%停損 (給更大空間)
    trailing_stop_threshold = -0.10  # 10%追蹤停損 (更寬鬆)

    # 2. 初始化帳戶
    cash = starting_cash
    total_invested = starting_cash
    portfolio = {} 
    transactions = [] 
    
    def should_buy_today(date_idx):
        """每3天選股一次 (更頻繁)"""
        return date_idx % 3 == 0

    def get_market_filter(date_idx):
        """簡化市場過濾器 - 更激進"""
        return True, 1.0  # 不管市場環境，永遠全力投入

    # 3. 主要回測迴圈
    for date_idx in range(start_idx, len(all_dates)):
        current_date = all_dates[date_idx]
        
        # 更新投資組合價值
        portfolio_value = cash
        for sid, position in portfolio.items():
            if current_date in data[sid]['price']:
                current_price = data[sid]['price'][current_date]['close']
                portfolio_value += position['shares'] * current_price

        # 檢查賣出條件 - 更激進的持有策略
        to_sell = []
        for sid, position in portfolio.items():
            if current_date not in data[sid]['price']:
                continue
                
            current_price = data[sid]['price'][current_date]['close']
            gain = (current_price - position['avg_cost']) / position['avg_cost']
            
            # 更新最高價格
            if current_price > position.get('highest_price', position['avg_cost']):
                position['highest_price'] = current_price
            
            # 賣出條件判斷 - 更寬鬆的停損，更貪心的獲利
            sell_reason = None
            
            # 1. 大幅獲利了結
            if gain >= take_profit_threshold:
                sell_reason = f"大幅獲利了結 (+{gain:.1%})"
            
            # 2. 嚴格停損 (給更大虧損空間)
            elif gain <= stop_loss_threshold:
                sell_reason = f"嚴格停損 ({gain:.1%})"
            
            # 3. 寬鬆追蹤停損
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

        # 檢查買進條件 - 更激進的選股
        if should_buy_today(date_idx):
            if len(portfolio) < top_n:
                # 計算所有股票的券商動量評分
                candidates = []
                
                for sid in list(data.keys())[:300]:  # 擴大搜尋範圍
                    if sid in portfolio:  # 已持有的跳過
                        continue
                    if current_date not in data[sid]['price']:
                        continue
                    
                    # 基本過濾條件 - 更寬鬆
                    price_info = data[sid]['price'][current_date]
                    if price_info['close'] < 10 or price_info.get('Trading_Volume', 0) < 500:
                        continue
                    
                    # 載入券商資料並計算評分
                    broker_data = load_broker_data(sid)
                    if not broker_data:
                        continue
                    
                    score, components = calculate_aggressive_broker_score(sid, current_date, broker_data, data[sid]['price'])
                    
                    if score >= buy_score_threshold:
                        candidates.append({
                            'sid': sid,
                            'score': score,
                            'price': price_info['close'],
                            'components': components
                        })
                
                # 選擇評分最高的股票買進 - 極度集中投資
                candidates.sort(key=lambda x: x['score'], reverse=True)
                
                available_slots = top_n - len(portfolio)
                
                # 激進的資金配置 - 全部現金投入
                for i, candidate in enumerate(candidates[:available_slots]):
                    if cash < 50000:  # 現金不足
                        break
                    
                    sid = candidate['sid']
                    price = candidate['price']
                    score = candidate['score']
                    
                    # 激進的買進策略 - 平均分配所有現金
                    remaining_slots = available_slots - i
                    target_value = cash / remaining_slots * 0.95  # 95%資金投入
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
    
    # 計算基準績效 (動態選擇可用日期)
    benchmark_return = 0
    benchmark_annualized = 0
    if '0050' in data:
        available_dates = sorted(data['0050']['price'].keys())
        
        # 找最接近的開始和結束日期
        start_date = all_dates[start_idx]
        end_date = all_dates[-1]
        
        start_price_date = None
        for date in available_dates:
            if date >= start_date:
                start_price_date = date
                break
        if not start_price_date:
            start_price_date = available_dates[-1]
        
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
        print(f"\n=== 激進券商動量回測結果 ===")
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
            print(f"[INFO] 需要提升 {(target_return - annualized_return):.2%} 才能達標")

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
    print("執行激進券商動量回測 - 目標年化139%...")
    result = run_aggressive_broker_backtest()
    if result:
        print(f"\n最終結果:")
        print(f"年化報酬率: {result['annualized_return']:.2%}")
        print(f"基準年化報酬率: {result['benchmark_annualized']:.2%}")
        print(f"超額年化報酬: {result['excess_return']:.2%}")
        print(f"是否達成139%目標: {'是' if result['target_achieved'] else '否'}")