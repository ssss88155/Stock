import backtest_momentum
import json
import os

def final_optimization():
    # 使用 543% 的基礎權重
    base_cfg = {
      "BUY_DATES": "DAILY",
      "MOMENTUM_EXIT_THRESHOLD": 30,
      "TAKE_PROFIT_HALF_THRESHOLD": 0.1616067800219892,
      "DAILY_INVEST_POOL": 300000,
      "STARTING_CASH": 2000000,
      "TOP_N": 10,
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
        "MIN_INDUSTRY_CLUSTER_SIZE": 2
      }
    }

    # 測試門檻組合
    thresholds = [100, 150, 200, 250, 300]
    cluster_sizes = [2, 3]
    
    print(f"{'Threshold':<10} | {'Cluster':<8} | {'ROI':<10} | {'Total PL':<15} | {'TX':<8}")
    print("-" * 65)

    for ts in thresholds:
        for cl in cluster_sizes:
            cfg = base_cfg.copy()
            cfg['BUY_SCORE_THRESHOLD'] = ts
            cfg['WEIGHTS'] = base_cfg['WEIGHTS'].copy()
            cfg['WEIGHTS']['MIN_INDUSTRY_CLUSTER_SIZE'] = cl
            
            res = backtest_momentum.run_backtest(override_config=cfg, silent=True)
            if res:
                tx_count = len(res['transactions'])
                print(f"{ts:<10} | {cl:<8} | {res['roi']:>10.2%} | {res['total_pl']:>15,.0f} | {tx_count}")

if __name__ == "__main__":
    final_optimization()
