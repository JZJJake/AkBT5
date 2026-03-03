import akshare as ak
import time
from concurrent.futures import ThreadPoolExecutor

symbols = ['000001', '000002', '600000', '600036', '000858', '600519', '002594', '601318', '600104', '000333']

def fetch(sym):
    try:
        df = ak.stock_zh_a_hist(symbol=sym, period="daily", start_date="20200101", end_date="20240101", adjust="qfq")
        return len(df)
    except Exception as e:
        return str(e)

start = time.time()
with ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(fetch, symbols))

print("Results:", results)
print(f"Time taken: {time.time() - start:.2f}s")
