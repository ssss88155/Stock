import backtest_momentum
import json
import os

def update_to_new_best():
    # 使用 543% ROI 的新設定
    new_best_cfg = {
      "BUY_DATES": "DAILY",
      "MOMENTUM_EXIT_THRESHOLD": 30,
      "TAKE_PROFIT_HALF_THRESHOLD": 0.1616067800219892,
      "DAILY_INVEST_POOL": 300000,
      "STARTING_CASH": 2000000,
      "TOP_N": 10,
      "BUY_SCORE_THRESHOLD": 70,
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
        "WEIGHT_HANDOVER": 7
      }
    }

    print(f"正在執行最終優化回測（ROI 目標 543%）...")
    
    res = backtest_momentum.run_backtest(override_config=new_best_cfg, silent=True)
    
    if res:
        print(f"回測完成！實際 ROI: {res['roi']:.2%}")
        
        output_dir = r"C:\jupyter_notebook\ai_twstock\temp_data"
        
        with open(os.path.join(output_dir, 'best_strategy_config.json'), 'w', encoding='utf-8') as f:
            json.dump(new_best_cfg, f, ensure_ascii=False, indent=2)
            
        with open(os.path.join(output_dir, 'best_strategy_results.json'), 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
            
        if 'transactions' in res:
            with open(os.path.join(output_dir, 'best_transactions.json'), 'w', encoding='utf-8') as f:
                json.dump(res['transactions'], f, ensure_ascii=False, indent=2)
        
        # 更新演算法說明
        desc_path = os.path.join(output_dir, 'algorithm_description.txt')
        algo_desc = f"""
        優化後的演算法說明 (最新優化版 - ROI: {res['roi']:.2%}):
        1. 評分邏輯 (Scoring Logic):
           - 權重分配：漲幅({new_best_cfg['WEIGHTS']['WEIGHT_GAIN']}%)、成交量({new_best_cfg['WEIGHTS']['WEIGHT_VOLUME']}%)、VCP({new_best_cfg['WEIGHTS']['WEIGHT_VCP']}%)。
           - 降低了法人(外資/投信)權重，更專注於純粹的價量動能。
        
        2. 二道門檻 - 產業集群過濾 (Sector Filter):
           - 僅買入當日高分標的中，所屬產業排名前 {new_best_cfg['INDUSTRY_FILTER_TOP_N']} 大的標的。
           - 此舉大幅減少了盤整期或單打獨鬥的雜訊訊號。
           
        3. 交易規則:
           - 停損 (Stop Loss): {new_best_cfg['STOP_LOSS_THRESHOLD']:.1%} (極緊湊停損，快速汰弱留強)。
           - 移動停扣 (Trailing Stop): {new_best_cfg['TRAILING_STOP_THRESHOLD']:.1%}。
        """
        with open(desc_path, 'w', encoding='utf-8') as f:
            f.write(algo_desc.strip())
            
        print("已更新 temp_data 中的最佳化檔案。")

if __name__ == "__main__":
    update_to_new_best()
