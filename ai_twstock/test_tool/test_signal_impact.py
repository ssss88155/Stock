import json
import os
import sys

# 將父目錄加入路徑以引用 analyze_momentum
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest_momentum_day_trading

def test_single_stock_streaming(target_sid):
    print(f"=== 深入測試股票: {target_sid} (串流提取模式) ===")
    
    micro_features = backtest_momentum_day_trading.load_micro_features()
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'stock_data_micro.json')
    
    if not os.path.exists(path):
        print("找不到 stock_data_micro.json")
        return

    print(f"正在從大型檔案中提取 {target_sid} 的數據...")
    
    target_data_str = ""
    search_pattern = f'"{target_sid}":'
    
    with open(path, 'r', encoding='utf-8') as f:
        found = False
        while True:
            chunk = f.read(1024 * 1024) # 1MB chunk
            if not chunk:
                break
            
            if search_pattern in chunk:
                pos = f.tell() - len(chunk)
                f.seek(pos + chunk.find(search_pattern) + len(search_pattern))
                
                brace_count = 0
                started = False
                while True:
                    char = f.read(1)
                    if not char: break
                    target_data_str += char
                    if char == '{':
                        brace_count += 1
                        started = True
                    elif char == '}':
                        brace_count -= 1
                    
                    if started and brace_count == 0:
                        found = True
                        break
                if found: break

        if not found:
            print(f"在檔案中找不到股票代號 {target_sid}")
            return

    try:
        # 尋找第一個 { 和最後一個 } 確保 JSON 完整
        start_idx = target_data_str.find('{')
        end_idx = target_data_str.rfind('}')
        if start_idx != -1 and end_idx != -1:
            json_str = target_data_str[start_idx:end_idx+1]
            target_data = json.loads(json_str)
            print(f"成功提取 {target_sid} 數據。")
        else:
            print("無法定位 JSON 物件邊界")
            return
    except Exception as e:
        print(f"JSON 解析失敗: {e}")
        return

    stock_dict = {target_sid: target_data}
    dates_price = set(target_data.get('price', {}).keys())
    dates_report = set(target_data.get('trading_daily_report', {}).keys())
    all_dates = sorted(list(dates_price | dates_report))
    
    print(f"掃描最近 100 天的券商訊號...")
    found_signals = 0
    for i in range(max(0, len(all_dates) - 100), len(all_dates)):
        date = all_dates[i]
        
        signal = backtest_momentum_day_trading.calculate_day_trading_signal(target_sid, date, stock_dict, micro_features)
        
        if signal['type']:
            found_signals += 1
            print(f"[{date}] 訊號: {signal['type']} 強度: {signal['strength']:.1f} 原因: {signal['reason']}")
            
            if i + 1 < len(all_dates):
                next_date = all_dates[i+1]
                p_curr = target_data.get('price', {}).get(date, {}).get('close', 0)
                p_next = target_data.get('price', {}).get(next_date, {}).get('close', 0)
                if p_curr > 0 and p_next > 0:
                    change = (p_next - p_curr) / p_curr
                    print(f"      -> 隔日收盤表現: {change:+.2%}")

    if found_signals == 0:
        print("這段期間沒有觸發任何券商訊號。")

if __name__ == "__main__":
    test_single_stock_streaming('1101')
