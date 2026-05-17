import json
import os
import argparse
import sys
import warnings
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# 忽略警告並設定編碼
warnings.filterwarnings("ignore")
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 設定中文字體
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'Arial', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# 將 lib 目錄加入 Python 路徑
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'lib'))
from common_lib import load_independent_stock_data, get_script_dir

def format_number(n):
    if abs(n) >= 10**8: return f"{n/10**8:.1f}億"
    if abs(n) >= 10**4: return f"{n/10**4:.0f}萬"
    return str(int(n))

def plot_analysis(stock_id, df, peaks, troughs, sh_summary):
    """還原 11:35 樣式的圖表 (修正 X 軸對齊與堆疊邏輯)"""
    full_dates = pd.date_range(start=df.index.min(), end=df.index.max(), freq='D')
    plot_df = df.reindex(full_dates)
    line_df = plot_df.interpolate(method='linear')
    
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(15, 20), sharex=True, gridspec_kw={'height_ratios': [3, 2, 2]})
    
    ax1.plot(line_df.index, line_df['close'], label='收盤價', color='black', alpha=0.8, linewidth=2)
    ax1.set_title(f"{stock_id} 籌碼占比與換手分析", fontsize=20, fontweight='bold', pad=20)
    ax1.set_ylabel("股價", fontsize=14)
    ax1.grid(True, linestyle='--', alpha=0.5)
    for d, p in peaks: ax1.scatter(d, p, color='red', marker='v', s=80, zorder=5)
    for d, p in troughs: ax1.scatter(d, p, color='green', marker='^', s=80, zorder=5)
    
    info_box = (f"Shareholding Structure Change\n"
               f"---------------------------\n"
               f"Foreign(Official): {sh_summary['f_ratio_start']:.2f}% -> {sh_summary['f_ratio_end']:.2f}% ({sh_summary['f_ratio_change']:+.2f}%)\n"
               f"SITC (Estimated): +{sh_summary['sitc_change']:.2f}%\n"
               f"Retail (Estimated): {sh_summary['retail_change']:+.2f}%")
    ax1.text(0.01, 0.98, info_box, transform=ax1.transAxes, fontsize=12, verticalalignment='top', 
             bbox=dict(boxstyle='round,pad=0.8', facecolor='white', edgecolor='gray', alpha=0.9), family='monospace')
    ax1.legend(loc='upper right', fontsize=12)

    ax2.plot(line_df.index, line_df['f_ratio'], label='外資占比(官方)', color='royalblue', linewidth=2.5)
    ax2.plot(line_df.index, line_df['s_ratio_est'], label='投信變動占比', color='darkorange', linewidth=2)
    ax2.plot(line_df.index, line_df['r_ratio_est'], label='散戶/其他占比', color='grey', alpha=0.6, linewidth=2)
    ax2.set_ylabel("持股比例 (%)", fontsize=14)
    ax2.set_ylim(0, 100)
    ax2.grid(True, linestyle=':', alpha=0.7)
    ax2.legend(loc='upper left', fontsize=11)
    ax2.text(1.02, 0.5, "註：投信與散戶基數為推估值\n所有線條皆反映實際比例或相對變化", transform=ax2.transAxes, 
             fontsize=10, rotation=270, verticalalignment='center', color='gray')

    width = 0.7
    s_p, f_p, r_p = np.maximum(df['sitc_net'], 0), np.maximum(df['foreign_net'], 0), np.maximum(df['retail_net'], 0)
    ax3.bar(df.index, s_p, width, label='投信買', color='darkorange', alpha=0.9)
    ax3.bar(df.index, f_p, width, bottom=s_p, label='外資買', color='royalblue', alpha=0.7)
    ax3.bar(df.index, r_p, width, bottom=s_p+f_p, label='散戶買', color='silver', alpha=0.6)
    s_m, f_m, r_m = np.minimum(df['sitc_net'], 0), np.minimum(df['foreign_net'], 0), np.minimum(df['retail_net'], 0)
    ax3.bar(df.index, s_m, width, color='darkorange', alpha=0.9)
    ax3.bar(df.index, f_m, width, bottom=s_m, color='royalblue', alpha=0.7)
    ax3.bar(df.index, r_m, width, bottom=s_m+f_m, color='silver', alpha=0.6)
    ax3.axhline(0, color='black', linewidth=1)
    ax3.set_ylabel("單日淨買賣 (張)", fontsize=14)
    ax3.set_xticks(df.index)
    ax3.set_xticklabels(df.index.strftime('%m-%d'), rotation=45)
    h, l = ax3.get_legend_handles_labels()
    ax3.legend(h[:3], l[:3], loc='upper left', ncol=3, fontsize=11)
    ax3.grid(True, axis='y', linestyle='--', alpha=0.4)

    plt.tight_layout()
    out_dir = os.path.join(get_script_dir(), 'analyze_independent')
    if not os.path.exists(out_dir): os.makedirs(out_dir)
    out_file = os.path.join(out_dir, f"report_visual_{stock_id}_{datetime.now().strftime('%Y%m%d')}.png")
    plt.savefig(out_file, dpi=150)
    print(f"\n[圖表已更新生成] {out_file}")

def analyze_stock(stock_id, start_date, end_date):
    data = load_independent_stock_data(stock_id, get_script_dir(__file__))
    if not data: return print("找不到資料")

    price_data, inst_data, hold_data = data.get('price', {}), data.get('institutional', {}), data.get('shareholding', {})
    sorted_dates = sorted([d for d in price_data.keys() if start_date <= d <= end_date])
    if not sorted_dates: return print("區間內無資料")

    hold_dates = sorted(list(hold_data.keys()))
    total_shares = 1; f_ratio_dict = {}
    if hold_dates:
        last_hold_date = hold_dates[-1]
        total_shares = hold_data[last_hold_date].get('NumberOfSharesIssued', 1)
        for d in hold_dates: f_ratio_dict[d] = hold_data[d].get('ForeignInvestmentSharesRatio', 0)

    def get_f_ratio(date_str):
        if date_str in f_ratio_dict: return f_ratio_dict[date_str]
        past_dates = [d for d in hold_dates if d <= date_str]
        return f_ratio_dict[past_dates[-1]] if past_dates else 0

    s_cum_list = []
    curr_s_cum = 0
    for d in sorted_dates:
        inst = inst_data.get(d, {})
        s_n = (inst.get('Investment_Trust', {}).get('buy', 0) - inst.get('Investment_Trust', {}).get('sell', 0)) / 1000
        curr_s_cum += s_n
        s_cum_list.append((curr_s_cum * 1000 / total_shares) * 100)
    
    s_min_delta = min(s_cum_list) if s_cum_list else 0
    s_base = abs(s_min_delta) + 5.0 if s_min_delta < 0 else 5.0

    records = []
    s_cum, r_cum = 0, 0
    for d in sorted_dates:
        p = price_data[d]
        inst = inst_data.get(d, {})
        s_n = (inst.get('Investment_Trust', {}).get('buy', 0) - inst.get('Investment_Trust', {}).get('sell', 0)) / 1000
        f_n = (inst.get('Foreign_Investor', {}).get('buy', 0) - inst.get('Foreign_Investor', {}).get('sell', 0)) / 1000
        d_n = (inst.get('Dealer_self', {}).get('buy', 0) - inst.get('Dealer_self', {}).get('sell', 0)) / 1000
        r_n = -(s_n + f_n + d_n)
        s_cum += s_n; r_cum += r_n
        f_r = get_f_ratio(d)
        s_r_est = s_base + (s_cum * 1000 / total_shares) * 100
        r_r_est = 100.0 - f_r - s_r_est
        records.append({'date': d, 'close': p['close'], 'sitc_net': s_n, 'foreign_net': f_n, 'retail_net': r_n,
                        'f_ratio': f_r, 's_ratio_est': s_r_est, 'r_ratio_est': r_r_est,
                        'sitc_cum': s_cum, 'foreign_cum': f_n}) # foreign_cum here is placeholder

    df = pd.DataFrame(records).set_index(pd.to_datetime([r['date'] for r in records]))
    # 修復 foreign_cum 真正累計
    df['foreign_cum'] = df['foreign_net'].cumsum()

    f_s, f_e = get_f_ratio(sorted_dates[0]), get_f_ratio(sorted_dates[-1])
    s_change = (s_cum * 1000 / total_shares) * 100
    r_change = -( (f_e - f_s) + s_change )

    print("\n" + "="*60)
    print(f"個股籌碼結構深度報告: {stock_id}")
    print(f"分析區間: {sorted_dates[0]} ~ {sorted_dates[-1]}")
    print("-" * 60)
    print(f"1. 外資占比變動：{f_s:.2f}% -> {f_e:.2f}% (變動 {f_e-f_s:+.2f}%)")
    print(f"2. 投信占比變動：約 {s_base:.2f}% -> {s_base+s_change:.2f}% (變動 {s_change:+.2f}%)")
    print(f"3. 散戶占比變動：約 {100-f_s-s_base:.2f}% -> {100-f_e-(s_base+s_change):.2f}% (變動 {r_change:+.2f}%)")
    print("-" * 60)
    if abs(r_change) > abs(s_change): print(f">>> 關鍵觀察：此區間外資變動籌碼主要由「散戶」接走。")
    else: print(f">>> 關鍵觀察：此區間「投信」力道較強。")
    print("="*60)

    peaks, troughs = [], []
    win = 5
    for i in range(win, len(df) - win):
        if df['close'].iloc[i] == df['close'].iloc[i-win:i+win].max(): peaks.append((df.index[i], df['close'].iloc[i]))
        if df['close'].iloc[i] == df['close'].iloc[i-win:i+win].min(): troughs.append((df.index[i], df['close'].iloc[i]))

    plot_analysis(stock_id, df, peaks, troughs, {'f_ratio_start': f_s, 'f_ratio_end': f_e, 'f_ratio_change': f_e - f_s, 'sitc_change': s_change, 'retail_change': r_change})

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('stock_id')
    parser.add_argument('--start', default='2025-01-01')
    parser.add_argument('--end', default=datetime.now().strftime('%Y-%m-%d'))
    analyze_stock(parser.parse_args().stock_id, parser.parse_args().start, parser.parse_args().end)
