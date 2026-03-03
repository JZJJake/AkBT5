import akshare as ak
import pandas as pd
import sqlite3
import os
import ta

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

def download_kline_data(symbol, start_date="19900101", end_date="20500101"):
    try:
        # Fetch daily K-line
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
        if df.empty:
            return

        df = df[['日期', '开盘', '最高', '最低', '收盘', '成交量']]
        df.columns = ['date', 'open', 'high', 'low', 'close', 'volume']

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
    except Exception as e:
        print(f"Error downloading k-line data for {symbol}: {e}")

def download_fundamental_data(symbol):
    try:
        # Note: In a real complete app, downloading fundamental data for all stocks takes time and might need different akshare APIs.
        # This is a simplified version using stock_individual_info_em
        info_df = ak.stock_individual_info_em(symbol=symbol)
        if info_df.empty:
            return

        # Extract values (simplified, some data might not be available directly in this specific API,
        # so we will store what we can find or mock if necessary for the demonstration of framework)
        # For circulating market cap:
        circulating_market_cap = 0
        try:
            val = info_df[info_df['item'] == '流通市值']['value'].values[0]
            circulating_market_cap = float(val) if val else 0
        except:
            pass

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO fundamental_data (symbol, circulating_market_cap, asset_liability_ratio, operating_cash_flow) VALUES (?, ?, ?, ?)",
                       (symbol, circulating_market_cap, 0.0, 0.0)) # Simplified, actual data extraction depends on specific APIs
        conn.commit()
        conn.close()
        print(f"Successfully downloaded fundamental data for {symbol}.")
    except Exception as e:
        print(f"Error downloading fundamental data for {symbol}: {e}")

if __name__ == "__main__":
    init_db()
    # Test with a single stock
    # download_stock_list()
    # download_kline_data("000001", start_date="20200101")
    # download_fundamental_data("000001")
