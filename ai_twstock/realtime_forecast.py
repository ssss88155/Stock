import sys
import os

# 將 lib 目錄加入 Python 路徑
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
import forecast_lib

# 將 ai_twstock 目錄加入 Python 路徑
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__))))
import analyze_momentum

def run_realtime_forecast():
    """
    執行即時預測，尋找今日開盤進場標的。
    """
    print("\n" + "="*60)
    print(" [開盤進場預測日誌] ")
    print("="*60)
    
    # 1. 嘗試連線 SDK 獲取餘額
    sdk = forecast_lib.login_esun_sdk()
    available_cash = 30000.0 # 預設流動資金
    
    if sdk:
        balance_info = forecast_lib.get_balance_info(sdk)
        if balance_info:
            try:
                # 這裡需要根據玉山 SDK 實際回傳格式抓取可用餘額，目前先嘗試常見欄位
                if isinstance(balance_info, dict) and 'available_balance' in balance_info:
                    available_cash = float(balance_info['available_balance'])
                    print(f"  [INFO] 成功從 SDK 獲取可用資金: {available_cash:,.0f}")
                else:
                    print(f"  [INFO] SDK 已連線，使用預設資金: {available_cash:,.0f}")
            except:
                print(f"  [INFO] SDK 餘額解析失敗，使用預設資金: {available_cash:,.0f}")
    else:
        print(f"  [INFO] SDK 未連線 (或是連線失敗)，使用預設資金: {available_cash:,.0f}")

    # 2. 執行分析 (T-1 資料預測今日 T 開盤)
    buy_candidates, best_cfg, last_data_date = forecast_lib.find_buy_candidates_realtime()
    
    if not buy_candidates:
        print(f"\n  [SKIPPED] {last_data_date} No strong candidates found.")
        return

    # 3. 計算分配金額與股數 (模擬回測買入日誌格式)
    num_to_buy = len(buy_candidates)
    target_per_stock = available_cash / num_to_buy if num_to_buy > 0 else 0
    
    print(f"\n  [分析基準日 T-1]: {last_data_date}")
    print(f"  [預期進場日 T  ]: 今日開盤")
    print("-" * 110)

    for res in buy_candidates:
        price = res['close'] # T-1 收盤
        if price <= 0: continue
        
        expected_shares = int(target_per_stock // price)
        
        note = ""
        if res.get('handover_ok'): note += "[換手] "
        if res.get('vcp_ok'): note += "[VCP] "
        
        # 模擬 output.txt 的風格
        print(f"  [買入] {last_data_date} {res['stock_id']} {res['name']} 預期股數: {expected_shares:,} 參考價格: {price:.2f} 分數: {res['score']:.1f} {note}")
    
    print("-" * 110)
    print(f"\n[策略配置參考] 門檻: {best_cfg.get('BUY_SCORE_THRESHOLD')}, 每日限額: {best_cfg.get('MAX_DAILY_BUY')}")

if __name__ == "__main__":
    run_realtime_forecast()
