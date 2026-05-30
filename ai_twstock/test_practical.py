import backtest_momentum
import json
import os

def test_practical_scenario():
    # 使用 591% 的權重
    cfg = {
      "BUY_DATES": "DAILY",
      "MOMENTUM_EXIT_THRESHOLD": 30,
      "TAKE_PROFIT_HALF_THRESHOLD": 0.1616067800219892,
      "DAILY_INVEST_POOL": 300000, # 實戰時這裡可能要調低，但先維持以利權重發揮
      "STARTING_CASH": 30000,     # 起始 3 萬
      "MONTHLY_CONTRIBUTION": 45000, # 每月加 4.5 萬
      "TOP_N": 10,
      "MAX_DAILY_BUY": 5,
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
    
    print("正在執行「實戰 3萬+4.5萬」回測...")
    res = backtest_momentum.run_backtest(override_config=cfg, silent=False)
    
    if res:
        print(f"\n最終回測結果 (實戰 Option 2):")
        print(f"總投入資金: {res.get('total_invested', 0):,.0f}")
        print(f"總盈虧: {res['total_pl']:,.0f}")
        print(f"ROI: {res['roi']:.2%}")

if __name__ == "__main__":
    test_practical_scenario()
