import yfinance as yf
import time

def test_yfinance_batch():
    start = time.time()
    tickers = ['000001.SZ', '000002.SZ', '600000.SS', '600036.SS', '000858.SZ', '600519.SS', '002594.SZ', '601318.SS', '600104.SS', '000333.SZ']
    df = yf.download(tickers, start="2010-01-01", end="2024-01-01", group_by='ticker')
    print(f"Time taken for batch (yfinance): {time.time() - start:.2f}s")
    for t in tickers:
        print(t, len(df[t].dropna()))

test_yfinance_batch()
