import tushare as ts
import time

# Note: tushare requires a token for most APIs, but some basic ones might be free.
# We'll see if pro API works without token or with default.
try:
    pro = ts.pro_api()
    df = pro.daily(ts_code='000001.SZ', start_date='20200101', end_date='20240101')
    print(len(df))
except Exception as e:
    print(f"Tushare Error: {e}")
