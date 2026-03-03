from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import pandas as pd
import json
from .data_manager import DB_PATH, get_connection, download_stock_list, download_kline_data, download_fundamental_data

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

@app.get("/api/kline/{symbol}")
def get_kline(symbol: str, period: str = Query("daily")):
    # For now, we only implemented daily. In the future, add weekly/monthly tables and logic.
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM kline_daily WHERE symbol = ? ORDER BY date ASC", conn, params=(symbol,))

        # Replace NaN with None for JSON serialization
        import numpy as np
        df = df.replace([np.inf, -np.inf], np.nan)
        # Convert to float and fillnan with None manually
        # This is strictly required for FastAPI builtin json encoder to avoid 'nan' errors.
        # However pandas `where(pd.notnull(df), None)` doesn't actually cast pandas floats containing NaNs
        # to Python `None` cleanly when the column is float type.
        df_dict = df.to_dict(orient="records")
        for row in df_dict:
            for k, v in row.items():
                if isinstance(v, float) and np.isnan(v):
                    row[k] = None

        return {"symbol": symbol, "data": df_dict}
    except Exception as e:
        return {"error": str(e), "data": []}
    finally:
        conn.close()

def background_download_task(symbol: str = None):
    if not symbol:
        download_stock_list()
        # To download all, we would loop over stock_list.
        # For demonstration and performance, we won't download all automatically here.
        # But we would add a loop in a real app:
        # conn = get_connection()
        # stocks = pd.read_sql_query("SELECT symbol FROM stock_list LIMIT 10", conn)['symbol'].tolist()
        # conn.close()
        # for s in stocks: download_kline_data(s)
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
