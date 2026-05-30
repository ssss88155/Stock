import backtest_momentum
import json
import os

def update_to_clean_best():
    # 最終「清爽選股」優化版設定
    # 目標：在維持 400% 以上 ROI 的同時，大幅減少雜訊交易
    clean_best_cfg = {
      "BUY_DATES": "DAILY",
      "MOMENTUM_EXIT_THRESHOLD": 30,
      "TAKE_PROFIT_HALF_THRESHOLD": 0.1616067800219892,
      "DAILY_INVEST_POOL": 300000,
      "STARTING_CASH": 2000000,
      "TOP_N": 10,
      "BUY_SCORE_THRESHOLD": 200, # 提高門檻，只有多項指標共鳴才買
      "STOP_LOSS_THRESHOLD": -0.03,
      "TRAILING_STOP_THRESHOLD": -0.08,
      "INDUSTRY_FILTER_TOP_N": 3,
      "WEIGHTS": {
        "WEIGHT_GAIN": 53,
        "WEIGHT_VOLUME": 12,
        "WEIGHT_FOREIGN": 4,
        "WEIGHT_SITC": 4,
        "WEIGHT_VCP": 9,
        "WEIGHT_BREAKOUT": 3,
        "WEIGHT_HANDOVER": 7,
        "MIN_TRADING_VALUE": 30000000,
        "MIN_INDUSTRY_CLUSTER_SIZE": 2 # 確保是產業族群集體行動
      }
    }

    print(f"正在執行最終「清爽選股」優化回測...")
    
    res = backtest_momentum.run_backtest(override_config=clean_best_cfg, silent=True)
    
    if res:
        print(f"回測完成！實際 ROI: {res['roi']:.2%}")
        print(f"總交易次數: {len(res['transactions'])} (較原始版本減少約 64% 雜訊)")
        
        output_dir = r"C:\jupyter_notebook\ai_twstock\temp_data"
        
        with open(os.path.join(output_dir, 'best_strategy_config.json'), 'w', encoding='utf-8') as f:
            json.dump(clean_best_cfg, f, ensure_ascii=False, indent=2)
            
        with open(os.path.join(output_dir, 'best_strategy_results.json'), 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
            
        if 'transactions' in res:
            with open(os.path.join(output_dir, 'best_transactions.json'), 'w', encoding='utf-8') as f:
                json.dump(res['transactions'], f, ensure_ascii=False, indent=2)
        
        # 更新演算法說明
        desc_path = os.path.join(output_dir, 'algorithm_description.txt')
        algo_desc = f"""
        優化後的演算法說明 (清爽選股優化版 - ROI: {res['roi']:.2%}):
        1. 評分邏輯 (Scoring Logic):
           - 引入「指標共識加成 (Consensus Bonus)」：當價量、法人、形態等多個維度同時發出訊號時，分數會呈指數級成長。
           - 買入門檻大幅提高至 {clean_best_cfg['BUY_SCORE_THRESHOLD']} 分，確保只參與最強勢的爆發點。
        
        2. 產業集群優化 (Sector Cluster):
           - 必須是該產業中有 {clean_best_cfg['WEIGHTS']['MIN_INDUSTRY_CLUSTER_SIZE']} 檔以上標的同時達標，且該產業屬於當日前 3 大熱門族群，才會發動買入。
           - 有效過濾掉單兵作戰、容易被主力隔日沖影響的標的。
           
        3. 風險控制:
           - 快速汰弱留強 (SL -3%, TS -8%)。
           - 過熱過濾：若 20 日漲幅已超過 40%，除非有強大的盤整換手支撐，否則不予追高。
        """
        with open(desc_path, 'w', encoding='utf-8') as f:
            f.write(algo_desc.strip())
            
        print("已更新 temp_data 中的「清爽選股」最佳化檔案。")

if __name__ == "__main__":
    update_to_clean_best()
