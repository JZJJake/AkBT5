import akshare as ak
import pandas as pd
import sqlite3
import os
import ta
import time
import random
import yfinance as yf

DB_PATH = "stock_data.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # 股票列表 (Stock List)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_list (
            symbol TEXT PRIMARY KEY,
            name TEXT
        )
    ''')

    # K线数据 (K-line data - Daily)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS kline_daily (
            symbol TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            macd REAL,
            macds REAL,
            macdh REAL,
            kdj_k REAL,
            kdj_d REAL,
            kdj_j REAL,
            PRIMARY KEY (symbol, date)
        )
    ''')

    # 基本面数据 (Fundamental Data)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fundamental_data (
            symbol TEXT PRIMARY KEY,
            circulating_market_cap REAL,
            asset_liability_ratio REAL,
            operating_cash_flow REAL
        )
    ''')

    conn.commit()
    conn.close()

def calculate_indicators(df):
    if df.empty or len(df) < 30:
        return df

    # Calculate MACD (10, 25, 7) instead of standard (12, 26, 9) per user requirement
    macd = ta.trend.MACD(close=df['close'], window_slow=25, window_fast=10, window_sign=7)
    df['macd'] = macd.macd()
    df['macds'] = macd.macd_signal()
    df['macdh'] = macd.macd_diff()

    # Calculate KDJ (9, 3, 3)
    stoch = ta.momentum.StochasticOscillator(high=df['high'], low=df['low'], close=df['close'], window=9, smooth_window=3)
    df['kdj_k'] = stoch.stoch()
    # ta.momentum.StochasticOscillator doesn't have d and j directly in a way we want often, let's manually calculate K, D, J using standard formulas if needed, or use pandas directly for standard KDJ.

    # KDJ standard calculation:
    low_list = df['low'].rolling(9, min_periods=1).min()
    high_list = df['high'].rolling(9, min_periods=1).max()
    rsv = (df['close'] - low_list) / (high_list - low_list) * 100

    # SMA for K and D
    df['kdj_k'] = rsv.ewm(com=2, adjust=False).mean()
    df['kdj_d'] = df['kdj_k'].ewm(com=2, adjust=False).mean()
    df['kdj_j'] = 3 * df['kdj_k'] - 2 * df['kdj_d']

    return df

def download_stock_list():
    try:
        # Fetch A-share stock list
        stock_info_df = ak.stock_info_a_code_name()
        stock_list_df = stock_info_df[['code', 'name']]
        stock_list_df.columns = ['symbol', 'name']

        conn = get_connection()
        stock_list_df.to_sql('stock_list', conn, if_exists='replace', index=False)
        conn.close()
        print(f"Successfully downloaded {len(stock_list_df)} stocks.")
    except Exception as e:
        print(f"Error downloading stock list: {e}")

def _get_yf_ticker(symbol: str) -> str:
    """Map A-share symbol (000001) to yfinance format (000001.SZ)"""
    # Beijing exchange starts with 4, 8, 9, SH starts with 6, SZ with 0, 3
    if symbol.startswith('6'):
        return f"{symbol}.SS"
    elif symbol.startswith(('0', '3')):
        return f"{symbol}.SZ"
    else:
        return f"{symbol}.BJ"  # Some might not be supported well

def download_kline_data(symbol, start_date="2010-01-01", end_date=None, retries=3):
    yf_ticker = _get_yf_ticker(symbol)

    for attempt in range(retries):
        try:
            # Batch downloading is handled in sync_all_data. This is for single fetch.
            df = yf.download(yf_ticker, start=start_date, end=end_date, progress=False, multi_level_index=False)
            if df.empty:
                return

            # Reset index to get Date column
            df.reset_index(inplace=True)

            # yfinance returns columns like: Date, Open, High, Low, Close, Adj Close, Volume
            df = df[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']].copy()
            df.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

            # Calculate indicators
            df = calculate_indicators(df)
            df['symbol'] = symbol

            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM kline_daily WHERE symbol = ?", (symbol,))
            conn.commit()
            df.to_sql('kline_daily', conn, if_exists='append', index=False)
            conn.close()
            print(f"Successfully downloaded K-line data for {symbol}.")
            return
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(random.uniform(1.0, 2.0))
            else:
                print(f"Error downloading k-line data for {symbol}: {e}")

def download_fundamental_data(symbol, retries=3):
    yf_ticker = _get_yf_ticker(symbol)
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(yf_ticker)
            info = ticker.info

            circulating_market_cap = info.get('marketCap', 0.0)
            operating_cash_flow = info.get('operatingCashflow', 0.0)
            # Yfinance doesn't easily expose asset-liability without fetching full financials.
            # We will use Total Debt / Total Assets if available.
            total_debt = info.get('totalDebt', 0.0)
            total_assets = info.get('totalAssets', 1.0) # Avoid div by zero
            asset_liability_ratio = (total_debt / total_assets) if total_assets else 0.0

            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO fundamental_data (symbol, circulating_market_cap, asset_liability_ratio, operating_cash_flow) VALUES (?, ?, ?, ?)",
                           (symbol, circulating_market_cap, asset_liability_ratio, operating_cash_flow))
            conn.commit()
            conn.close()
            return
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(random.uniform(1.0, 2.0))
            else:
                # Insert empty
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO fundamental_data (symbol, circulating_market_cap, asset_liability_ratio, operating_cash_flow) VALUES (?, ?, ?, ?)",
                               (symbol, 0.0, 0.0, 0.0))
                conn.commit()
                conn.close()

def sync_all_data():
    """
    Downloads the entire stock list, then batches K-line download using yfinance for immense speedup.
    """
    print("Starting fast batch sync of all A-share data via yfinance...")
    download_stock_list()

    conn = get_connection()
    try:
        stocks = pd.read_sql_query("SELECT symbol FROM stock_list", conn)['symbol'].tolist()
    except Exception as e:
        print(f"Error reading stock list from DB: {e}")
        conn.close()
        return

    # Pre-clean DB
    cursor = conn.cursor()
    cursor.execute("DELETE FROM kline_daily")
    conn.commit()
    conn.close()

    # Process in chunks of 50 to avoid memory explosion or yf limits
    chunk_size = 50
    total = len(stocks)

    print(f"Downloading historical data for {total} stocks in batches...")
    for i in range(0, total, chunk_size):
        chunk = stocks[i:i+chunk_size]
        yf_tickers = [_get_yf_ticker(sym) for sym in chunk]

        try:
            # Multi-threaded download
            df_batch = yf.download(yf_tickers, start="2010-01-01", group_by='ticker', threads=True, progress=False)

            conn = get_connection()
            for j, symbol in enumerate(chunk):
                yf_ticker = yf_tickers[j]

                # yfinance returns single level columns if only 1 ticker was requested/succeeded
                # otherwise multi-index. Handle both:
                try:
                    if len(chunk) == 1:
                        df_stock = df_batch.copy()
                    else:
                        if yf_ticker not in df_batch:
                            continue
                        df_stock = df_batch[yf_ticker].copy()

                    if df_stock.empty or df_stock['Close'].isna().all():
                        continue

                    df_stock.dropna(subset=['Close'], inplace=True)
                    df_stock.reset_index(inplace=True)

                    df_stock = df_stock[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']].copy()
                    df_stock.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
                    df_stock['date'] = pd.to_datetime(df_stock['date']).dt.strftime('%Y-%m-%d')

                    df_stock = calculate_indicators(df_stock)
                    df_stock['symbol'] = symbol

                    # Batch insert
                    df_stock.to_sql('kline_daily', conn, if_exists='append', index=False)

                except Exception as e:
                    print(f"Error processing stock {symbol} from batch: {e}")

            conn.close()
            print(f"[{min(i+chunk_size, total)}/{total}] Batch processed.")

        except Exception as e:
            print(f"Error fetching batch {i}: {e}")

    print("Full fast sync complete.")


if __name__ == "__main__":
    init_db()
    # Test with a single stock
    # download_stock_list()
    # download_kline_data("000001", start_date="20200101")
    # download_fundamental_data("000001")
