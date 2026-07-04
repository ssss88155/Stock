import sqlite3
import pandas as pd
import os

db_path = r'C:\jupyter_notebook\ai_twstock\data\SQL_DB\taiwan_stock_micro.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("Tables:", tables)
    
    for table in tables:
        table_name = table[0]
        print(f"\nSchema for {table_name}:")
        cursor.execute(f"PRAGMA table_info({table_name});")
        print(cursor.fetchall())
        
        print(f"\nFirst 5 rows of {table_name}:")
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 5;")
        print(cursor.fetchall())
    
    conn.close()
else:
    print(f"Database not found at {db_path}")
