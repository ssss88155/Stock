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
# 隔日沖跟單策略回測 - 兩種策略
# =================================================================
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config', 'backtest_config.json')
BROKER_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data_independent_microstructure')
MICRO_FEATURE_FILE = os.path.join(os.path.dirname(__file__), 'data', 'micro_feature_all.json')

def load_config():
    """載入回測參數設定"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] 載入設定檔失敗: {e}")
    return {}

def load_broker_features():
    """載入券商特徵資料"""
    if os.path.exists(MICRO_FEATURE_FILE):
        try:
            with open(MICRO_FEATURE_FILE, 'r', encoding='utf-8') as f:
                features = json.load(f)
                # 建立 ID 到特徵的映射
                return {item['id']: item for item in features}
        except Exception as e:
            print(f"[WARN] 載入券商特徵失敗: {e}")
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

def identify_day_trading_brokers(broker_features):
    """識別隔日沖券商"""
    day_trading_brokers = set()
    
    # 基於穩重指數識別 (穩重指數 < 0 的券商)
    for broker_id, features in broker_features.items():
        stability = features.get('穩重指數', 100)
        if stability < 0:
            day_trading_brokers.add(broker_id)
    
    # 已知的隔日沖券商 (基於分析結果)
    known_day_traders = {
        '1440',  # 美林
        '1480',  # 美商高盛  
        '1650',  # 瑞銀
        '1360',  # 港麥格理
        '1470',  # 台灣摩根
        '1560',  # 港商野村
        '8440',  # 摩根大通
        '9800',  # 元大 (部分分點)
        '8900',  # 法銀巴黎
    }
    
    day_trading_brokers.update(known_day_traders)
    return day_trading_brokers

def detect_day_trading_patterns(stock_id, broker_data, day_trading_brokers, lookback_days=5):
    """
    檢測隔日沖模式
    
    策略1: 隔日沖倒貨後反彈 - 當隔日沖券商大量賣出後，預期反彈
    策略2: 隔日沖拉抬跟進 - 當隔日沖券商大量買進時，跟進操作
    """
    
    if 'trading_daily_report' not in broker_data:
        return []
    
    daily_reports = broker_data['trading_daily_report']
    dates = sorted(daily_reports.keys())
    
    signals = []
    
    for i in range(lookback_days, len(dates)):
        current_date = dates[i]
        current_report = daily_reports[current_date]
        
        # 分析當日隔日沖券商行為
        day_trader_buy_amount = 0
        day_trader_sell_amount = 0
        day_trader_actions = []
        
        # 檢查買方
        if 'top_buyers' in current_report:
            for buyer in current_report['top_buyers']:
                trader_name = buyer.get('trader', '')
                trader_id = trader_name.split('/')[-1] if '/' in trader_name else trader_name
                net_amount = buyer.get('net', 0)
                avg_price = buyer.get('avg_p', 0)
                
                if trader_id in day_trading_brokers and net_amount > 200000:  # 20萬股以上
                    day_trader_buy_amount += net_amount
                    day_trader_actions.append({
                        'trader': trader_name,
                        'action': 'BUY',
                        'amount': net_amount,
                        'price': avg_price
                    })
        
        # 檢查賣方
        if 'top_sellers' in current_report:
            for seller in current_report['top_sellers']:
                trader_name = seller.get('trader', '')
                trader_id = trader_name.split('/')[-1] if '/' in trader_name else trader_name
                net_amount = seller.get('net_s', 0)
                avg_price = seller.get('avg_p', 0)
                
                if trader_id in day_trading_brokers and net_amount > 200000:  # 20萬股以上
                    day_trader_sell_amount += net_amount
                    day_trader_actions.append({
                        'trader': trader_name,
                        'action': 'SELL',
                        'amount': net_amount,
                        'price': avg_price
                    })
        
        # 策略1: 隔日沖倒貨後反彈訊號
        if day_trader_sell_amount > day_trader_buy_amount * 2 and day_trader_sell_amount > 500000:
            # 檢查前幾天是否有大量買進 (確認是倒貨而非空襲)
            recent_buy_amount = 0
            for j in range(max(0, i-3), i):
                prev_date = dates[j]
                prev_report = daily_reports[prev_date]
                
                if 'top_buyers' in prev_report:
                    for buyer in prev_report['top_buyers']:
                        trader_name = buyer.get('trader', '')
                        trader_id = trader_name.split('/')[-1] if '/' in trader_name else trader_name
                        if trader_id in day_trading_brokers:
                            recent_buy_amount += buyer.get('net', 0)
            
            if recent_buy_amount > day_trader_sell_amount * 0.5:  # 前幾天有相當買進量
                signals.append({
                    'date': current_date,
                    'strategy': 'REVERSAL',  # 反彈策略
                    'signal_strength': min(100, day_trader_sell_amount / 1000000 * 50),
                    'day_trader_sell': day_trader_sell_amount,
                    'recent_buy': recent_buy_amount,
                    'actions': day_trader_actions,
                    'reason': f'隔日沖倒貨 {day_trader_sell_amount:,.0f}股，預期反彈'
                })
        
        # 策略2: 隔日沖拉抬跟進訊號
        elif day_trader_buy_amount > day_trader_sell_amount * 2 and day_trader_buy_amount > 800000:
            # 檢查是否為急拉 (價格相對前日有明顯上漲)
            if i > 0:
                prev_date = dates[i-1]
                if (prev_date in daily_reports and 
                    current_date in daily_reports):
                    
                    signals.append({
                        'date': current_date,
                        'strategy': 'FOLLOW',  # 跟進策略
                        'signal_strength': min(100, day_trader_buy_amount / 1000000 * 40),
                        'day_trader_buy': day_trader_buy_amount,
                        'actions': day_trader_actions,
                        'reason': f'隔日沖大量買進 {day_trader_buy_amount:,.0f}股，跟進操作'
                    })
    
    return signals

def calculate_support_resistance(stock_id, date, price_data, lookback_days=20):
    """計算支撐壓力位"""
    try:
        dates = sorted(price_data.keys())
        current_idx = dates.index(date)
        
        if current_idx < lookback_days:
            return None, None
        
        # 取前20天的價格資料
        recent_dates = dates[current_idx-lookback_days:current_idx]
        highs = [price_data[d]['max'] for d in recent_dates if 'max' in price_data[d]]
        lows = [price_data[d]['min'] for d in recent_dates if 'min' in price_data[d]]
        closes = [price_data[d]['close'] for d in recent_dates if 'close' in price_data[d]]
        
        if len(highs) < 10:
            return None, None
        
        # 簡單的支撐壓力計算
        resistance = max(highs)
        support = min(lows)
        current_price = price_data[date]['close']
        
        # 檢查是否在支撐附近 (支撐上方5%以內)
        near_support = support <= current_price <= support * 1.05
        
        return support, resistance, near_support
        
    except Exception as e:
        return None, None, False

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
    if os.path.exists('taiwan_stocks.csv'):
        try:
            import csv
            with open('taiwan_stocks.csv', 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    names[row['code']] = row.get('name', row['code'])
        except Exception as e:
            print(f"[WARN] 載入股票名稱失敗: {e}")
    return names

def run_day_trading_follow_backtest(override_config=None, silent=False):
    """執行隔日沖跟單策略回測"""
    
    # 1. 載入資料與設定
    data = analyze_momentum.load_stock_data_wrapper('stock_data.json')
    data = preprocess_data(data)
    stock_names = load_stock_names()
    broker_features = load_broker_features()
    day_trading_brokers = identify_day_trading_brokers(broker_features)
    
    _config = load_config()
    if override_config: 
        _config.update(override_config)

    starting_cash = _config.get('STARTING_CASH', 1000000)
    
    # 隔日沖跟單參數
    max_positions = 5  # 最多持有5檔
    
    # 回測期間設定 (3個月，更短期更頻繁)
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    if not all_dates: 
        return None
    
    end_idx = len(all_dates) - 1
    start_idx = max(0, end_idx - 60)  # 約3個月交易日
    
    # 交易參數
    signal_threshold = 30  # 訊號強度門檻
    
    # 策略1參數 (反彈策略)
    reversal_take_profit = 0.08  # 8%獲利了結
    reversal_stop_loss = -0.04   # 4%停損
    reversal_hold_days = 3       # 最多持有3天
    
    # 策略2參數 (跟進策略)  
    follow_take_profit = 0.15    # 15%獲利了結
    follow_stop_loss = -0.06     # 6%停損
    follow_hold_days = 5         # 最多持有5天

    # 2. 初始化帳戶
    cash = starting_cash
    total_invested = starting_cash
    portfolio = {} 
    transactions = [] 
    
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
            
            # 更新最高價格
            if current_price > position.get('highest_price', position['avg_cost']):
                position['highest_price'] = current_price
            
            # 計算持有天數
            buy_date = datetime.strptime(position['buy_date'], '%Y-%m-%d')
            current_date_obj = datetime.strptime(current_date, '%Y-%m-%d')
            hold_days = (current_date_obj - buy_date).days
            
            # 賣出條件判斷
            sell_reason = None
            strategy = position['strategy']
            
            if strategy == 'REVERSAL':
                # 反彈策略賣出條件
                if gain >= reversal_take_profit:
                    sell_reason = f"反彈獲利了結 (+{gain:.1%})"
                elif gain <= reversal_stop_loss:
                    sell_reason = f"反彈停損 ({gain:.1%})"
                elif hold_days >= reversal_hold_days:
                    sell_reason = f"反彈到期賣出 ({gain:.1%})"
            
            elif strategy == 'FOLLOW':
                # 跟進策略賣出條件
                if gain >= follow_take_profit:
                    sell_reason = f"跟進獲利了結 (+{gain:.1%})"
                elif gain <= follow_stop_loss:
                    sell_reason = f"跟進停損 ({gain:.1%})"
                elif hold_days >= follow_hold_days:
                    sell_reason = f"跟進到期賣出 ({gain:.1%})"
            
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
                'reason': reason,
                'strategy': position['strategy']
            })
            
            del portfolio[sid]
            
            if not silent:
                print(f"[{current_date}] 賣出 {sid} {sell_shares}股 @ {current_price:.2f} ({reason})")

        # 檢查買進條件
        if len(portfolio) < max_positions:
            # 掃描所有股票尋找隔日沖訊號
            candidates = []
            
            for sid in list(data.keys())[:100]:  # 限制掃描範圍
                if sid in portfolio:  # 已持有的跳過
                    continue
                if current_date not in data[sid]['price']:
                    continue
                
                # 基本過濾條件
                price_info = data[sid]['price'][current_date]
                if price_info['close'] < 15 or price_info.get('Trading_Volume', 0) < 1000:
                    continue
                
                # 載入券商資料並檢測隔日沖訊號
                broker_data = load_broker_data(sid)
                if not broker_data:
                    continue
                
                signals = detect_day_trading_patterns(sid, broker_data, day_trading_brokers)
                
                # 檢查當日是否有訊號
                for signal in signals:
                    if (signal['date'] == current_date and 
                        signal['signal_strength'] >= signal_threshold):
                        
                        # 對於反彈策略，檢查是否在支撐附近
                        if signal['strategy'] == 'REVERSAL':
                            support, resistance, near_support = calculate_support_resistance(
                                sid, current_date, data[sid]['price'])
                            if not near_support:
                                continue  # 不在支撐附近，跳過
                        
                        candidates.append({
                            'sid': sid,
                            'signal': signal,
                            'price': price_info['close']
                        })
            
            # 按訊號強度排序，選擇最強的訊號
            candidates.sort(key=lambda x: x['signal']['signal_strength'], reverse=True)
            
            available_slots = max_positions - len(portfolio)
            buy_budget = cash / available_slots if available_slots > 0 else 0
            
            for candidate in candidates[:available_slots]:
                if cash < buy_budget * 0.3:  # 現金不足
                    break
                
                sid = candidate['sid']
                price = candidate['price']
                signal = candidate['signal']
                
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
                            'signal_strength': signal['signal_strength'],
                            'strategy': signal['strategy'],
                            'reason': signal['reason']
                        })
                        
                        # 更新持股
                        portfolio[sid] = {
                            'shares': shares,
                            'avg_cost': price,
                            'buy_date': current_date,
                            'highest_price': price,
                            'strategy': signal['strategy']
                        }
                        
                        if not silent:
                            print(f"[{current_date}] 買進 {sid} {shares}股 @ {price:.2f} ({signal['strategy']}: {signal['reason']})")

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
    
    # 統計策略表現
    reversal_trades = [t for t in transactions if t.get('strategy') == 'REVERSAL']
    follow_trades = [t for t in transactions if t.get('strategy') == 'FOLLOW']
    
    reversal_gains = [t['gain'] for t in reversal_trades if t['action'] == 'SELL']
    follow_gains = [t['gain'] for t in follow_trades if t['action'] == 'SELL']

    if not silent:
        print(f"\n=== 隔日沖跟單策略回測結果 ===")
        print(f"回測期間: {all_dates[start_idx]} ~ {all_dates[-1]} ({days}天)")
        print(f"初始資金: {starting_cash:,.0f}")
        print(f"最終價值: {final_value:,.0f}")
        print(f"總報酬率: {total_return:.2%}")
        print(f"年化報酬率: {annualized_return:.2%}")
        print(f"交易次數: {len(transactions)}")
        
        print(f"\n策略分析:")
        print(f"反彈策略交易: {len(reversal_trades)} 次")
        if reversal_gains:
            print(f"反彈策略平均報酬: {sum(reversal_gains)/len(reversal_gains):.2%}")
            print(f"反彈策略勝率: {len([g for g in reversal_gains if g > 0])/len(reversal_gains):.1%}")
        
        print(f"跟進策略交易: {len(follow_trades)} 次")
        if follow_gains:
            print(f"跟進策略平均報酬: {sum(follow_gains)/len(follow_gains):.2%}")
            print(f"跟進策略勝率: {len([g for g in follow_gains if g > 0])/len(follow_gains):.1%}")

    return {
        'total_return': total_return,
        'annualized_return': annualized_return,
        'final_value': final_value,
        'transactions': transactions,
        'days': days,
        'reversal_performance': {
            'trades': len(reversal_trades),
            'avg_return': sum(reversal_gains)/len(reversal_gains) if reversal_gains else 0,
            'win_rate': len([g for g in reversal_gains if g > 0])/len(reversal_gains) if reversal_gains else 0
        },
        'follow_performance': {
            'trades': len(follow_trades),
            'avg_return': sum(follow_gains)/len(follow_gains) if follow_gains else 0,
            'win_rate': len([g for g in follow_gains if g > 0])/len(follow_gains) if follow_gains else 0
        }
    }

if __name__ == "__main__":
    print("執行隔日沖跟單策略回測...")
    result = run_day_trading_follow_backtest()
    if result:
        print(f"\n最終結果:")
        print(f"年化報酬率: {result['annualized_return']:.2%}")
        print(f"反彈策略勝率: {result['reversal_performance']['win_rate']:.1%}")
        print(f"跟進策略勝率: {result['follow_performance']['win_rate']:.1%}")