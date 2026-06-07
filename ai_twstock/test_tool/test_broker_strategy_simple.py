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
            
            print("[OK] 成功載入 2330 券商資料")
            
            if 'trading_daily_report' in data:
                dates = list(data['trading_daily_report'].keys())
                print(f"[OK] 包含 {len(dates)} 個交易日資料")
                
                # 檢查最新一天的資料結構
                latest_date = max(dates)
                latest_data = data['trading_daily_report'][latest_date]
                
                print(f"[OK] 最新日期: {latest_date}")
                
                if 'top_buyers' in latest_data:
                    print(f"[OK] 主要買方: {len(latest_data['top_buyers'])} 筆")
                    # 顯示前3大買方
                    for i, buyer in enumerate(latest_data['top_buyers'][:3]):
                        print(f"  {i+1}. {buyer.get('trader', 'N/A')} - 淨買: {buyer.get('net', 0):,} 股")
                
                if 'top_sellers' in latest_data:
                    print(f"[OK] 主要賣方: {len(latest_data['top_sellers'])} 筆")
                    # 顯示前3大賣方
                    for i, seller in enumerate(latest_data['top_sellers'][:3]):
                        print(f"  {i+1}. {seller.get('trader', 'N/A')} - 淨賣: {seller.get('net_s', 0):,} 股")
                
                return True
            else:
                print("[ERROR] 資料格式不正確")
                return False
                
        except Exception as e:
            print(f"[ERROR] 載入失敗: {e}")
            return False
    else:
        print(f"[ERROR] 找不到檔案: {test_file}")
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
    print(f"[OK] 券商評分: {score:.1f} 分")
    
    # 分析評分組成
    print("評分組成分析:")
    print("- 外資淨買: 800,000 股 (港麥格理)")
    print("- 本土大券商淨買: 800,000 股 (群益+凱基)")
    print("- 高價買進券商: 2 家")
    print("- 外資淨賣: 600,000 股 (瑞銀)")
    
    return score > 0

def test_stock_data_loading():
    """測試股票資料載入"""
    print("\n=== 測試股票資料載入 ===")
    
    try:
        data = analyze_momentum.load_stock_data_wrapper('stock_data.json')
        print(f"[OK] 成功載入股票資料，包含 {len(data)} 檔股票")
        
        # 檢查台積電資料
        if '2330' in data:
            stock_data = data['2330']
            if 'price' in stock_data:
                dates = list(stock_data['price'].keys())
                print(f"[OK] 2330 包含 {len(dates)} 個交易日價格資料")
                
                # 檢查最新價格資料結構
                latest_date = max(dates)
                latest_price = stock_data['price'][latest_date]
                print(f"[OK] 最新日期 {latest_date}: 收盤價 {latest_price.get('close', 'N/A')}")
                
                return True
            else:
                print("[ERROR] 缺少價格資料")
                return False
        else:
            print("[ERROR] 找不到 2330 資料")
            return False
            
    except Exception as e:
        print(f"[ERROR] 載入失敗: {e}")
        return False

def main():
    """主測試函數"""
    print("券商策略測試程式")
    print("=" * 50)
    
    tests = [
        ("券商資料載入", test_broker_data_loading),
        ("股票資料載入", test_stock_data_loading),
        ("券商評分邏輯", test_simple_broker_score)
    ]
    
    passed = 0
    total = len(tests)
    
    for name, test in tests:
        try:
            print(f"\n執行測試: {name}")
            if test():
                passed += 1
                print(f"[PASS] {name} 測試通過")
            else:
                print(f"[FAIL] {name} 測試失敗")
        except Exception as e:
            print(f"[ERROR] {name} 測試異常: {e}")
    
    print("\n" + "=" * 50)
    print(f"測試結果: {passed}/{total} 通過")
    
    if passed == total:
        print("[SUCCESS] 所有測試通過，可以進行完整回測")
        return True
    else:
        print("[WARNING] 部分測試失敗，需要修正問題")
        return False

if __name__ == "__main__":
    success = main()
    if success:
        print("\n準備執行簡化版回測...")
        # 這裡可以加入簡化版回測邏輯
    else:
        print("\n請先修正測試問題再進行回測")