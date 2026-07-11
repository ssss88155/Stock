import json
import os

def inspect_debug_data():
    path = r"C:\jupyter_notebook\ai_twstock\stock_data_debug.json"
    if not os.path.exists(path):
        print("File not found")
        return
        
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    for sid in data:
        print(f"\nStock: {sid}")
        price_dates = sorted(list(data[sid].get('price', {}).keys()))
        report_dates = sorted(list(data[sid].get('trading_daily_report', {}).keys()))
        
        print(f"Price data range: {price_dates[0] if price_dates else 'N/A'} to {price_dates[-1] if price_dates else 'N/A'} (Total: {len(price_dates)})")
        print(f"Report data range: {report_dates[0] if report_dates else 'N/A'} to {report_dates[-1] if report_dates else 'N/A'} (Total: {len(report_dates)})")
        
        if report_dates:
            last_date = report_dates[-1]
            print(f"Sample report on {last_date}:")
            print(json.dumps(data[sid]['trading_daily_report'][last_date], indent=2, ensure_ascii=False)[:500])

if __name__ == "__main__":
    inspect_debug_data()
