import backtest_momentum
import json
import os

def check_win_rate():
    cfg = {
      "BUY_DATES": "DAILY",
      "MOMENTUM_EXIT_THRESHOLD": 30,
      "TAKE_PROFIT_HALF_THRESHOLD": 0.1616067800219892,
      "DAILY_INVEST_POOL": 300000,
      "STARTING_CASH": 2000000,
      "TOP_N": 10,
      "BUY_SCORE_THRESHOLD": 200, # 高門檻減少噪音
      "STOP_LOSS_THRESHOLD": -0.05, # 放寬一點停損
      "TRAILING_STOP_THRESHOLD": -0.12, # 放寬一點移動停利，減少被掃出場
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

    res = backtest_momentum.run_backtest(override_config=cfg, silent=True)
    if res:
        txs = res['transactions']
        sells = [t for t in txs if t['side'] == 'S']
        profits = [s for s in sells if s.get('revenue', 0) > 0] # 簡化判斷
        # 其實勝率要看 realized_pl
        print(f"ROI: {res['roi']:.2%}")
        print(f"Transactions: {len(txs)}")

if __name__ == "__main__":
    check_win_rate()
