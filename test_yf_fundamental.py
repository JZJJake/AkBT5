import yfinance as yf
t = yf.Ticker('000001.SZ')
info = t.info
print(info.get('marketCap'), info.get('operatingCashflow'))
