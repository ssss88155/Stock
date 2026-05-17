import backtest_momentum
import json
import os

def run_experiments():
    # 原始購買日期
    with open(os.path.join('config', 'backtest_config.json'), 'r', encoding='utf-8') as f:
        orig_config = json.load(f)
    orig_buy_dates = orig_config.get('BUY_DATES', [])

    # 參數網格
    grid = {
        'BUY_DATES': ["DAILY", orig_buy_dates],
        'BUY_SCORE_THRESHOLD': [0, 60, 75],
        'MOMENTUM_EXIT_THRESHOLD': [20, 40],
        'TAKE_PROFIT_HALF_THRESHOLD': [0.15, 0.25],
        'STOP_LOSS_THRESHOLD': [-0.07, -0.12],
        'DAILY_INVEST_POOL': [150000, 300000]
    }

    results = []
    
    # 遞迴跑網格 (簡單起見用巢狀迴圈)
    count = 0
    total_runs = 2 * 3 * 2 * 2 * 2 * 2
    
    print(f"Starting {total_runs} experiments...")

    for bd in grid['BUY_DATES']:
        for bst in grid['BUY_SCORE_THRESHOLD']:
            for met in grid['MOMENTUM_EXIT_THRESHOLD']:
                for tpht in grid['TAKE_PROFIT_HALF_THRESHOLD']:
                    for slt in grid['STOP_LOSS_THRESHOLD']:
                        for dip in grid['DAILY_INVEST_POOL']:
                            count += 1
                            cfg = {
                                'BUY_DATES': bd,
                                'BUY_SCORE_THRESHOLD': bst,
                                'MOMENTUM_EXIT_THRESHOLD': met,
                                'TAKE_PROFIT_HALF_THRESHOLD': tpht,
                                'STOP_LOSS_THRESHOLD': slt,
                                'DAILY_INVEST_POOL': dip,
                                'STARTING_CASH': 2000000 # 給足資金避免卡住
                            }
                            
                            # 執行回測 (silent=True 減少輸出)
                            res = backtest_momentum.run_backtest(override_config=cfg, silent=True)
                            
                            if res:
                                res['config'] = cfg
                                results.append(res)
                                # 簡短列印進度
                                bd_label = "DAILY" if bd == "DAILY" else "ORIG"
                                print(f"Run {count}/{total_runs}: {bd_label}, ScoreTH:{bst}, MomExit:{met}, ROI:{res['roi']:.1%}")

    # 排序結果
    results.sort(key=lambda x: x['total_pl'], reverse=True)

    print("\n" + "="*100)
    print(f"{'Rank':<5} {'ROI':<8} {'Total PL':<12} {'Invested':<12} {'BD':<7} {'ScoreTH':<8} {'MomExit':<8} {'TP_Half':<8} {'SL':<8} {'Pool':<8}")
    print("-" * 100)
    for i, r in enumerate(results[:30]): # 印出前 30 名
        cfg = r['config']
        bd_label = "DAILY" if cfg['BUY_DATES'] == "DAILY" else "ORIG"
        print(f"{i+1:<5} {r['roi']:>7.1%} {r['total_pl']:>12,.0f} {r['peak_invested']:>12,.0f} {bd_label:<7} {cfg['BUY_SCORE_THRESHOLD']:<8} {cfg['MOMENTUM_EXIT_THRESHOLD']:<8} {cfg['TAKE_PROFIT_HALF_THRESHOLD']:<8} {cfg['STOP_LOSS_THRESHOLD']:<8} {cfg['DAILY_INVEST_POOL']:<8}")

    # 詳細報告前 5 名
    print("\n--- Top 5 Detailed Results ---")
    for i, r in enumerate(results[:5]):
        print(f"\n[Rank {i+1}] Profit: {r['total_pl']:,.0f}, ROI: {r['roi']:.2%}")
        print(f"Config: {json.dumps(r['config'], ensure_ascii=False)}")
        # 可以列印出具體的投入產出，但因為 user 想要看到每一筆，我會把結果存成檔案或大表
    
    # 輸出所有結果到檔案以便 review
    with open('experiment_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    run_experiments()
