import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import sys
import io

# Ensure terminal output is UTF-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def fetch_stock_data(url):
    print(f"Fetching data from {url}...")
    try:
        # TWSE site uses Big5 encoding for these JSP pages
        response = requests.get(url)
        response.encoding = 'big5' 
        if response.status_code != 200:
            print(f"Failed to fetch data. Status code: {response.status_code}")
            return None
        return response.text
    except Exception as e:
        print(f"Error fetching data: {e}")
        return None

def parse_stocks(html_content):
    if not html_content:
        return []
    
    # Use lxml for better parsing performance
    soup = BeautifulSoup(html_content, 'lxml')
    table = soup.find('table', class_='h4')
    if not table:
        print("Could not find the stock table.")
        return []
    
    stocks = []
    current_category = ""
    
    rows = table.find_all('tr')
    for row in rows:
        cols = row.find_all('td')
        if not cols:
            continue
        
        # Check if it's a category header (one cell spanning multiple columns)
        # Category headers like "股票", "受益憑證" are in a single <td> with colspan
        if len(cols) == 1:
            current_category = cols[0].get_text(strip=True)
            # print(f"Processing category: {current_category}") # Debugging
            continue
        
        # We only want "股票" (Individual Stocks)
        # Note: In the HTML, it's exactly "股票"
        if current_category != "股票":
            continue
            
        # The first column is "有價證券代號及名稱", e.g., "1101　台泥"
        # It uses a full-width space (U+3000)
        code_name = cols[0].get_text(strip=True)
        
        # Split by any whitespace (including full-width)
        # Format is usually: "CODE   NAME"
        parts = re.split(r'[\s\u3000]+', code_name)
        if len(parts) >= 2:
            code = parts[0]
            name = parts[1]
            
            # 4th column (index 3) is Market (上市/上櫃)
            market = cols[3].get_text(strip=True)
            # 5th column (index 4) is Industry
            industry = cols[4].get_text(strip=True)
            # 6th column (index 5) is Listing Date
            listing_date = cols[2].get_text(strip=True)
            
            stocks.append({
                'code': code,
                'name': name,
                'market': market,
                'industry': industry,
                'listing_date': listing_date,
                'category': current_category
            })
            
    return stocks

def main():
    urls = {
        "Listed (上市)": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2",
        "OTC (上櫃)": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
    }
    
    all_stocks = []
    for label, url in urls.items():
        html = fetch_stock_data(url)
        stocks = parse_stocks(html)
        print(f"Found {len(stocks)} stocks from {label}")
        all_stocks.extend(stocks)
    
    if not all_stocks:
        print("No stocks found. Please check the parser.")
        return

    df = pd.DataFrame(all_stocks)
    
    # Verification
    print("\n" + "="*30)
    print("--- Verification Report ---")
    print("="*30)
    print(f"Total stocks found: {len(df)}")
    print(f"Unique stock codes: {df['code'].nunique()}")
    
    # Check for duplicates
    if df['code'].nunique() != len(df):
        duplicates = df[df.duplicated('code', keep=False)]
        print(f"Warning: Found {len(duplicates)} duplicate codes.")
        print(duplicates.sort_values('code'))
    else:
        print("No duplicate stock codes found. (Verification Pass)")
        
    # Check format (mostly 4 digits)
    df['code_len'] = df['code'].apply(len)
    print("\nStock code length distribution:")
    print(df['code_len'].value_counts().sort_index())
    
    # Verify market types
    print("\nMarket types found:")
    market_counts = df['market'].value_counts()
    print(market_counts)
    
    # Specific verification for "上市" and "上櫃"
    if "上市" in market_counts and "上櫃" in market_counts:
        print("Successfully captured both Listed and OTC stocks. (Verification Pass)")
    
    # Check for non-stock items (sanity check)
    # Individual stocks should not have "ETF" or "債" in their names usually
    # But some might, so we rely on the "股票" category filter which is robust.
    
    # Save to CSV
    output_path = "taiwan_stocks.csv"
    df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"\nSaved results to {output_path}")
    
    # Sample check (Printing first 5 and last 5)
    print("\nSample Data (First 5):")
    print(df[['code', 'name', 'market', 'industry']].head(5).to_string(index=False))
    print("\nSample Data (Last 5):")
    print(df[['code', 'name', 'market', 'industry']].tail(5).to_string(index=False))

if __name__ == "__main__":
    main()
