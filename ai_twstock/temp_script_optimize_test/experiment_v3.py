import backtest_momentum
import json
import os

def run_experiments_v3():
    # 原始購買日期
    config_path = os.path.join('config', 'backtest_config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            orig_config = json.load(f)
    else:
        orig_config = {}
        
    orig_buy_dates = orig_config.get('BUY_DATES', 'DAILY')

    # 定義不同的策略實驗組合 (權重 + 演算法參數)
    experiments = [
        {
            "name": "HandoverConsolidation",
            "weights": {"WEIGHT_GAIN": 10, "WEIGHT_VOLUME": 10, "WEIGHT_FOREIGN": 10, "WEIGHT_SITC": 10, "WEIGHT_VCP": 20, "WEIGHT_BREAKOUT": 10, "WEIGHT_HANDOVER": 30},
            "params": {"BUY_SCORE_THRESHOLD": 80, "STOP_LOSS_THRESHOLD": -0.08}
        },
        {
            "name": "HighConvictionSelective",
            "weights": {"WEIGHT_GAIN": 20, "WEIGHT_VOLUME": 10, "WEIGHT_FOREIGN": 20, "WEIGHT_SITC": 20, "WEIGHT_VCP": 10, "WEIGHT_BREAKOUT": 10, "WEIGHT_HANDOVER": 10},
            "params": {"BUY_SCORE_THRESHOLD": 90, "STOP_LOSS_THRESHOLD": -0.10}
        },
        {
            "name": "VCP_Focus",
            "weights": {"WEIGHT_GAIN": 10, "WEIGHT_VOLUME": 10, "WEIGHT_FOREIGN": 10, "WEIGHT_SITC": 10, "WEIGHT_VCP": 40, "WEIGHT_BREAKOUT": 10, "WEIGHT_HANDOVER": 10},
            "params": {"BUY_SCORE_THRESHOLD": 75, "STOP_LOSS_THRESHOLD": -0.07}
        },
        {
            "name": "TightRiskControl",
            "weights": {"WEIGHT_GAIN": 15, "WEIGHT_VOLUME": 15, "WEIGHT_FOREIGN": 15, "WEIGHT_SITC": 15, "WEIGHT_VCP": 15, "WEIGHT_BREAKOUT": 15, "WEIGHT_HANDOVER": 10},
            "params": {"BUY_SCORE_THRESHOLD": 80, "STOP_LOSS_THRESHOLD": -0.05, "TRAILING_STOP_THRESHOLD": -0.08}
        },
        {
            "name": "ExtremeSelective",
            "weights": {"WEIGHT_GAIN": 10, "WEIGHT_VOLUME": 10, "WEIGHT_FOREIGN": 10, "WEIGHT_SITC": 10, "WEIGHT_VCP": 20, "WEIGHT_BREAKOUT": 10, "WEIGHT_HANDOVER": 30},
            "params": {"BUY_SCORE_THRESHOLD": 95, "STOP_LOSS_THRESHOLD": -0.03, "TRAILING_STOP_THRESHOLD": -0.05}
        },
        {
            "name": "TrendFollowing_Strict",
            "weights": {"WEIGHT_GAIN": 40, "WEIGHT_VOLUME": 20, "WEIGHT_FOREIGN": 10, "WEIGHT_SITC": 10, "WEIGHT_VCP": 5, "WEIGHT_BREAKOUT": 15, "WEIGHT_HANDOVER": 0},
            "params": {"BUY_SCORE_THRESHOLD": 85, "STOP_LOSS_THRESHOLD": -0.05}
        }
    ]

    base_cfg = {
        'BUY_DATES': orig_buy_dates,
        'MOMENTUM_EXIT_THRESHOLD': 30,
        'TAKE_PROFIT_HALF_THRESHOLD': 0.20,
        'DAILY_INVEST_POOL': 200000,
        'STARTING_CASH': 2000000
    }

    results = []
    print(f"Starting experiment V3 for {len(experiments)} scenarios...")

    for exp in experiments:
        cfg = base_cfg.copy()
        cfg.update(exp['params'])
        cfg['WEIGHTS'] = exp['weights']
        
        # 執行回測
        res = backtest_momentum.run_backtest(override_config=cfg, silent=True)
        
        if res:
            res['exp_name'] = exp['name']
            res['config'] = cfg
            results.append(res)
            print(f"Scenario: {exp['name']:<25} ROI: {res['roi']:>7.2%} PL: {res['total_pl']:>10,.0f}")

    # 排序
    results.sort(key=lambda x: x['roi'], reverse=True)

    print("\n" + "="*140)
    print(f"{'Rank':<5} {'Scenario':<25} {'ROI':<8} {'Total PL':<12} {'Starting':<12} {'ScoreThr':<8} {'SL':<6} {'Gain':<4} {'For':<4} {'SITC':<4} {'VCP':<4} {'Hnd':<4}")
    print("-" * 140)
    for i, r in enumerate(results):
        ws = r['config']['WEIGHTS']
        params = r['config']
        print(f"{i+1:<5} {r['exp_name']:<25} {r['roi']:>7.2%} {r['total_pl']:>12,.0f} {r['starting_cash']:>12,.0f} "
              f"{params['BUY_SCORE_THRESHOLD']:<8} {params['STOP_LOSS_THRESHOLD']:<6.1%} "
              f"{ws['WEIGHT_GAIN']:<4} {ws['WEIGHT_FOREIGN']:<4} {ws['WEIGHT_SITC']:<4} {ws['WEIGHT_VCP']:<4} {ws.get('WEIGHT_HANDOVER', 0):<4}")

    output_file = 'experiment_v3_results.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {output_file}")

if __name__ == "__main__":
    run_experiments_v3()
