import backtest_momentum
import json
import os

def run_industry_experiment():
    # 使用 393% ROI 的原始設定
    base_cfg = {
      "BUY_DATES": "DAILY",
      "MOMENTUM_EXIT_THRESHOLD": 30,
      "TAKE_PROFIT_HALF_THRESHOLD": 0.1616067800219892,
      "DAILY_INVEST_POOL": 300000,
      "STARTING_CASH": 2000000,
      "TOP_N": 10,
      "BUY_SCORE_THRESHOLD": 70,
      "STOP_LOSS_THRESHOLD": -0.031374706587833444,
      "TRAILING_STOP_THRESHOLD": -0.0842728515159677,
      "WEIGHTS": {
        "WEIGHT_GAIN": 51,
        "WEIGHT_VOLUME": 9,
        "WEIGHT_FOREIGN": 7,
        "WEIGHT_SITC": 7,
        "WEIGHT_VCP": 12,
        "WEIGHT_BREAKOUT": 6,
        "WEIGHT_HANDOVER": 8
      }
    }

    # 測試不同的 INDUSTRY_FILTER_TOP_N
    test_values = [None, 1, 2, 3, 5]
    
    results = []
    print(f"{'Top N Ind':<10} | {'ROI':<10} | {'Total PL':<15} | {'Bench ROI':<10}")
    print("-" * 55)

    for val in test_values:
        cfg = base_cfg.copy()
        if val is not None:
            cfg['INDUSTRY_FILTER_TOP_N'] = val
        
        # 執行回測
        res = backtest_momentum.run_backtest(override_config=cfg, silent=True)
        
        if res:
            roi = res['roi']
            total_pl = res['total_pl']
            bench_roi = res['bench_roi']
            label = str(val) if val is not None else "None"
            print(f"{label:<10} | {roi:>10.2%} | {total_pl:>15,.0f} | {bench_roi:>10.2%}")
            
            results.append({
                "industry_filter_top_n": val,
                "roi": roi,
                "total_pl": total_pl,
                "bench_roi": bench_roi
            })

    with open('industry_experiment_results_393.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    run_industry_experiment()
