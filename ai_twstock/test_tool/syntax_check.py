#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
語法檢查工具 - 檢查 Python 程式碼語法是否正確
"""

import ast
import sys
import os

def check_syntax(file_path):
    """檢查 Python 檔案語法"""
    print(f"檢查檔案: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"[ERROR] 檔案不存在: {file_path}")
        return False
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source_code = f.read()
        
        # 嘗試解析 AST
        ast.parse(source_code)
        print("[SUCCESS] 語法檢查通過")
        return True
        
    except SyntaxError as e:
        print(f"[ERROR] 語法錯誤:")
        print(f"  行號: {e.lineno}")
        print(f"  錯誤: {e.msg}")
        print(f"  位置: {e.text}")
        return False
        
    except Exception as e:
        print(f"[ERROR] 其他錯誤: {e}")
        return False

def main():
    # 檢查目標檔案
    target_file = os.path.join(os.path.dirname(__file__), '..', 'backtest_enhanced_day_trading.py')
    target_file = os.path.abspath(target_file)
    
    print("=== Python 語法檢查工具 ===")
    success = check_syntax(target_file)
    
    if success:
        print("\n✅ 語法檢查通過，程式碼應該可以正常執行")
    else:
        print("\n❌ 發現語法錯誤，需要修正後才能執行")
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)