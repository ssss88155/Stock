import json
import sys
import os

def analyze_broker_features():
    """分析券商特徵，找出隔日沖相關券商"""
    
    # 載入券商特徵資料
    feature_file = r"C:\jupyter_notebook\ai_twstock\data\micro_feature_all.json"
    
    try:
        with open(feature_file, 'r', encoding='utf-8') as f:
            brokers = json.load(f)
        
        print(f"載入 {len(brokers)} 個券商資料")
        
        # 分析穩重指數分布
        stability_scores = [broker.get('穩重指數', 100) for broker in brokers]
        print(f"\n穩重指數統計:")
        print(f"最低: {min(stability_scores)}")
        print(f"最高: {max(stability_scores)}")
        print(f"平均: {sum(stability_scores)/len(stability_scores):.1f}")
        
        # 找出低穩重指數的券商 (可能是隔日沖)
        print(f"\n穩重指數 < 50 的券商:")
        low_stability = []
        for broker in brokers:
            stability = broker.get('穩重指數', 100)
            if stability < 50:
                low_stability.append(broker)
                print(f"{broker['id']} {broker['name']} (穩重指數:{stability}) - {broker.get('特性', '')[:80]}")
        
        # 搜尋特定關鍵字
        keywords = ['短線', '投機', '攻擊', '快進', '波段', '炒作', '當沖', '隔日']
        print(f"\n包含短線交易關鍵字的券商:")
        keyword_brokers = []
        for broker in brokers:
            feature = broker.get('特性', '')
            for keyword in keywords:
                if keyword in feature:
                    keyword_brokers.append(broker)
                    print(f"{broker['id']} {broker['name']} (穩重指數:{broker.get('穩重指數', 100)}) - {feature[:80]}")
                    break
        
        # 分析穩重指數分級
        print(f"\n穩重指數分級統計:")
        levels = {
            '極低 (0-20)': 0,
            '低 (21-40)': 0, 
            '中低 (41-60)': 0,
            '中等 (61-80)': 0,
            '高 (81-100)': 0
        }
        
        for broker in brokers:
            stability = broker.get('穩重指數', 100)
            if stability <= 20:
                levels['極低 (0-20)'] += 1
            elif stability <= 40:
                levels['低 (21-40)'] += 1
            elif stability <= 60:
                levels['中低 (41-60)'] += 1
            elif stability <= 80:
                levels['中等 (61-80)'] += 1
            else:
                levels['高 (81-100)'] += 1
        
        for level, count in levels.items():
            print(f"{level}: {count} 個券商")
        
        return low_stability, keyword_brokers
        
    except Exception as e:
        print(f"錯誤: {e}")
        return [], []

def find_day_trading_patterns():
    """從實際交易資料中找出隔日沖模式"""
    
    # 載入台積電的券商資料作為範例
    broker_file = r"C:\jupyter_notebook\ai_twstock\data_independent_microstructure\2330.json"
    
    try:
        with open(broker_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        daily_reports = data.get('trading_daily_report', {})
        dates = sorted(daily_reports.keys())[-10:]  # 最近10天
        
        print(f"\n分析台積電最近10天的券商交易模式:")
        
        # 追蹤券商的連續交易行為
        broker_tracking = {}
        
        for date in dates:
            report = daily_reports[date]
            
            # 記錄當日買方
            if 'top_buyers' in report:
                for buyer in report['top_buyers']:
                    trader = buyer.get('trader', '')
                    net = buyer.get('net', 0)
                    
                    if trader not in broker_tracking:
                        broker_tracking[trader] = []
                    broker_tracking[trader].append((date, 'BUY', net))
            
            # 記錄當日賣方
            if 'top_sellers' in report:
                for seller in report['top_sellers']:
                    trader = seller.get('trader', '')
                    net = seller.get('net_s', 0)
                    
                    if trader not in broker_tracking:
                        broker_tracking[trader] = []
                    broker_tracking[trader].append((date, 'SELL', net))
        
        # 分析可能的隔日沖模式
        print(f"\n可能的隔日沖模式 (買進後隔日賣出):")
        day_trading_candidates = []
        
        for trader, actions in broker_tracking.items():
            if len(actions) >= 2:
                # 排序交易記錄
                actions.sort(key=lambda x: x[0])
                
                # 檢查是否有買進後隔日賣出的模式
                for i in range(len(actions)-1):
                    current_date, current_action, current_amount = actions[i]
                    next_date, next_action, next_amount = actions[i+1]
                    
                    # 檢查是否為連續日期且動作相反
                    if (current_action == 'BUY' and next_action == 'SELL' and 
                        current_amount > 100000 and next_amount > 100000):
                        
                        day_trading_candidates.append({
                            'trader': trader,
                            'buy_date': current_date,
                            'sell_date': next_date,
                            'buy_amount': current_amount,
                            'sell_amount': next_amount
                        })
        
        for candidate in day_trading_candidates[:10]:
            print(f"{candidate['trader']}: {candidate['buy_date']} 買進 {candidate['buy_amount']:,} -> {candidate['sell_date']} 賣出 {candidate['sell_amount']:,}")
        
        return day_trading_candidates
        
    except Exception as e:
        print(f"錯誤: {e}")
        return []

if __name__ == "__main__":
    print("券商特徵分析工具")
    print("=" * 50)
    
    # 分析券商特徵
    low_stability, keyword_brokers = analyze_broker_features()
    
    # 分析實際交易模式
    day_trading_patterns = find_day_trading_patterns()
    
    print(f"\n總結:")
    print(f"低穩重指數券商: {len(low_stability)} 個")
    print(f"包含短線關鍵字券商: {len(keyword_brokers)} 個") 
    print(f"發現可能隔日沖模式: {len(day_trading_patterns)} 個")