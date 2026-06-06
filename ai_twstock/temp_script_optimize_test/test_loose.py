import backtest_momentum
import json
import os

def test_loose_stops():
    cfg = {
      "BUY_DATES": "DAILY",
      "MOMENTUM_EXIT_THRESHOLD": 30,
      "TAKE_PROFIT_HALF_THRESHOLD": 0.1616067800219892,
      "DAILY_INVEST_POOL": 300000,
      "STARTING_CASH": 2000000,
      "TOP_N": 10,
      "BUY_SCORE_THRESHOLD": 70,
      "STOP_LOSS_THRESHOLD": -0.05, # 從 -0.03 放寬
      "TRAILING_STOP_THRESHOLD": -0.10, # 從 -0.08 放寬
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
    res = backtest_momentum.run_backtest(override_config=cfg, silent=True)
    if res:
        print(f"ROI: {res['roi']:.2%}")
        print(f"Transactions: {len(res['transactions'])}")

if __name__ == "__main__":
    test_loose_stops()
