import backtest_momentum
import json
import os
import random

def run_optimization(iterations=50):
    best_roi = -float('inf')
    best_config = None
    best_results = None

    # 定義基礎設定
    base_cfg = {
        'BUY_DATES': 'DAILY',
        'MOMENTUM_EXIT_THRESHOLD': 30,
        'TAKE_PROFIT_HALF_THRESHOLD': 0.15,
        'DAILY_INVEST_POOL': 300000, # 稍微增加每日投入，提高資金利用率
        'STARTING_CASH': 2000000,
        'TOP_N': 10 # 增加標的數量，分散風險
    }

    print(f"Starting optimization for {iterations} iterations...")

    # 包含一個強勢的基礎組合作為起點
    trend_following = {
        "weights": {"WEIGHT_GAIN": 40, "WEIGHT_VOLUME": 20, "WEIGHT_FOREIGN": 10, "WEIGHT_SITC": 10, "WEIGHT_VCP": 5, "WEIGHT_BREAKOUT": 15, "WEIGHT_HANDOVER": 0},
        "params": {"BUY_SCORE_THRESHOLD": 85, "STOP_LOSS_THRESHOLD": -0.05, "TRAILING_STOP_THRESHOLD": -0.15}
    }

    for i in range(iterations):
        if i == 0:
            weights = trend_following['weights']
            params = trend_following['params']
        else:
            # 圍繞 TrendFollowing 進行變異
            weights = {
                "WEIGHT_GAIN": max(0, trend_following['weights']['WEIGHT_GAIN'] + random.randint(-15, 15)),
                "WEIGHT_VOLUME": max(0, trend_following['weights']['WEIGHT_VOLUME'] + random.randint(-10, 10)),
                "WEIGHT_FOREIGN": max(0, trend_following['weights']['WEIGHT_FOREIGN'] + random.randint(-10, 10)),
                "WEIGHT_SITC": max(0, trend_following['weights']['WEIGHT_SITC'] + random.randint(-10, 10)),
                "WEIGHT_VCP": max(0, trend_following['weights']['WEIGHT_VCP'] + random.randint(-10, 10)),
                "WEIGHT_BREAKOUT": max(0, trend_following['weights']['WEIGHT_BREAKOUT'] + random.randint(-10, 10)),
                "WEIGHT_HANDOVER": max(0, trend_following['weights']['WEIGHT_HANDOVER'] + random.randint(0, 30))
            }
            # 正規化
            total_w = sum(weights.values())
            for k in weights: weights[k] = int(weights[k] * 100 / total_w)
            weights["WEIGHT_HANDOVER"] += (100 - sum(weights.values()))

            params = {
                "BUY_SCORE_THRESHOLD": random.randint(70, 95),
                "STOP_LOSS_THRESHOLD": random.uniform(-0.08, -0.03),
                "TRAILING_STOP_THRESHOLD": random.uniform(-0.15, -0.08),
                "TAKE_PROFIT_HALF_THRESHOLD": random.uniform(0.10, 0.25),
                "MOMENTUM_EXIT_THRESHOLD": random.randint(20, 50)
            }

        cfg = base_cfg.copy()
        cfg.update(params)
        cfg['WEIGHTS'] = weights

        # 執行回測
        res = backtest_momentum.run_backtest(override_config=cfg, silent=True)
        
        if res:
            roi = res['roi']
            alpha = roi - res['bench_roi']
            # 我們以 ROI 為主，但也考慮 Alpha
            if roi > best_roi:
                best_roi = roi
                best_config = cfg
                best_results = res
                print(f"New Best! Iter {i+1}: ROI={roi:.2%}, Alpha={alpha:.2%}")

    # 記錄最終結果
    if best_config:
        print("\n" + "="*50)
        print("OPTIMIZATION COMPLETE")
        print(f"Best ROI: {best_results['roi']:.2%}")
        print(f"Benchmark ROI: {best_results['bench_roi']:.2%}")
        print(f"Alpha: {best_results['roi'] - best_results['bench_roi']:.2%}")
        print("Best Weights:", json.dumps(best_config['WEIGHTS'], indent=2))
        print("Best Params:", {k: v for k, v in best_config.items() if k != 'WEIGHTS'})
        
        # 儲存最佳組合
        output_dir = r"C:\jupyter_notebook\ai_twstock\temp_data"
        os.makedirs(output_dir, exist_ok=True)
        
        with open(os.path.join(output_dir, 'best_strategy_config.json'), 'w', encoding='utf-8') as f:
            json.dump(best_config, f, ensure_ascii=False, indent=2)
            
        with open(os.path.join(output_dir, 'best_strategy_results.json'), 'w', encoding='utf-8') as f:
            json.dump(best_results, f, ensure_ascii=False, indent=2)

        # 儲存交易紀錄
        if 'transactions' in best_results:
            with open(os.path.join(output_dir, 'best_transactions.json'), 'w', encoding='utf-8') as f:
                json.dump(best_results['transactions'], f, ensure_ascii=False, indent=2)
        
        # 儲存演算法說明
        algo_desc = """
        優化後的演算法說明：
        1. 評分邏輯 (Scoring Logic):
           - 結合漲幅 (40%)、成交量突破 (20%)、外資/投信連買、VCP 形態與換手盤整。
           - VCP 形態新增「量縮 (Volume Dry-up)」檢查，收斂末端成交量萎縮會額外加分。
           - 法人共識 (外資與投信同步) 給予 1.5 倍權重加成。
           - 相對強度 (RS) 強化濾網：
             - 弱於大盤 (RS < 0) 的標的分數打 0.3 ~ 0.6 折。
             - 優於大盤 (RS > 5%) 的標的分數加成 1.5 倍。
             - 極強勢標的 (RS > 10%) 的標的分數加成 2.0 倍。
           
        2. 買入規則 (Entry Rules):
           - T-1 日收盤後分析，T 日開盤買入。
           - 市場濾網 (Market Filter):
             - 指數趨勢 (0050 > MA20) 且市場廣度 (Breadth > 15%)。
             - 若指數弱勢，廣度要求提高至 60%。
           - 每日投入上限調高至 30 萬，最大持股數量 10 檔。
           
        3. 賣出規則 (Exit Rules):
           - 停損 (Stop Loss): 約 -5% ~ -8% 動態停損。
           - 移動停利 (Trailing Stop): 從最高點回落約 15%。
           - 分批停利: 獲利達到 13% ~ 15% 時先賣出一半。
           - 動能減退: 分數低於門檻 (MOMENTUM_EXIT_THRESHOLD) 時全數出清。
        """
        with open(os.path.join(output_dir, 'algorithm_description.txt'), 'w', encoding='utf-8') as f:
            f.write(algo_desc.strip())
        
    return best_config

if __name__ == "__main__":
    run_optimization(iterations=50)
