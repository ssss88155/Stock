import json
import os
import unicodedata
import time

# --- 終端機顏色 ---
class Color:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    GRAY = '\033[90m' # 改用 90 (深灰色) 避免與白色混淆
    ORANGE = '\033[38;5;208m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

    @staticmethod
    def wrap(text, color):
        return f"{color}{text}{Color.END}"

# --- 字串處理與對齊 ---
def get_display_width(s):
    """計算字串在終端機顯示的寬度 (中文字佔 2 單位)"""
    width = 0
    for char in str(s):
        if unicodedata.east_asian_width(char) in ('W', 'F', 'A'):
            width += 2
        else:
            width += 1
    return width

def truncate_string(s, max_width):
    """截斷字串並確保顯示寬度不超過 max_width"""
    if get_display_width(s) <= max_width:
        return s
    
    current_width = 0
    res = ""
    for char in str(s):
        char_width = 2 if unicodedata.east_asian_width(char) in ('W', 'F', 'A') else 1
        if current_width + char_width > max_width:
            break
        res += char
        current_width += char_width
    return res

def pad_string(s, width, align='left'):
    """手動補齊空白以對齊終端機顯示寬度"""
    s = str(s)
    cur_w = get_display_width(s)
    pad_size = max(0, width - cur_w)
    if align == 'left':
        return s + ' ' * pad_size
    elif align == 'right':
        return ' ' * pad_size + s
    else: # center
        left_pad = pad_size // 2
        right_pad = pad_size - left_pad
        return ' ' * left_pad + s + ' ' * right_pad

# --- 資料讀取與同步 ---
_LOADED_DATA_CACHE = None

def get_script_dir(file_path):
    return os.path.dirname(os.path.abspath(file_path))

def load_stock_data(filename='stock_data.json', script_file=None):
    """
    載入大型股票 JSON 資料
    :param filename: 檔名
    :param script_file: 呼叫者的 __file__，用來定位目錄
    """
    global _LOADED_DATA_CACHE
    if _LOADED_DATA_CACHE is not None:
        return _LOADED_DATA_CACHE
        
    base_dir = get_script_dir(script_file) if script_file else os.getcwd()
    path = os.path.join(base_dir, filename)
    
    # 自動執行增量合併 (假設 data_independent 在同目錄)
    sync_independent_data(path)
    
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                _LOADED_DATA_CACHE = data
                return data
            except json.JSONDecodeError:
                return {}
    return {}

def load_independent_stock_data(stock_id, base_dir):
    """載入獨立的個股 JSON 資料"""
    path = os.path.join(base_dir, 'data_independent', f"{stock_id}.json")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get(stock_id, {})
        except Exception: pass
    return {}

def sync_independent_data(target_path):
    """將 data_independent 中的更新同步到大 JSON 檔案"""
    base_dir = os.path.dirname(target_path)
    source_dir = os.path.join(base_dir, 'data_independent')
    
    if not os.path.exists(source_dir):
        return

    last_merge_time = 0
    if os.path.exists(target_path):
        last_merge_time = os.path.getmtime(target_path)
    
    changed_files = []
    with os.scandir(source_dir) as it:
        for entry in it:
            if entry.is_file() and entry.name.endswith('.json'):
                if entry.stat().st_mtime > last_merge_time:
                    changed_files.append(entry.path)
            
    if not changed_files:
        return

    print(f"[INFO] Syncing {len(changed_files)} updated stocks...")
    
    merged_data = {}
    if os.path.exists(target_path):
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                merged_data = json.load(f)
        except Exception:
            merged_data = {}

    for file_path in changed_files:
        for _ in range(3):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    merged_data.update(json.load(f))
                break
            except (PermissionError, json.JSONDecodeError):
                time.sleep(0.1)
            except Exception:
                break

    sorted_data = dict(sorted(merged_data.items()))
    temp_path = target_path + ".tmp"
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(sorted_data, f, ensure_ascii=False, indent=4)
    
    if os.path.exists(target_path):
        os.remove(target_path)
    os.rename(temp_path, target_path)
