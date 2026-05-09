from configparser import ConfigParser
from esun_trade.sdk import SDK
import os

# This is just to inspect the SDK methods
config = ConfigParser()
config.read('C:\\jupyter_notebook\\Stock_Jade_report\\config.ini')
sdk = SDK(config)
print("Methods in sdk:", [m for m in dir(sdk) if not m.startswith('_')])
