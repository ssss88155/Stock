from configparser import ConfigParser
from esun_trade.sdk import SDK
from esun_trade.order import OrderObject
from esun_trade.constant import (APCode, Trade, PriceFlag, BSFlag, Action)

'''
# 1. 讀取 config
config = ConfigParser()
config.read(r'./config.simulation.ini')   # ← 你的路徑

# 2. 登入（**不要加任何參數**，讓 SDK 自己跳輸入框）
sdk = SDK(config)
sdk.login()          # ← 這裡執行後會跳出 Enter cert password:

print("✅ 登入成功！")

# 3. 下單測試（模擬買 1 股 2884 跌停，絕對不會真的扣錢）
order = OrderObject(
    buy_sell=Action.Buy,
    price_flag=PriceFlag.LimitDown,
    price=None,
    stock_no="2884",
    quantity=1,
)
sdk.place_order(order)
print("🎉 委託單已成功送出！（模擬環境）")
'''

from configparser import ConfigParser
from esun_trade.sdk import SDK

# 讀取設定檔
config = ConfigParser()
config.read('./config.ini')
# 將設定檔內容寫至 SDK 中，並確認是否已設定密碼
sdk = SDK(config)