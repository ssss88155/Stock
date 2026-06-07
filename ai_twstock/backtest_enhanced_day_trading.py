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
# 增強版隔日沖策略 - 基於穩重指數和權重分析
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

def calculate_day_trading_weight(stock_id, date, broker_data, broker_features):
    """
    計算隔日沖權重指數
    
    邏輯：
    - 負分券商 = 隔日沖券商，賣掉可進場 (反彈策略)
    - 正分券商 = 穩健券商，買了可跟進 (跟進策略)
    - 隔日沖買方權重 - 賣方權重 = 進場訊號強度
    """
    
    if 'trading_daily_report' not in broker_data:
        return 0, {}, []
    
    daily_reports = broker_data['trading_daily_report']
    if date not in daily_reports:
        return 0, {}, []
    
    report = daily_reports[date]
    
    # 初始化權重計算
    day_trading_buy_weight = 0    # 隔日沖買方權重
    day_trading_sell_weight = 0   # 隔日沖賣方權重
    stable_buy_weight = 0         # 穩健券商買方權重
    stable_sell_weight = 0        # 穩健券商賣方權重
    
    analysis_details = []
    
    # 分析買方
    if 'top_buyers' in report:
        for buyer in report['top_buyers']:
            trader_name = buyer.get('trader', '')
            trader_id = trader_name.split('/')[-1] if '/' in trader_name else trader_name
            net_amount = buyer.get('net', 0)
            avg_price = buyer.get('avg_p', 0)
            
            # 查詢券商穩重指數
            stability_score = 50  # 預設值
            if trader_id in broker_features:
                stability_score = broker_features[trader_id].get('穩重指數', 50)
            
            # 計算權重 (以淨買賣量為基礎)
            weight = net_amount / 100000  # 以10萬股為單位
            
            if stability_score < 0:
                # 負分 = 隔日沖券商
                day_trading_buy_weight += weight * abs(stability_score) / 100
            else:
                # 正分 = 穩健券商
                stable_buy_weight += weight * stability_score / 100
            
            analysis_details.append({
                'trader': trader_name,
                'action': 'BUY',
                'amount': net_amount,
                'price': avg_price,
                'stability': stability_score,
                'weight': weight,
                'type': 'day_trading' if stability_score < 0 else 'stable'
            })
    
    # 分析賣方
    if 'top_sellers' in report:
        for seller in report['top_sellers']:
            trader_name = seller.get('trader', '')
            trader_id = trader_name.split('/')[-1] if '/' in trader_name else trader_name
            net_amount = seller.get('net_s', 0)
            avg_price = seller.get('avg_p', 0)
            
            # 查詢券商穩重指數
            stability_score = 50  # 預設值
            if trader_id in broker_features:
                stability_score = broker_features[trader_id].get('穩重指數', 50)
            
            # 計算權重
            weight = net_amount / 100000  # 以10萬股為單位
            
            if stability_score < 0:
                # 負分 = 隔日沖券商
                day_trading_sell_weight += weight * abs(stability_score) / 100
            else:
                # 正分 = 穩健券商
                stable_sell_weight += weight * stability_score / 100
            
            analysis_details.append({
                'trader': trader_name,
                'action': 'SELL',
                'amount': net_amount,
                'price': avg_price,
                'stability': stability_score,
                'weight': weight,
                'type': 'day_trading' if stability_score < 0 else 'stable'
            })
    
    # 計算綜合指標
    day_trading_net_weight = day_trading_buy_weight - day_trading_sell_weight
    stable_net_weight = stable_buy_weight - stable_sell_weight
    
    # 總合權重指數
    total_weight_index = day_trading_net_weight + stable_net_weight
    
    weight_analysis = {
        'day_trading_buy': day_trading_buy_weight,
        'day_trading_sell': day_trading_sell_weight,
        'day_trading_net': day_trading_net_weight,
        'stable_buy': stable_buy_weight,
        'stable_sell': stable_sell_weight,
        'stable_net': stable_net_weight,
        'total_index': total_weight_index
    }
    
    return total_weight_index, weight_analysis, analysis_details

def calculate_support_resistance_enhanced(stock_id, date, price_data, lookback_days=20):
    """增強版支撐壓力分析"""
    try:
        dates = sorted(price_data.keys())
        current_idx = dates.index(date)
        
        if current_idx < lookback_days:
            return None, None, False, {}
        
        # 取前N天的價格資料
        recent_dates = dates[current_idx-lookback_days:current_idx]
        highs = []
        lows = []
        closes = []
        volumes = []
        
        for d in recent_dates:
            if all(k in price_data[d] for k in ['max', 'min', 'close']):
                highs.append(price_data[d]['max'])
                lows.append(price_data[d]['min'])
                closes.append(price_data[d]['close'])
                volumes.append(price_data[d].get('Trading_Volume', 0))
        
        if len(highs) < 10:
            return None, None, False, {}
        
        current_price = price_data[date]['close']
        
        # 計算支撐壓力位
        resistance_levels = []
        support_levels = []
        
        # 方法1: 近期高低點
        recent_high = max(highs)
        recent_low = min(lows)
        
        # 方法2: 移動平均作為動態支撐壓力
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else current_price
        ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else current_price
        ma20 = sum(closes) / len(closes)
        
        # 方法3: 成交量加權支撐位 (高成交量的價位更重要)
        volume_weighted_prices = []
        for i, (price, vol) in enumerate(zip(closes, volumes)):
            if vol > 0:
                volume_weighted_prices.extend([price] * int(vol / 1000000))  # 以百萬股為權重
        
        if volume_weighted_prices:
            volume_weighted_support = sorted(volume_weighted_prices)[len(volume_weighted_prices)//4]  # 25%分位數
            volume_weighted_resistance = sorted(volume_weighted_prices)[len(volume_weighted_prices)*3//4]  # 75%分位數
        else:
            volume_weighted_support = recent_low
            volume_weighted_resistance = recent_high
        
        # 綜合支撐壓力位
        support_candidates = [recent_low, ma20, volume_weighted_support]
        resistance_candidates = [recent_high, volume_weighted_resistance]
        
        # 選擇最接近當前價格的支撐位
        support = max([s for s in support_candidates if s <= current_price * 1.02])  # 允許2%誤差
        resistance = min([r for r in resistance_candidates if r >= current_price * 0.98])  # 允許2%誤差
        
        # 判斷是否在支撐附近
        support_distance = (current_price - support) / support if support > 0 else 1
        near_support = 0 <= support_distance <= 0.05  # 在支撐上方5%以內
        
        # 判斷是否接近突破
        resistance_distance = (resistance - current_price) / current_price if resistance > 0 else 1
        near_breakout = 0 <= resistance_distance <= 0.03  # 距離壓力3%以內
        
        support_analysis = {
            'support': support,
            'resistance': resistance,
            'current_price': current_price,
            'support_distance': support_distance,
            'resistance_distance': resistance_distance,
            'near_support': near_support,
            'near_breakout': near_breakout,
            'ma5': ma5,
            'ma10': ma10,
            'ma20': ma20,
            'recent_high': recent_high,
            'recent_low': recent_low
        }
        
        return support, resistance, near_support, support_analysis
        
    except Exception as e:
        return None, None, False, {}

def generate_trading_signals(stock_id, date, broker_data, broker_features, price_data, 
                           enable_support_filter=True, day_trading_threshold=5, stable_threshold=3):
    """
    生成交易訊號
    
    參數:
    - enable_support_filter: 是否啟用支撐線過濾
    - day_trading_threshold: 隔日沖權重門檻
    - stable_threshold: 穩健券商權重門檻
    """
    
    # 計算隔日沖權重
    total_weight, weight_analysis, details = calculate_day_trading_weight(
        stock_id, date, broker_data, broker_features)
    
    if total_weight == 0:
        return None
    
    # 支撐壓力分析
    support, resistance, near_support, support_analysis = calculate_support_resistance_enhanced(
        stock_id, date, price_data)
    
    signals = []
    
    # 策略1: 隔日沖倒貨反彈 (負分券商大量賣出)
    if weight_analysis['day_trading_sell'] > day_trading_threshold:
        # 檢查支撐線條件 (如果啟用)
        if not enable_support_filter or near_support:
            signal_strength = min(100, weight_analysis['day_trading_sell'] * 10)
            signals.append({
                'strategy': 'REVERSAL',
                'signal_strength': signal_strength,
                'reason': f"隔日沖倒貨 (賣方權重:{weight_analysis['day_trading_sell']:.1f})",
                'weight_analysis': weight_analysis,
                'support_analysis': support_analysis,
                'details': details
            })
    
    # 策略2: 隔日沖拉抬跟進 (負分券商大量買進)
    if weight_analysis['day_trading_buy'] > day_trading_threshold:
        signal_strength = min(100, weight_analysis['day_trading_buy'] * 8)
        signals.append({
            'strategy': 'FOLLOW_DAY_TRADING',
            'signal_strength': signal_strength,
            'reason': f"隔日沖拉抬 (買方權重:{weight_analysis['day_trading_buy']:.1f})",
            'weight_analysis': weight_analysis,
            'support_analysis': support_analysis,
            'details': details
        })
    
    # 策略3: 穩健券商跟進 (正分券商大量買進)
    if weight_analysis['stable_buy'] > stable_threshold:
        signal_strength = min(100, weight_analysis['stable_buy'] * 6)
        signals.append({
            'strategy': 'FOLLOW_STABLE',
            'signal_strength': signal_strength,
            'reason': f"穩健券商買進 (買方權重:{weight_analysis['stable_buy']:.1f})",
            'weight_analysis': weight_analysis,
            'support_analysis': support_analysis,
            'details': details
        })
    
    # 策略4: 綜合權重突破 (總權重指數高)
    if total_weight > day_trading_threshold + stable_threshold:
        signal_strength = min(100, total_weight * 5)
        signals.append({
            'strategy': 'COMBINED',
            'signal_strength': signal_strength,
            'reason': f"綜合權重突破 (總指數:{total_weight:.1f})",
            'weight_analysis': weight_analysis,
            'support_analysis': support_analysis,
            'details': details
        })
    
    # 返回最強訊號
    if signals:
        return max(signals, key=lambda x: x['signal_strength'])
    else:
        return None

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

def run_enhanced_day_trading_backtest(override_config=None, silent=False):
    """執行增強版隔日沖策略回測"""
    
    # 1. 載入資料與設定
    data = analyze_momentum.load_stock_data_wrapper('stock_data.json')
    data = preprocess_data(data)
    stock_names = load_stock_names()
    broker_features = load_broker_features()
    
    _config = load_config()
    if override_config: 
        _config.update(override_config)

    starting_cash = _config.get('STARTING_CASH', 1000000)
    
    # 策略參數
    max_positions = 5
    enable_support_filter = _config.get('ENABLE_SUPPORT_FILTER', True)  # 支撐線過濾開關
    day_trading_threshold = _config.get('DAY_TRADING_THRESHOLD', 5)     # 隔日沖權重門檻
    stable_threshold = _config.get('STABLE_THRESHOLD', 3)               # 穩健券商權重門檻
    signal_threshold = _config.get('SIGNAL_THRESHOLD', 30)              # 訊號強度門檻
    
    # 回測期間設定
    all_dates = sorted(list(set(d for sid in data for d in data[sid].get('price', {}))))
    if not all_dates: 
        return None
    
    end_idx = len(all_dates) - 1
    start_idx = max(0, end_idx - 60)  # 約3個月交易日
    
    # 不同策略的交易參數
    strategy_params = {
        'REVERSAL': {
            'take_profit': 0.08,
            'stop_loss': -0.04,
            'hold_days': 3
        },
        'FOLLOW_DAY_TRADING': {
            'take_profit': 0.15,
            'stop_loss': -0.06,
            'hold_days': 5
        },
        'FOLLOW_STABLE': {
            'take_profit': 0.12,
            'stop_loss': -0.05,
            'hold_days': 7
        },
        'COMBINED': {
            'take_profit': 0.20,
            'stop_loss': -0.08,
            'hold_days': 10
        }
    }

    # 2. 初始化帳戶
    cash = starting_cash
    total_invested = starting_cash
    portfolio = {} 
    transactions = [] 
    
    # 策略績效追蹤
    strategy_performance = {
        'REVERSAL': {'trades': [], 'total_return': 0},
        'FOLLOW_DAY_TRADING': {'trades': [], 'total_return': 0},
        'FOLLOW_STABLE': {'trades': [], 'total_return': 0},
        'COMBINED': {'trades': [], 'total_return': 0}
    }
    
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
            params = strategy_params[strategy]
            
            if gain >= params['take_profit']:
                sell_reason = f"{strategy}獲利了結 (+{gain:.1%})"
            elif gain <= params['stop_loss']:
                sell_reason = f"{strategy}停損 ({gain:.1%})"
            elif hold_days >= params['hold_days']:
                sell_reason = f"{strategy}到期賣出 ({gain:.1%})"
            
            if sell_reason:
                to_sell.append((sid, sell_reason, gain))

        # 執行賣出
        for sid, reason, gain in to_sell:
            position = portfolio[sid]
            sell_shares = position['shares']
            current_price = data[sid]['price'][current_date]['close']
            sell_value = sell_shares * current_price * 0.998  # 扣除交易成本
            cash += sell_value
            
            strategy = position['strategy']
            
            # 記錄策略績效
            strategy_performance[strategy]['trades'].append(gain)
            strategy_performance[strategy]['total_return'] += gain
            
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
                'strategy': strategy
            })
            
            del portfolio[sid]
            
            if not silent:
                print(f"[{current_date}] 賣出 {sid} {sell_shares}股 @ {current_price:.2f} ({reason})")

        # 檢查買進條件
        if len(portfolio) < max_positions:
            # 掃描所有股票尋找訊號
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
                
                # 載入券商資料並生成訊號
                broker_data = load_broker_data(sid)
                if not broker_data:
                    continue
                
                signal = generate_trading_signals(
                    sid, current_date, broker_data, broker_features, data[sid]['price'],
                    enable_support_filter, day_trading_threshold, stable_threshold)
                
                if signal and signal['signal_strength'] >= signal_threshold:
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

    if not silent:
        print(f"\n=== 增強版隔日沖策略回測結果 ===")
        print(f"回測期間: {all_dates[start_idx]} ~ {all_dates[-1]} ({days}天)")
        print(f"初始資金: {starting_cash:,.0f}")
        print(f"最終價值: {final_value:,.0f}")
        print(f"總報酬率: {total_return:.2%}")
        print(f"年化報酬率: {annualized_return:.2%}")
        print(f"交易次數: {len(transactions)}")
        print(f"支撐線過濾: {'啟用' if enable_support_filter else '停用'}")
        
        print(f"\n各策略績效分析:")
        for strategy, perf in strategy_performance.items():
            if perf['trades']:
                avg_return = sum(perf['trades']) / len(perf['trades'])
                win_rate = len([t for t in perf['trades'] if t > 0]) / len(perf['trades'])
                print(f"{strategy}:")
                print(f"  交易次數: {len(perf['trades'])}")
                print(f"  平均報酬: {avg_return:.2%}")
                print(f"  勝率: {win_rate:.1%}")
                print(f"  總貢獻: {perf['total_return']:.2%}")

    return {
        'total_return': total_return,
        'annualized_return': annualized_return,
        'final_value': final_value,
        'transactions': transactions,
        'days': days,
        'strategy_performance': strategy_performance,
        'config': {
            'enable_support_filter': enable_support_filter,
            'day_trading_threshold': day_trading_threshold,
            'stable_threshold': stable_threshold,
            'signal_threshold': signal_threshold
        }
    }

if __name__ == "__main__":
    print("執行增強版隔日沖策略回測...")
    
    # 測試不同參數組合
    configs = [
        {'ENABLE_SUPPORT_FILTER': True, 'DAY_TRADING_THRESHOLD': 5, 'STABLE_THRESHOLD': 3},
        {'ENABLE_SUPPORT_FILTER': False, 'DAY_TRADING_THRESHOLD': 5, 'STABLE_THRESHOLD': 3},
        {'ENABLE_SUPPORT_FILTER': True, 'DAY_TRADING_THRESHOLD': 3, 'STABLE_THRESHOLD': 2}
    ]
    
    best_result = None
    best_return = -1
    
    for i, config in enumerate(configs):
        print(f"\n=== 測試配置 {i+1} ===")
        result = run_enhanced_day_trading_backtest(config)
        if result and result['annualized_return'] > best_return:
            best_return = result['annualized_return']
            best_result = result
    
    if best_result:
        print(f"\n=== 最佳配置結果 ===")
        print(f"年化報酬率: {best_result['annualized_return']:.2%}")
        print(f"配置參數: {best_result['config']}")
        
        print(f"\n各策略個別績效:")
        for strategy, perf in best_result['strategy_performance'].items():
            if perf['trades']:
                avg_return = sum(perf['trades']) / len(perf['trades'])
                print(f"{strategy}: {len(perf['trades'])}次交易, 平均報酬{avg_return:.2%}, 總貢獻{perf['total_return']:.2%}")