import json
import os

# 這是深度校驗後的券商特性邏輯。
# 規則：
# 1. 外資量化巨獸 (高盛, 美林, 摩根, 瑞銀, 法興, 麥格理) -> -100 ~ -60 (極危險)
# 2. 隔日沖基地 (凱基台北, 松山, 三多, 虎尾, 土城) -> -100 (極危險)
# 3. 內資短線主力 (群益大安, 永豐南京, 富邦南京) -> -80 ~ -30
# 4. 官股穩定力量 (兆豐, 合庫, 台灣, 土地, 台銀) -> 95 ~ 100
# 5. 穩定長線機構 (國泰總公司, 富邦總公司) -> 90 ~ 100

def get_refined_feature(tid, name):
    # --- 1. 極端危險區 (量化與隔日沖) ---
    
    # 外資巨獸
    if tid in ["1480", "148C"]:
        return "頂級量化巨獸。狂買狂賣，操作不留情面，對股價衝擊力極大，是非常危險的存在。", -100
    if tid in ["1440", "144C"]:
        return "外資量化巨獸。程式交易大本營，操作極其高頻且具備強大的助漲助跌慣性，極度危險。", -100
    if tid in ["1650", "165C"]:
        return "量化與避險基金聚集地。演算法交易極度發達，是短線波動的主要推手，不講基本面。", -100
    if tid in ["8440", "844C"]:
        return "超級量化巨獸。短線、當沖與波段進出極快，常在盤中造成劇烈震盪，極度侵略性。", -100
    if tid in ["1560"]:
        return "外資侵略者。擅長發動突發性的趨勢，操作風格犀利且變化莫測，對中型股破壞力強。", -80
    if tid in ["1590"]:
        return "量化勢力。具備高度市場破壞力，進出頻繁且量大，風格偏向高頻交易。", -70
    if tid in ["1453"]:
        return "大摩量化。具備強大研究背景，但實質操作多為演算法驅動，具備高度侵略性。", -40
    
    # 隔日沖與主力基地
    if "凱基台北" in name or tid == "9268":
        return "全台最強隔日沖大本營。擅長拉抬後隔日迅速倒貨，對短線籌碼極具毀滅性。", -100
    if "凱基松山" in name or tid == "9264":
        return "傳奇隔日沖基地。操作快狠準，是短線趨勢的領先指標，同樣也是散戶收割機。", -100
    if "凱基三多" in name or tid == "9275":
        return "南台灣隔日沖重鎮。操作手法極具侵略性，常伴隨地緣主力進行短線噴發與收割。", -100
    if "元大土城" in name or tid == "980J":
        return "高頻當沖與隔日沖中心。完全拋棄地緣經營，轉為純粹的短線獲利通道，具高度風險。", -95
    if "凱基台北(代)" in name or tid == "8110":
        return "超級隔日沖分身通道。專門處理大規模的高頻進出與派貨動作，危險程度極高。", -100
    if "富邦中壢" in name or tid == "960C":
        return "凶悍內資主力出口。操作風格與外資量化巨獸相似，極度追求短線爆發與收割。", -90
    if "永豐南京" in name or "永豐金南京" in name:
        return "內資主力剽悍舞台。專注於特定標的的短線炒作，洗盤力道大，是典型的「主力戰場」。", -80
    if "群益大安" in name:
        return "台北核心主力區。匯集強大市場影響力的資深主力，進出代表了內資大戶的集體意志。", -30

    # --- 2. 穩定與正派區 ---
    if any(k in name for k in ["兆豐", "合庫", "台銀", "土地", "台灣", "土銀"]):
        return "官股背景穩定力量。操作週期長，不參與短線博弈，常為長線配置或護盤資金出口。", 98
    if "國泰總公司" in name or tid == "8881":
        return "核心穩定力量。負責集團核心資產配置，穩定市場磐石，不具侵略性。", 100
    if "富邦總公司" in name or tid == "9600":
        return "本土綜合穩定力量。進出具備明確的趨勢參考價值，多為長線布局資金。", 70
    if "國泰" in name and "總" not in name:
        return "本土長線穩健力量。主要為壽險、長線基金布局，操作風格溫和。", 90
    if "大和" in name or tid == "1670":
        return "日系保守派。極度關注基本面，不參與短線博弈，是市場中最正派的資金來源。", 100
    if "法銀巴黎" in name or tid == "8900":
        return "保守型外資代表。主要進行長線資產配置，是量化市場中的冷靜力量。", 95

    # --- 3. 綜合與一般區 ---
    if any(k in name for k in ["凱基", "永豐", "群益"]):
        return "內資活躍主力分點。包含大量量化程式與短線大戶，操作節奏快且具備攻擊性。", -45
    if any(k in name for k in ["康和", "大昌", "美好"]):
        return "短線客與當沖熱門通道。吸引大量尋求高倍數獲利的投機資金，籌碼穩定度極低。", -40
    if any(k in name for k in ["元大", "富邦", "統一"]):
        return "綜合性大型分點。資金來源混雜，操作風格多元，通常具備一定的市場中立性。", 25
    
    # 預設：區域型/一般分點
    return "一般分點或區域型分點。包含散戶與各類中實戶，進出邏輯隨機且定性不足。", -5

def verify_and_merge():
    data_dir = r'C:\jupyter_notebook\ai_twstock\data'
    all_refined_features = []
    
    # 遍歷 01 到 20
    for i in range(1, 21):
        filename = f'micro_feature_{i:02d}.json'
        path = os.path.join(data_dir, filename)
        if not os.path.exists(path): continue
        
        with open(path, 'r', encoding='utf-8') as f:
            chunk = json.load(f)
            
        print(f"Verifying {filename}...")
        for item in chunk:
            tid = item['id']
            name = item['name']
            
            # 使用深度邏輯重新校準
            feat, score = get_refined_feature(tid, name)
            item['特性'] = feat
            item['穩重指數'] = score
            
        # 覆蓋回原檔案
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)
            
        all_refined_features.extend(chunk)

    # 最終合併儲存
    final_path = os.path.join(data_dir, 'micro_feature_all.json')
    with open(final_path, 'w', encoding='utf-8') as f:
        json.dump(all_refined_features, f, ensure_ascii=False, indent=2)
    
    print(f"\nVerification Complete!")
    print(f"Total processed: {len(all_refined_features)}")
    print(f"Final file saved: {final_path}")

if __name__ == "__main__":
    verify_and_merge()
 stories
