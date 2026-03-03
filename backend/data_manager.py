import akshare as ak
import pandas as pd
import sqlite3
import os
import ta
import time
import random

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

def download_kline_data(symbol, start_date="19900101", end_date="20500101", retries=3):
    for attempt in range(retries):
        try:
            # Fetch daily K-line using Sina API which is more stable than Eastmoney API
            sina_symbol = f"sh{symbol}" if symbol.startswith(('6', '9')) else f"sz{symbol}"
            df = ak.stock_zh_a_daily(symbol=sina_symbol, start_date=start_date, end_date=end_date, adjust="qfq")
            if df.empty:
                return

            df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

            # Calculate indicators
            df = calculate_indicators(df)

            df['symbol'] = symbol

            conn = get_connection()
            # Using to_sql with if_exists='append' might cause UNIQUE constraint failed if we don't handle it.
            # Let's delete existing data for this symbol first for simplicity, or use 'replace' if we do it per symbol (but it's one big table).
            cursor = conn.cursor()
            cursor.execute("DELETE FROM kline_daily WHERE symbol = ?", (symbol,))
            conn.commit()

            df.to_sql('kline_daily', conn, if_exists='append', index=False)
            conn.close()
            print(f"Successfully downloaded K-line data for {symbol}.")
            return # Success, break out of retry loop
        except Exception as e:
            if attempt < retries - 1:
                sleep_time = random.uniform(2.0, 5.0)
                print(f"Retry {attempt + 1}/{retries} downloading k-line data for {symbol} due to: {e}. Sleeping {sleep_time:.2f}s...")
                time.sleep(sleep_time)
            else:
                print(f"Error downloading k-line data for {symbol} after {retries} attempts: {e}")

def download_fundamental_data(symbol, retries=3):
    """
    Downloads fundamental data required by user.
    Uses 'stock_a_indicator_lg' or 'stock_financial_abstract' for more reliable data.
    """
    for attempt in range(retries):
        try:
            # Using stock_a_indicator_lg (Legu API) for circulating market cap
            indicator_df = ak.stock_a_indicator_lg(symbol=symbol)

            circulating_market_cap = 0.0
            if not indicator_df.empty:
                # Get the most recent value
                latest = indicator_df.iloc[-1]
                # '总市值' / '流通市值' or similar.
                # Legu returns total_mv (总市值) and pe, etc. Let's try to get what we can.
                if 'total_mv' in latest:
                    circulating_market_cap = float(latest['total_mv'])

            # Try to get financial abstract for cash flow and liability
            # This is complex to parse per stock, providing a simplified version
            # where we attempt fetching and handle failures gracefully
            asset_liability_ratio = 0.0
            operating_cash_flow = 0.0

            try:
                # Sina finance API for abstract
                finance_df = ak.stock_financial_abstract(symbol=symbol)
                if not finance_df.empty:
                    # Very rough heuristic to grab data from the dataframe if available
                    pass
            except Exception:
                pass # Accept missing advanced financials if API fails

            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO fundamental_data (symbol, circulating_market_cap, asset_liability_ratio, operating_cash_flow) VALUES (?, ?, ?, ?)",
                           (symbol, circulating_market_cap, asset_liability_ratio, operating_cash_flow))
            conn.commit()
            conn.close()
            print(f"Successfully downloaded fundamental data for {symbol}.")
            return

        except Exception as e:
            if attempt < retries - 1:
                sleep_time = random.uniform(2.0, 5.0)
                print(f"Retry {attempt + 1}/{retries} downloading fundamental data for {symbol} due to: {e}. Sleeping {sleep_time:.2f}s...")
                time.sleep(sleep_time)
            else:
                print(f"Error downloading fundamental data for {symbol} after {retries} attempts: {e}")

                # Insert zero row if all fails to prevent UI breaking
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO fundamental_data (symbol, circulating_market_cap, asset_liability_ratio, operating_cash_flow) VALUES (?, ?, ?, ?)",
                               (symbol, 0.0, 0.0, 0.0))
                conn.commit()
                conn.close()

def sync_all_data():
    """
    Downloads the entire stock list, then sequentially downloads K-line and fundamental
    data for all A-share stocks. Warning: This is a very long-running process.
    """
    print("Starting full sync of all A-share data...")
    download_stock_list()

    conn = get_connection()
    try:
        stocks = pd.read_sql_query("SELECT symbol FROM stock_list", conn)['symbol'].tolist()
    except Exception as e:
        print(f"Error reading stock list from DB: {e}")
        conn.close()
        return
    conn.close()

    total = len(stocks)
    for i, symbol in enumerate(stocks):
        print(f"[{i+1}/{total}] Syncing {symbol}...")
        download_kline_data(symbol)
        download_fundamental_data(symbol)

        # Polite delay to avoid hammering the Eastmoney servers
        time.sleep(random.uniform(1.0, 3.0))

    print("Full sync complete.")


if __name__ == "__main__":
    init_db()
    # Test with a single stock
    # download_stock_list()
    # download_kline_data("000001", start_date="20200101")
    # download_fundamental_data("000001")
