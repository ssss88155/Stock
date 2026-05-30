import backtest_momentum
import json
import os
import itertools

def run_experiments():
    # 原始購買日期
    config_path = os.path.join('config', 'backtest_config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            orig_config = json.load(f)
    else:
        orig_config = {}
    
    orig_buy_dates = orig_config.get('BUY_DATES', "DAILY")

    # 定義權重組合 (聚焦於表現好的 Handover)
    weight_sets = [
        {"name": "HandoverFocus_v1", "WEIGHT_GAIN": 20, "WEIGHT_VOLUME": 10, "WEIGHT_FOREIGN": 10, "WEIGHT_SITC": 10, "WEIGHT_VCP": 10, "WEIGHT_BREAKOUT": 10, "WEIGHT_HANDOVER": 60},
        {"name": "HandoverFocus_v2", "WEIGHT_GAIN": 10, "WEIGHT_VOLUME": 5, "WEIGHT_FOREIGN": 5, "WEIGHT_SITC": 5, "WEIGHT_VCP": 5, "WEIGHT_BREAKOUT": 5, "WEIGHT_HANDOVER": 85},
        {"name": "HandoverInst", "WEIGHT_GAIN": 10, "WEIGHT_VOLUME": 10, "WEIGHT_FOREIGN": 20, "WEIGHT_SITC": 20, "WEIGHT_VCP": 10, "WEIGHT_BREAKOUT": 10, "WEIGHT_HANDOVER": 40},
    ]

    # 定義門檻組合 (聚焦於表現好的寬鬆停損與高門檻)
    thresholds = [
        {'BUY_SCORE_THRESHOLD': 70, 'STOP_LOSS_THRESHOLD': -0.15, 'TAKE_PROFIT_HALF_THRESHOLD': 0.25},
        {'BUY_SCORE_THRESHOLD': 85, 'STOP_LOSS_THRESHOLD': -0.15, 'TAKE_PROFIT_HALF_THRESHOLD': 0.25},
        {'BUY_SCORE_THRESHOLD': 70, 'STOP_LOSS_THRESHOLD': -0.20, 'TAKE_PROFIT_HALF_THRESHOLD': 0.30},
        {'BUY_SCORE_THRESHOLD': 90, 'STOP_LOSS_THRESHOLD': -0.12, 'TAKE_PROFIT_HALF_THRESHOLD': 0.20},
    ]

    results = []
    
    combinations = list(itertools.product(weight_sets, thresholds))
    print(f"Starting {len(combinations)} experiments...")

    for ws, th in combinations:
        cfg = {
            'BUY_DATES': orig_buy_dates,
            'DAILY_INVEST_POOL': 300000,
            'STARTING_CASH': 1000000,
            'TOP_N': 5,
            'WEIGHTS': ws
        }
        cfg.update(th)
        
        # 執行回測
        res = backtest_momentum.run_backtest(override_config=cfg, silent=True)
        
        if res:
            res['weight_name'] = ws['name']
            res['config'] = cfg
            results.append(res)
            print(f"Set: {ws['name']:<15} Thresh: B{th['BUY_SCORE_THRESHOLD']} S{th['STOP_LOSS_THRESHOLD']} ROI: {res['roi']:>7.2%}")

    # 排序
    results.sort(key=lambda x: x['roi'], reverse=True)

    print("\n" + "="*140)
    print(f"{'Rank':<5} {'Weight Set':<15} {'ROI':<8} {'B_Thresh':<8} {'S_Loss':<8} {'T_Prof':<8} {'Total PL':<12} {'Invested':<12}")
    print("-" * 140)
    for i, r in enumerate(results[:15]): # 印前15名
        cfg = r['config']
        print(f"{i+1:<5} {r['weight_name']:<15} {r['roi']:>7.2%} {cfg['BUY_SCORE_THRESHOLD']:<8} {cfg['STOP_LOSS_THRESHOLD']:<8} {cfg['TAKE_PROFIT_HALF_THRESHOLD']:<8} {r['total_pl']:>12,.0f} {r['peak_invested']:>12,.0f}")

    with open('experiment_results_v2.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    run_experiments()
