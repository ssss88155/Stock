import backtest_momentum
import json
import os

def test_stops():
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
      "INDUSTRY_FILTER_TOP_N": 3,
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

    # 測試不同的 STOP_LOSS_THRESHOLD
    sl_values = [-0.03, -0.05, -0.08, -0.10]
    # 測試不同的 TRAILING_STOP_THRESHOLD
    ts_values = [-0.08, -0.10, -0.12, -0.15]
    
    print(f"{'SL':<6} | {'TS':<6} | {'ROI':<10} | {'Total PL':<15}")
    print("-" * 45)

    for sl in sl_values:
        for ts in ts_values:
            cfg = base_cfg.copy()
            cfg['STOP_LOSS_THRESHOLD'] = sl
            cfg['TRAILING_STOP_THRESHOLD'] = ts
            res = backtest_momentum.run_backtest(override_config=cfg, silent=True)
            if res:
                print(f"{sl:<6} | {ts:<6} | {res['roi']:>10.2%} | {res['total_pl']:>15,.0f}")

if __name__ == "__main__":
    test_stops()
