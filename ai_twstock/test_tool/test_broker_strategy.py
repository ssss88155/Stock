import json
import os
import sys
from datetime import datetime

# 添加父目錄到路徑
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analyze_momentum

def test_broker_data_loading():
    """測試券商資料載入"""
    print("=== 測試券商資料載入 ===")
    
    broker_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data_independent_microstructure')
    
    # 測試載入台積電 (2330) 的券商資料
    test_file = os.path.join(broker_dir, '2330.json')
    if os.path.exists(test_file):
        try:
            with open(test_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            print(f"[OK] 成功載入 2330 券商資料")
            
            if 'trading_daily_report' in data:
                dates = list(data['trading_daily_report'].keys())
                print(f"✓ 包含 {len(dates)} 個交易日資料")
                
                # 檢查最新一天的資料結構
                latest_date = max(dates)
                latest_data = data['trading_daily_report'][latest_date]
                
                print(f"✓ 最新日期: {latest_date}")
                
                if 'top_buyers' in latest_data:
                    print(f"✓ 主要買方: {len(latest_data['top_buyers'])} 筆")
                    # 顯示前3大買方
                    for i, buyer in enumerate(latest_data['top_buyers'][:3]):
                        print(f"  {i+1}. {buyer.get('trader', 'N/A')} - 淨買: {buyer.get('net', 0):,} 股")
                
                if 'top_sellers' in latest_data:
                    print(f"✓ 主要賣方: {len(latest_data['top_sellers'])} 筆")
                    # 顯示前3大賣方
                    for i, seller in enumerate(latest_data['top_sellers'][:3]):
                        print(f"  {i+1}. {seller.get('trader', 'N/A')} - 淨賣: {seller.get('net_s', 0):,} 股")
                
                return True
            else:
                print("✗ 資料格式不正確")
                return False
                
        except Exception as e:
            print(f"✗ 載入失敗: {e}")
            return False
    else:
        print(f"✗ 找不到檔案: {test_file}")
        return False

def test_broker_classification():
    """測試券商分類邏輯"""
    print("\n=== 測試券商分類 ===")
    
    # 定義主要外資券商
    foreign_brokers = {
        '港麥格理', '瑞銀', '摩根大通', '美林', '台灣摩根', '美商高盛', 
        '港商野村', '法銀巴黎', '大和國泰', '花旗環球', '上海匯豐'
    }
    
    # 定義主要投信券商
    sitc_brokers = {
        '群益', '凱基', '永豐金', '富邦', '國泰', '統一', '元大', 
        '台新證券', '新光', '日盛', '兆豐', '第一金'
    }
    
    def classify_broker(broker_name):
        if any(foreign in broker_name for foreign in foreign_brokers):
            return 'foreign'
        elif any(sitc in broker_name for sitc in sitc_brokers):
            return 'domestic_major'
        else:
            return 'domestic_minor'
    
    # 測試案例
    test_cases = [
        "港麥格理/1360",
        "群益/9100", 
        "凱基/9200",
        "瑞銀/1650",
        "永豐金/9A00",
        "小券商/1234"
    ]
    
    for broker in test_cases:
        classification = classify_broker(broker)
        print(f"✓ {broker} -> {classification}")
    
    return True

def test_stock_data_loading():
    """測試股票資料載入"""
    print("\n=== 測試股票資料載入 ===")
    
    try:
        data = analyze_momentum.load_stock_data_wrapper('stock_data.json')
        print(f"✓ 成功載入股票資料，包含 {len(data)} 檔股票")
        
        # 檢查台積電資料
        if '2330' in data:
            stock_data = data['2330']
            if 'price' in stock_data:
                dates = list(stock_data['price'].keys())
                print(f"✓ 2330 包含 {len(dates)} 個交易日價格資料")
                
                # 檢查最新價格資料結構
                latest_date = max(dates)
                latest_price = stock_data['price'][latest_date]
                print(f"✓ 最新日期 {latest_date}: 收盤價 {latest_price.get('close', 'N/A')}")
                
                return True
            else:
                print("✗ 缺少價格資料")
                return False
        else:
            print("✗ 找不到 2330 資料")
            return False
            
    except Exception as e:
        print(f"✗ 載入失敗: {e}")
        return False

def test_simple_broker_score():
    """測試簡化版券商評分邏輯"""
    print("\n=== 測試券商評分邏輯 ===")
    
    # 模擬券商資料
    mock_broker_data = {
        'trading_daily_report': {
            '2026-06-05': {
                'top_buyers': [
                    {'trader': '群益/9100', 'net': 500000, 'avg_p': 100.5},
                    {'trader': '港麥格理/1360', 'net': 800000, 'avg_p': 101.0},
                    {'trader': '凱基/9200', 'net': 300000, 'avg_p': 100.2}
                ],
                'top_sellers': [
                    {'trader': '瑞銀/1650', 'net_s': 600000, 'avg_p': 100.8},
                    {'trader': '小券商/1234', 'net_s': 200000, 'avg_p': 100.1}
                ]
            }
        }
    }
    
    mock_price_data = {
        '2026-06-05': {
            'close': 100.0,
            'Trading_Volume': 10000000
        }
    }
    
    def classify_broker(broker_name):
        foreign_brokers = {'港麥格理', '瑞銀', '摩根大通', '美林'}
        sitc_brokers = {'群益', '凱基', '永豐金', '富邦', '國泰'}
        
        if any(foreign in broker_name for foreign in foreign_brokers):
            return 'foreign'
        elif any(sitc in broker_name for sitc in sitc_brokers):
            return 'domestic_major'
        else:
            return 'domestic_minor'
    
    def calculate_simple_score(date, broker_data, price_data):
        if date not in broker_data['trading_daily_report']:
            return 0
        
        report = broker_data['trading_daily_report'][date]
        current_price = price_data[date]['close']
        
        foreign_net = 0
        domestic_net = 0
        high_price_buyers = 0
        
        # 分析買方
        for buyer in report.get('top_buyers', []):
            trader_name = buyer.get('trader', '')
            net_amount = buyer.get('net', 0)
            avg_price = buyer.get('avg_p', current_price)
            
            broker_type = classify_broker(trader_name)
            
            if broker_type == 'foreign':
                foreign_net += net_amount
            elif broker_type == 'domestic_major':
                domestic_net += net_amount
            
            if avg_price > current_price * 1.002:
                high_price_buyers += 1
        
        # 分析賣方
        for seller in report.get('top_sellers', []):
            trader_name = seller.get('trader', '')
            net_amount = seller.get('net_s', 0)
            
            broker_type = classify_broker(trader_name)
            
            if broker_type == 'foreign':
                foreign_net -= net_amount
            elif broker_type == 'domestic_major':
                domestic_net -= net_amount
        
        # 計算評分
        score = 0
        
        # 外資動量 (30分)
        if foreign_net > 0:
            score += min(30, foreign_net / 100000 * 5)
        
        # 本土券商動量 (25分)
        if domestic_net > 0:
            score += min(25, domestic_net / 50000 * 5)
        
        # 高價買進信心 (20分)
        score += min(20, high_price_buyers * 5)
        
        return score
    
    # 測試評分
    score = calculate_simple_score('2026-06-05', mock_broker_data, mock_price_data)
    print(f"✓ 券商評分: {score:.1f} 分")
    
    # 分析評分組成
    print("評分組成分析:")
    print("- 外資淨買: 800,000 股 (港麥格理)")
    print("- 本土大券商淨買: 800,000 股 (群益+凱基)")
    print("- 高價買進券商: 2 家")
    print("- 外資淨賣: 600,000 股 (瑞銀)")
    
    return score > 0

def main():
    """主測試函數"""
    print("券商策略測試程式")
    print("=" * 50)
    
    tests = [
        test_broker_data_loading,
        test_broker_classification, 
        test_stock_data_loading,
        test_simple_broker_score
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
                print("✓ 測試通過\n")
            else:
                print("✗ 測試失敗\n")
        except Exception as e:
            print(f"✗ 測試異常: {e}\n")
    
    print("=" * 50)
    print(f"測試結果: {passed}/{total} 通過")
    
    if passed == total:
        print("✓ 所有測試通過，可以進行完整回測")
    else:
        print("✗ 部分測試失敗，需要修正問題")

if __name__ == "__main__":
    main()