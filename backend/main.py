from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import pandas as pd
import json
from .data_manager import DB_PATH, get_connection, download_stock_list, download_kline_data, sync_all_data, get_sync_progress

app = FastAPI(title="A-Share Trader Platform")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse('static/index.html')

@app.get("/api/stocks")
def get_stocks():
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT symbol, name FROM stock_list", conn)
        return {"stocks": df.to_dict(orient="records")}
    except Exception as e:
        return {"error": str(e), "stocks": []}
    finally:
        conn.close()

@app.get("/api/screener")
def run_screener():
    conn = get_connection()
    try:
        # Prevent memory bomb by only loading the last 60 days of data across all stocks
        # (need more days to calculate reliable weekly KDJ).
        max_date_df = pd.read_sql_query("SELECT MAX(date) FROM kline_daily", conn)
        max_date_str = max_date_df.iloc[0, 0]

        if not max_date_str:
            return {"error": "No data in database", "stocks": []}

        # We need at least 9 weeks (~63 days) of data to calculate weekly KDJ. Let's fetch 100 days.
        cutoff_date = (pd.to_datetime(max_date_str) - pd.Timedelta(days=100)).strftime('%Y-%m-%d')

        # Load daily data needed for A3 and daily KDJJ, plus required columns for weekly resampling
        df = pd.read_sql_query("SELECT symbol, date, open, high, low, close, volume, ma20, ma205, macdh, kdj_k, kdj_j FROM kline_daily WHERE date >= ?", conn, params=(cutoff_date,))

        if df.empty:
            return {"error": "No recent data", "stocks": []}

        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values(by=['symbol', 'date']).reset_index(drop=True)

        # Calculate shifted columns within groups for daily conditions
        df['m20_1'] = df.groupby('symbol')['ma20'].shift(1)
        df['macdh_1'] = df.groupby('symbol')['macdh'].shift(1)
        df['dm205'] = df['ma20'] - df['ma205']
        df['dm205_1'] = df.groupby('symbol')['dm205'].shift(1)

        df['j_1'] = df.groupby('symbol')['kdj_j'].shift(1)
        df['j_2'] = df.groupby('symbol')['kdj_j'].shift(2)

        # We evaluate the daily condition on the last row for each symbol
        latest_daily = df.groupby('symbol').tail(1).copy()

        cond_a3 = (latest_daily['close'] > latest_daily['open']) & \
                  (latest_daily['ma20'] > latest_daily['m20_1']) & \
                  (latest_daily['ma20'] > latest_daily['ma205']) & \
                  (latest_daily['dm205'] > latest_daily['dm205_1']) & \
                  (latest_daily['macdh'] > latest_daily['macdh_1'])

        cond_kdjj_daily = ((latest_daily['j_2'] < latest_daily['kdj_k']) | (latest_daily['kdj_j'] < latest_daily['kdj_k'])) & \
                    (latest_daily['j_1'] < 30) & \
                    (latest_daily['kdj_j'] > latest_daily['j_1']) & \
                    (latest_daily['j_1'] < latest_daily['j_2'])

        daily_cond = cond_a3 & cond_kdjj_daily & (latest_daily['volume'] > 0)
        daily_pass_symbols = latest_daily[daily_cond]['symbol'].tolist()

        if not daily_pass_symbols:
            return {"error": None, "stocks": []}

        # Optimization: Only calculate weekly KDJ for stocks that passed the daily screener
        df_filtered = df[df['symbol'].isin(daily_pass_symbols)].copy()
        df_filtered.set_index('date', inplace=True)

        final_symbols = []
        for sym, group in df_filtered.groupby('symbol'):
            if len(group) < 30: # Not enough data for weekly indicator calculation
                continue

            # Resample to weekly
            weekly = group.resample('W-FRI').agg({
                'high': 'max',
                'low': 'min',
                'close': 'last'
            }).dropna()

            if len(weekly) < 2:
                continue

            # Calculate Weekly KDJ
            low_list = weekly['low'].rolling(9, min_periods=1).min()
            high_list = weekly['high'].rolling(9, min_periods=1).max()
            rsv = (weekly['close'] - low_list) / (high_list - low_list + 1e-8) * 100

            # ewm equivalent to TDX SMA(..., 3, 1)
            k = rsv.ewm(alpha=1/3, adjust=False).mean()
            d = k.ewm(alpha=1/3, adjust=False).mean()
            j = 3 * k - 2 * d

            # Weekly KDJ J line upward condition: current J > previous J
            j_values = j.values
            if j_values[-1] > j_values[-2]:
                final_symbols.append(sym)

        if not final_symbols:
            return {"error": None, "stocks": []}

        placeholders = ','.join(['?'] * len(final_symbols))
        query_names = f"SELECT symbol, name FROM stock_list WHERE symbol IN ({placeholders})"
        df_selected = pd.read_sql_query(query_names, conn, params=final_symbols)

        return {"error": None, "stocks": df_selected.to_dict(orient="records")}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e), "stocks": []}
    finally:
        conn.close()

@app.get("/api/kline/{symbol}")
def get_kline(symbol: str, period: str = Query("daily")):
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM kline_daily WHERE symbol = ? ORDER BY date ASC", conn, params=(symbol,))

        if df.empty:
            return {"symbol": symbol, "data": []}

        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)

        if period == "weekly":
            # Resample to weekly K-line
            df = df.resample('W-FRI').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()

            # Recalculate indicators for weekly
            from .data_manager import calculate_indicators
            df = calculate_indicators(df)

        elif period == "monthly":
            # Resample to monthly K-line
            df = df.resample('ME').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()

            # Recalculate indicators for monthly
            from .data_manager import calculate_indicators
            df = calculate_indicators(df)

        df.reset_index(inplace=True)
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        df['symbol'] = symbol

        # Replace NaN with None for JSON serialization
        import numpy as np
        df = df.replace([np.inf, -np.inf], np.nan)
        # Convert to float and fillnan with None manually
        # This is strictly required for FastAPI builtin json encoder to avoid 'nan' errors.
        # However pandas `where(pd.notnull(df), None)` doesn't actually cast pandas floats containing NaNs
        # to Python `None` cleanly when the column is float type.
        last_close = float(df['close'].iloc[-1]) if not df.empty else 0.0

        df_dict = df.to_dict(orient="records")
        for row in df_dict:
            for k, v in row.items():
                if isinstance(v, float) and np.isnan(v):
                    row[k] = None

        return {"symbol": symbol, "data": df_dict, "last_close": last_close}
    except Exception as e:
        return {"error": str(e), "data": [], "last_close": 0}
    finally:
        conn.close()

def background_download_task(symbol: str = None):
    if not symbol:
        sync_all_data()
    else:
        # User requested update for specific stock
        download_kline_data(symbol)

@app.get("/api/sync_progress")
def sync_progress_api():
    return get_sync_progress()

@app.post("/api/download")

def trigger_download(background_tasks: BackgroundTasks, symbol: str = None):
    background_tasks.add_task(background_download_task, symbol)
    return {"message": "Download task started in the background."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
