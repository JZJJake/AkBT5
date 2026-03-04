from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import pandas as pd
import json
from .data_manager import DB_PATH, get_connection, download_stock_list, download_kline_data, download_fundamental_data, sync_all_data

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
        # Prevent memory bomb by only loading the last 15 days of data across all stocks.
        max_date_df = pd.read_sql_query("SELECT MAX(date) FROM kline_daily", conn)
        max_date_str = max_date_df.iloc[0, 0]

        if not max_date_str:
            return {"error": "No data in database", "stocks": []}

        cutoff_date = (pd.to_datetime(max_date_str) - pd.Timedelta(days=15)).strftime('%Y-%m-%d')

        df = pd.read_sql_query("SELECT symbol, date, open, close, volume, ma20, ma205, macdh, kdj_k, kdj_j FROM kline_daily WHERE date >= ?", conn, params=(cutoff_date,))

        if df.empty:
            return {"error": "No recent data", "stocks": []}

        df = df.sort_values(by=['symbol', 'date']).reset_index(drop=True)

        # Calculate shifted columns within groups
        df['m20_1'] = df.groupby('symbol')['ma20'].shift(1)
        df['macdh_1'] = df.groupby('symbol')['macdh'].shift(1)
        df['dm205'] = df['ma20'] - df['ma205']
        df['dm205_1'] = df.groupby('symbol')['dm205'].shift(1)

        df['j_1'] = df.groupby('symbol')['kdj_j'].shift(1)
        df['j_2'] = df.groupby('symbol')['kdj_j'].shift(2)

        # We only want to evaluate the last row for each symbol
        latest = df.groupby('symbol').tail(1).copy()

        # Removed missing fundamental data filters (JYJE, Market Cap, STAR) as requested.
        # final condition relies strictly on pure price action / technicals: A3 AND KDJJ

        cond_a3 = (latest['close'] > latest['open']) & \
                  (latest['ma20'] > latest['m20_1']) & \
                  (latest['ma20'] > latest['ma205']) & \
                  (latest['dm205'] > latest['dm205_1']) & \
                  (latest['macdh'] > latest['macdh_1'])

        cond_kdjj = ((latest['j_2'] < latest['kdj_k']) | (latest['kdj_j'] < latest['kdj_k'])) & \
                    (latest['j_1'] < 30) & \
                    (latest['kdj_j'] > latest['j_1']) & \
                    (latest['j_1'] < latest['j_2'])

        final_cond = cond_a3 & cond_kdjj & (latest['volume'] > 0)

        selected_symbols = latest[final_cond]['symbol'].tolist()

        if not selected_symbols:
            return {"error": None, "stocks": []}

        placeholders = ','.join(['?'] * len(selected_symbols))
        query_names = f"SELECT symbol, name FROM stock_list WHERE symbol IN ({placeholders})"
        df_selected = pd.read_sql_query(query_names, conn, params=selected_symbols)

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
        download_fundamental_data(symbol)

@app.post("/api/download")
def trigger_download(background_tasks: BackgroundTasks, symbol: str = None):
    background_tasks.add_task(background_download_task, symbol)
    return {"message": "Download task started in the background."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
