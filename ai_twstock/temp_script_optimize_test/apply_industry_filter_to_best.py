import backtest_momentum
import json
import os

def apply_best_with_industry():
    # 1. 載入之前的 393% 最佳設定
    config_path = r"C:\jupyter_notebook\ai_twstock\temp_data\01_best_393%ROI_git20260530_221254\best_strategy_config.json"
    if not os.path.exists(config_path):
        print(f"找不到最佳設定檔！路徑: {config_path}")
        return
        
    with open(config_path, 'r', encoding='utf-8') as f:
        best_cfg = json.load(f)
    
    # 2. 加入產業過濾門檻 (Top 3)
    best_cfg['INDUSTRY_FILTER_TOP_N'] = 3
    
    print(f"正在執行包含產業過濾（Top 3）的最佳化回測...")
    
    # 3. 執行回測
    res = backtest_momentum.run_backtest(override_config=best_cfg, silent=True)
    
    if res:
        print(f"回測完成！新的 ROI: {res['roi']:.2%}")
        
        # 4. 儲存回 temp_data 作為新的 best 檔案
        output_dir = r"C:\jupyter_notebook\ai_twstock\temp_data"
        
        # 儲存 config
        with open(os.path.join(output_dir, 'best_strategy_config.json'), 'w', encoding='utf-8') as f:
            json.dump(best_cfg, f, ensure_ascii=False, indent=2)
            
        # 儲存 results
        with open(os.path.join(output_dir, 'best_strategy_results.json'), 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
            
        # 儲存交易紀錄
        if 'transactions' in res:
            with open(os.path.join(output_dir, 'best_transactions.json'), 'w', encoding='utf-8') as f:
                json.dump(res['transactions'], f, ensure_ascii=False, indent=2)
        
        # 5. 更新演算法說明
        desc_path = os.path.join(output_dir, 'algorithm_description.txt')
        if os.path.exists(desc_path):
            with open(desc_path, 'r', encoding='utf-8') as f:
                desc = f.read()
        else:
            desc = "優化後的演算法說明："
            
        if "產業集群過濾" not in desc:
            desc += "\n\n4. 產業集群過濾 (Sector Filter):\n   - 第二道門檻：僅買入當日通過初選標的中，所屬產業排名前 3 大的標的。"
            with open(desc_path, 'w', encoding='utf-8') as f:
                f.write(desc)
        
        print("已更新 temp_data 中的 best 檔案。")

if __name__ == "__main__":
    apply_best_with_industry()
