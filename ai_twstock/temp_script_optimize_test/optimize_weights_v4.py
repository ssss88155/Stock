import backtest_momentum
import json
import os
import random

def run_weight_optimization(iterations=20):
    best_roi = 4.9092 # 目前已知的 490%
    best_weights = {
        "WEIGHT_GAIN": 51,
        "WEIGHT_VOLUME": 9,
        "WEIGHT_FOREIGN": 7,
        "WEIGHT_SITC": 7,
        "WEIGHT_VCP": 12,
        "WEIGHT_BREAKOUT": 6,
        "WEIGHT_HANDOVER": 8
    }

    base_cfg = {
      "BUY_DATES": "DAILY",
      "MOMENTUM_EXIT_THRESHOLD": 30,
      "TAKE_PROFIT_HALF_THRESHOLD": 0.1616067800219892,
      "DAILY_INVEST_POOL": 300000,
      "STARTING_CASH": 2000000,
      "TOP_N": 10,
      "BUY_SCORE_THRESHOLD": 70,
      "STOP_LOSS_THRESHOLD": -0.03,
      "TRAILING_STOP_THRESHOLD": -0.08,
      "INDUSTRY_FILTER_TOP_N": 3
    }

    print(f"Starting weight optimization for {iterations} iterations...")

    for i in range(iterations):
        # 圍繞目前最佳權重進行微調
        weights = {k: max(0, v + random.randint(-5, 5)) for k, v in best_weights.items()}
        # 正規化
        total_w = sum(weights.values())
        if total_w == 0: continue
        for k in weights: weights[k] = int(weights[k] * 100 / total_w)
        # 補足 100
        weights["WEIGHT_GAIN"] += (100 - sum(weights.values()))

        cfg = base_cfg.copy()
        cfg['WEIGHTS'] = weights
        
        res = backtest_momentum.run_backtest(override_config=cfg, silent=True)
        if res:
            roi = res['roi']
            if roi > best_roi:
                best_roi = roi
                best_weights = weights
                print(f"New Best! Iter {i+1}: ROI={roi:.2%}")
                print(json.dumps(weights))

    print(f"Optimization finished. Best ROI: {best_roi:.2%}")
    print(f"Best Weights: {json.dumps(best_weights)}")

if __name__ == "__main__":
    run_weight_optimization(30)
