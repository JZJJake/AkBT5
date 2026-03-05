import akshare as ak
import pandas as pd
import numpy as np
import sqlite3
import os
import ta
import time
import random
from pytdx.hq import TdxHq_API

DB_PATH = "stock_data.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Check if kline_daily exists and has latest columns
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kline_daily'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(kline_daily)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'macd_st_line' not in columns or 'ma20' not in columns:
            print("Database schema outdated. Dropping old kline_daily table...")
            cursor.execute("DROP TABLE kline_daily")

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
            change_pct REAL,
            upper_shadow_pct REAL,
            is_limit_up BOOLEAN,
            ma20 REAL,
            ma205 REAL,
            ztfb3 BOOLEAN,
            ztfb_maxh REAL,
            ztfb_maxl REAL,
            kdj_st INTEGER,
            kdj_tj REAL,
            macd_st_line INTEGER,
            macd_st_dot INTEGER,
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

    # Moving Averages
    df['ma20'] = df['close'].rolling(window=20, min_periods=1).mean()
    df['ma205'] = df['ma20'].rolling(window=5, min_periods=1).mean()

    # Pre-close calculation
    df['pre_close'] = df['close'].shift(1).fillna(df['open'])

    # Change percentage
    df['change_pct'] = (df['close'] - df['pre_close']) / df['pre_close'] * 100

    # Is Limit Up (approximate +9.8% or more)
    df['is_limit_up'] = (df['change_pct'] >= 9.8).astype(int)

    # Upper shadow percentage calculation
    # (High - Max(Open, Close)) / Pre_Close
    df['upper_shadow_pct'] = (df['high'] - df[['open', 'close']].max(axis=1)) / df['pre_close'] * 100

    # ZTFB3 Logic (3-day consolidation after limit up)
    df['ztfb3'] = 0
    df['ztfb_maxh'] = 0.0
    df['ztfb_maxl'] = 0.0

    is_lu = df['is_limit_up'].values
    highs = df['high'].values
    lows = df['low'].values
    ztfb3 = np.zeros(len(df), dtype=int)
    ztfb_maxh = np.zeros(len(df))
    ztfb_maxl = np.zeros(len(df))

    # A limit up followed by 3 days of consolidation
    for i in range(len(df) - 3):
        if is_lu[i] == 1:
            # check next 3 days
            sub_high = highs[i+1:i+4]
            sub_low = lows[i+1:i+4]
            if len(sub_high) == 3:
                ztfb3[i+3] = 1 # Mark the 3rd day of consolidation
                ztfb_maxh[i+3] = sub_high.max()
                ztfb_maxl[i+3] = sub_low.min()

    df['ztfb3'] = ztfb3
    df['ztfb_maxh'] = ztfb_maxh
    df['ztfb_maxl'] = ztfb_maxl

    # Drop pre_close as it is not in our schema and was only used for intermediate calculation
    if 'pre_close' in df.columns:
        df.drop(columns=['pre_close'], inplace=True)

    # Calculate MACD (10, 25, 7) instead of standard (12, 26, 9) per user requirement
    macd = ta.trend.MACD(close=df['close'], window_slow=25, window_fast=10, window_sign=7)
    df['macd'] = macd.macd() # DIFF
    df['macds'] = macd.macd_signal() # DEA
    df['macdh'] = macd.macd_diff() # MACDd / MACD histogram

    # --- Custom MACD Logic ---
    diff_val = df['macd'].values
    xl_macd = df['macd'].diff().fillna(0).values

    tj_macd = np.zeros(len(df))
    tj2_macd = np.zeros(len(df))
    count_tj = 0
    count_tj2 = 0

    for i in range(len(xl_macd)):
        if xl_macd[i] > 0:
            count_tj += 1
        else:
            count_tj = 0

        if xl_macd[i] < 0:
            count_tj2 += 1
        else:
            count_tj2 = 0

        tj_macd[i] = count_tj
        tj2_macd[i] = count_tj2

    macd_st_line = np.zeros(len(df), dtype=int) # 0: default, 1: red, 2: pink
    for i in range(len(df)):
        t_val = int(tj_macd[i])
        t2_val = int(tj2_macd[i])

        pjxl = 0
        if t_val > 0:
            pjxl = xl_macd[i-t_val+1:i+1].sum() / t_val

        pjxl2 = 0
        if t2_val > 0:
            pjxl2 = xl_macd[i-t2_val+1:i+1].sum() / t2_val

        st = (t_val > 0) and (xl_macd[i] > pjxl * 0.7)
        st2 = (t2_val > 0) and (xl_macd[i] > pjxl2 * 0.7)

        if st:
            macd_st_line[i] = 1 # Red
        elif (not st and t_val > 0) or st2:
            macd_st_line[i] = 2 # Pink
        else:
            macd_st_line[i] = 0 # Default

    df['macd_st_line'] = macd_st_line

    dea = df['macds'].values
    macdd = df['macdh'].values

    macd_st_dot = np.zeros(len(df), dtype=int)
    for i in range(1, len(df)):
        cond = (dea[i] > dea[i-1]) and (dea[i] < diff_val[i]) and (macdd[i] > macdd[i-1])
        macd_st_dot[i] = 1 if cond else 0

    df['macd_st_dot'] = macd_st_dot

    # --- Custom KDJ logic ---
    low_list = df['low'].rolling(9, min_periods=1).min()
    high_list = df['high'].rolling(9, min_periods=1).max()
    rsv = (df['close'] - low_list) / (high_list - low_list + 1e-8) * 100

    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    j = 3 * k - 2 * d

    df['kdj_k'] = k
    df['kdj_d'] = d
    df['kdj_j'] = j

    xl = j.diff().fillna(0)
    xl_values = xl.values
    tj_values = np.zeros(len(df))

    count = 0
    for i in range(len(xl_values)):
        if xl_values[i] > 0:
            count += 1
        else:
            count = 0
        tj_values[i] = count
    df['kdj_tj'] = tj_values

    st_values = np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        t_val = int(tj_values[i])
        if t_val > 0:
            pjxl = xl_values[i-t_val+1:i+1].sum() / t_val
            if xl_values[i] > pjxl * 0.7:
                st_values[i] = 1 # Bright Red
            else:
                st_values[i] = 2 # Dark Red
        else:
            st_values[i] = 0 # White
    df['kdj_st'] = st_values

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

# TDX Servers (prioritize ones known to work)
TDX_SERVERS = [
    ('218.75.126.9', 7709),   # 广发证券 (Known to work)
    ('119.147.212.81', 7709), # 招商证券深圳
    ('119.147.164.60', 7709), # 招商证券深圳
    ('106.120.74.86', 7709),  # 招商证券北京
    ('124.74.236.94', 7721),  # 平安证券
    ('114.80.63.12', 7709),   # 东方证券
    ('119.147.171.206', 7709),
    ('119.147.171.207', 7709)
]

def get_tdx_api():
    """Connect to a fast TDX server."""
    api = TdxHq_API()
    for ip, port in TDX_SERVERS:
        try:
            if api.connect(ip, port, time_out=2):
                print(f"Connected to TDX server {ip}:{port}")
                return api
        except:
            pass
    print("Warning: Could not connect to any TDX servers.")
    return api # Return unconnected api to handle failures gracefully

def _get_tdx_market(symbol: str) -> int:
    """Map A-share symbol to TDX market (0 for Shenzhen, 1 for Shanghai)"""
    if symbol.startswith(('6', '9')):
        return 1
    return 0

def sync_all_data():
    """
    Downloads the entire stock list, then fetches QFQ K-lines via Akshare.
    """
    print("Starting sync of all A-share data via Akshare (QFQ)...")
    download_stock_list()

    init_db()

    conn = get_connection()
    try:
        stocks = pd.read_sql_query("SELECT symbol FROM stock_list", conn)['symbol'].tolist()
        latest_dates_df = pd.read_sql_query("SELECT symbol, MAX(date) as latest_date FROM kline_daily GROUP BY symbol", conn)
        latest_dates = latest_dates_df.set_index('symbol')['latest_date'].to_dict()
    except Exception as e:
        print(f"Error reading DB: {e}")
        conn.close()
        return

    try:
        total = len(stocks)
        batch_size = 100
        combined_df_list = []

        for idx, symbol in enumerate(stocks):
            if idx % 10 == 0:
                print(f"[{idx}/{total}] Syncing Akshare data...")

            is_incremental = symbol in latest_dates and latest_dates[symbol] is not None
            latest_db_date = latest_dates.get(symbol)

            try:
                # Need start date to be far back if not incremental
                # Akshare fetches all historical data by default if no start/end date
                df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")

                if df is not None and not df.empty:
                    df = df[['日期', '开盘', '最高', '最低', '收盘', '成交量']]
                    df.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
                    df['symbol'] = symbol
                    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

                    df = calculate_indicators(df)

                    if is_incremental and latest_db_date:
                        df = df[df['date'] > latest_db_date]

                    if not df.empty:
                        combined_df_list.append(df)
            except Exception as e:
                continue

            # Batch insert
            if len(combined_df_list) >= batch_size or idx == total - 1:
                if combined_df_list:
                    combined_df = pd.concat(combined_df_list, ignore_index=True)
                    combined_df.to_sql('kline_daily', conn, if_exists='append', index=False)
                    combined_df_list = []

        print("Full sync complete!")
    finally:
        conn.close()

def download_kline_data(symbol, api=None):
    """
    Fetch historical data for a single stock via Akshare with incremental update support.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(date) FROM kline_daily WHERE symbol=?", (symbol,))
        row = cursor.fetchone()
        latest_date = row[0] if row and row[0] else None

        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
        if df is not None and not df.empty:
            df = df[['日期', '开盘', '最高', '最低', '收盘', '成交量']]
            df.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
            df['symbol'] = symbol
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

            df = calculate_indicators(df)

            if latest_date:
                df = df[df['date'] > latest_date]

            if not df.empty:
                df.to_sql('kline_daily', conn, if_exists='append', index=False)
    except Exception as e:
        print(f"Error downloading kline for {symbol}: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
