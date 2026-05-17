import backtest_momentum
import json
import os

def run_experiments():
    # 原始購買日期
    with open(os.path.join('config', 'backtest_config.json'), 'r', encoding='utf-8') as f:
        orig_config = json.load(f)
    orig_buy_dates = orig_config.get('BUY_DATES', [])

    # 定義權重組合
    weight_sets = [
        {"name": "Original", "WEIGHT_GAIN": 10, "WEIGHT_VOLUME": 15, "WEIGHT_FOREIGN": 30, "WEIGHT_SITC": 15, "WEIGHT_VCP": 20, "WEIGHT_BREAKOUT": 10},
        {"name": "ForeignFocus", "WEIGHT_GAIN": 10, "WEIGHT_VOLUME": 10, "WEIGHT_FOREIGN": 50, "WEIGHT_SITC": 10, "WEIGHT_VCP": 10, "WEIGHT_BREAKOUT": 10},
        {"name": "SITCFocus", "WEIGHT_GAIN": 10, "WEIGHT_VOLUME": 10, "WEIGHT_FOREIGN": 10, "WEIGHT_SITC": 50, "WEIGHT_VCP": 10, "WEIGHT_BREAKOUT": 10},
        {"name": "TechnicalFocus", "WEIGHT_GAIN": 20, "WEIGHT_VOLUME": 20, "WEIGHT_FOREIGN": 10, "WEIGHT_SITC": 10, "WEIGHT_VCP": 20, "WEIGHT_BREAKOUT": 20},
        {"name": "BreakoutVCP", "WEIGHT_GAIN": 10, "WEIGHT_VOLUME": 10, "WEIGHT_FOREIGN": 10, "WEIGHT_SITC": 10, "WEIGHT_VCP": 30, "WEIGHT_BREAKOUT": 30},
        {"name": "PureGain", "WEIGHT_GAIN": 50, "WEIGHT_VOLUME": 10, "WEIGHT_FOREIGN": 10, "WEIGHT_SITC": 10, "WEIGHT_VCP": 10, "WEIGHT_BREAKOUT": 10}
    ]

    # 固定最佳回測參數
    base_cfg = {
        'BUY_DATES': orig_buy_dates,
        'BUY_SCORE_THRESHOLD': 70,
        'MOMENTUM_EXIT_THRESHOLD': 30,
        'TAKE_PROFIT_HALF_THRESHOLD': 0.20,
        'STOP_LOSS_THRESHOLD': -0.10,
        'DAILY_INVEST_POOL': 200000,
        'STARTING_CASH': 2000000
    }

    results = []
    print(f"Starting weight experiments for {len(weight_sets)} sets...")

    for ws in weight_sets:
        cfg = base_cfg.copy()
        cfg['WEIGHTS'] = ws
        
        # 執行回測
        res = backtest_momentum.run_backtest(override_config=cfg, silent=True)
        
        if res:
            res['weight_name'] = ws['name']
            res['config'] = cfg
            results.append(res)
            print(f"Set: {ws['name']:<15} ROI: {res['roi']:>7.2%}")

    # 排序
    results.sort(key=lambda x: x['roi'], reverse=True)

    print("\n" + "="*120)
    print(f"{'Rank':<5} {'Weight Set':<15} {'ROI':<8} {'Total PL':<12} {'Invested':<12} {'Gain':<5} {'Vol':<5} {'For':<5} {'SITC':<5} {'VCP':<5} {'Brk':<5}")
    print("-" * 120)
    for i, r in enumerate(results):
        ws = r['config']['WEIGHTS']
        print(f"{i+1:<5} {r['weight_name']:<15} {r['roi']:>7.2%} {r['total_pl']:>12,.0f} {r['peak_invested']:>12,.0f} {ws['WEIGHT_GAIN']:<5} {ws['WEIGHT_VOLUME']:<5} {ws['WEIGHT_FOREIGN']:<5} {ws['WEIGHT_SITC']:<5} {ws['WEIGHT_VCP']:<5} {ws['WEIGHT_BREAKOUT']:<5}")

    with open('weight_experiment_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    run_experiments()
