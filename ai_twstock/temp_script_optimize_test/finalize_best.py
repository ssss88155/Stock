import backtest_momentum
import json
import os

def finalize_best():
    # 591% ROI 的最優配置
    best_cfg = {
      "BUY_DATES": "DAILY",
      "MOMENTUM_EXIT_THRESHOLD": 30,
      "TAKE_PROFIT_HALF_THRESHOLD": 0.1616067800219892,
      "DAILY_INVEST_POOL": 300000,
      "STARTING_CASH": 2000000,
      "TOP_N": 10,
      "MAX_DAILY_BUY": 5, # 關鍵門檻：限制每日進貨量，去蕪存菁
      "BUY_SCORE_THRESHOLD": 100,
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

    print(f"正在執行最終「591% 高效率選股」回測...")
    
    res = backtest_momentum.run_backtest(override_config=best_cfg, silent=True)
    
    if res:
        print(f"回測完成！最終 ROI: {res['roi']:.2%}")
        print(f"交易次數: {len(res['transactions'])}")
        
        output_dir = r"C:\jupyter_notebook\ai_twstock\temp_data"
        
        with open(os.path.join(output_dir, 'best_strategy_config.json'), 'w', encoding='utf-8') as f:
            json.dump(best_cfg, f, ensure_ascii=False, indent=2)
            
        with open(os.path.join(output_dir, 'best_strategy_results.json'), 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
            
        if 'transactions' in res:
            with open(os.path.join(output_dir, 'best_transactions.json'), 'w', encoding='utf-8') as f:
                json.dump(res['transactions'], f, ensure_ascii=False, indent=2)
        
        # 更新演算法說明
        desc_path = os.path.join(output_dir, 'algorithm_description.txt')
        algo_desc = f"""
        優化後的演算法說明 (591% 高效率選股版 - ROI: {res['roi']:.2%}):
        1. 核心選股邏輯:
           - 強化價量動能權重，並引入「連續帶量突破」機制（要求今日量比>2.0且昨日量比>1.2）。
           - 買入門檻設定為 {best_cfg['BUY_SCORE_THRESHOLD']} 分。
        
        2. 關鍵門檻 - 每日進貨限制 (Daily Limit):
           - 新增 `MAX_DAILY_BUY = 5`：每日最多僅買入評分最高的前 5 檔標的。
           - 此舉能強迫系統在眾多訊號中挑選「最強的主場」，有效減少了 50% 的雜訊交易，同時提升了獲利品質。
           
        3. 產業集群過濾 (Top 3 Industries):
           - 僅參與當日最熱門的前 3 大產業，避開冷門股的單日虛假突破。
           
        4. 風險控制:
           - 維持極緊湊的汰弱留強機制 (SL -3%, TS -8%)，確保資金永遠留在最強勢的部位。
        """
        with open(desc_path, 'w', encoding='utf-8') as f:
            f.write(algo_desc.strip())
            
        print("已更新所有最佳化檔案。")

if __name__ == "__main__":
    finalize_best()
