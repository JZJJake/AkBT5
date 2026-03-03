import yfinance as yf
import time

def test_yfinance():
    start = time.time()
    df = yf.download('000001.SZ', start="2010-01-01", end="2024-01-01")
    print(f"Time taken for one stock (yfinance): {time.time() - start:.2f}s, rows: {len(df)}")

test_yfinance()
