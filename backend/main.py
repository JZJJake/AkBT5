from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import pandas as pd
import json
import os
import sys

# Ensure the parent directory is in the path to allow either module execution or script execution
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.data_manager import DB_PATH, get_connection, download_stock_list, download_kline_data, sync_all_data, get_sync_progress

app = FastAPI(title="A-Share Trader Platform")

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(STATIC_DIR, 'index.html'))

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
        if period == "weekly":
            # Group by ISO week year and week number. This inherently only includes actual trading days in the calculation.
            df['year_week'] = df['date'].dt.isocalendar().year.astype(str) + '-' + df['date'].dt.isocalendar().week.astype(str).str.zfill(2)

            weekly_data = []
            for name, group in df.groupby('year_week'):
                if not group.empty:
                    weekly_data.append({
                        'date': group['date'].iloc[-1], # End of week date
                        'open': group['open'].iloc[0],
                        'high': group['high'].max(),
                        'low': group['low'].min(),
                        'close': group['close'].iloc[-1],
                        'volume': group['volume'].sum()
                    })
            df = pd.DataFrame(weekly_data)

            # Recalculate indicators for weekly based on actual traded weeks
            from backend.data_manager import calculate_indicators
            df = calculate_indicators(df)

        elif period == "monthly":
            # Group by year and month. This only includes actual trading days in the calculation.
            df['year_month'] = df['date'].dt.year.astype(str) + '-' + df['date'].dt.month.astype(str).str.zfill(2)

            monthly_data = []
            for name, group in df.groupby('year_month'):
                if not group.empty:
                    monthly_data.append({
                        'date': group['date'].iloc[-1], # End of month date
                        'open': group['open'].iloc[0],
                        'high': group['high'].max(),
                        'low': group['low'].min(),
                        'close': group['close'].iloc[-1],
                        'volume': group['volume'].sum()
                    })
            df = pd.DataFrame(monthly_data)

            # Recalculate indicators for monthly based on actual traded months
            from backend.data_manager import calculate_indicators
            df = calculate_indicators(df)

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


@app.get("/api/backtest/{symbol}")
def run_backtest(symbol: str):
    conn = get_connection()
    try:
        # Fetch all daily data for the symbol
        df = pd.read_sql_query("SELECT * FROM kline_daily WHERE symbol = ? ORDER BY date ASC", conn, params=(symbol,))
        if df.empty:
            return {"error": "No data found for symbol", "trades": [], "summary": {}}

        df['date'] = pd.to_datetime(df['date'])

        # Recalculate indicators if needed or rely on existing ones
        # For weekly KDJ, we need to calculate it on a rolling basis to avoid lookahead bias.
        # This means for any given day, the "Weekly J" is calculated up to that day's week.

        # Set date as index to facilitate resampling
        df_dt = df.copy()
        df_dt.set_index('date', inplace=True)

        # Calculate weekly KDJ expanding window
        # To avoid lookahead, we group by week and take the last available value of the week up to that day.
        # Actually, standard TDX logic evaluates the weekly indicator based on the week's *current* state.
        # So on Wednesday, the "Weekly" KDJ is calculated using Mon-Wed data.
        # A simpler robust approximation: resample the history up to `current_date` to weekly, and take the last two J values.

        # Optimizing this: calculate rolling weekly aggregates.
        # Since standard weekly KDJ uses Friday closes (or last trading day of week),
        # we can compute the weekly series, then map it back to daily.

        weekly_df = df_dt.resample('W-FRI').agg({
            'high': 'max',
            'low': 'min',
            'close': 'last'
        }).dropna()

        low_list = weekly_df['low'].rolling(9, min_periods=1).min()
        high_list = weekly_df['high'].rolling(9, min_periods=1).max()
        rsv = (weekly_df['close'] - low_list) / (high_list - low_list + 1e-8) * 100
        k = rsv.ewm(alpha=1/3, adjust=False).mean()
        d = k.ewm(alpha=1/3, adjust=False).mean()
        j = 3 * k - 2 * d

        weekly_df['week_j'] = j
        weekly_df['week_j_prev'] = j.shift(1)
        weekly_df['week_j_upward'] = weekly_df['week_j'] > weekly_df['week_j_prev']

        # We need to map the weekly J condition to the daily timeframe *without* look-ahead bias.
        # The true "Weekly J" value on Wednesday only uses data up to Wednesday.
        # Calculating rolling weekly KDJ point-in-time for every day is slow.
        # Approximation avoiding lookahead: For any day, use the weekly J computed at the END of the PREVIOUS week.
        # This guarantees we aren't using future data, though it delays the signal slightly.
        # (Alternatively, you could evaluate the weekly condition intra-week, but that requires row-by-row weekly re-aggregation)

        # We shift the weekly signal by 1 week, so the signal generated on Friday is applied to the *following* week.
        weekly_df['shifted_week_j_upward'] = weekly_df['week_j_upward'].shift(1).fillna(False)

        # Now, group daily dates by the Friday they fall under, and map the shifted signal.
        # `week_end` is the Friday of the CURRENT week.
        # By mapping `shifted_week_j_upward`, we are applying the PREVIOUS week's J condition to this week.
        df['week_end'] = df['date'] + pd.to_timedelta((4 - df['date'].dt.dayofweek) % 7, unit='d')
        df = pd.merge(df, weekly_df[['shifted_week_j_upward']], left_on='week_end', right_index=True, how='left')
        df['week_j_upward'] = df['shifted_week_j_upward'].fillna(False)

        # Pre-calculate shifted values for conditions
        df['m20_1'] = df['ma20'].shift(1)
        df['macdh_1'] = df['macdh'].shift(1)
        df['dm205'] = df['ma20'] - df['ma205']
        df['dm205_1'] = df['dm205'].shift(1)

        df['j_1'] = df['kdj_j'].shift(1)
        df['j_2'] = df['kdj_j'].shift(2)

        # Buy Condition: A3 + Daily KDJJ + Weekly J upward
        cond_a3 = (df['close'] > df['open']) & \
                  (df['ma20'] > df['m20_1']) & \
                  (df['ma20'] > df['ma205']) & \
                  (df['dm205'] > df['dm205_1']) & \
                  (df['macdh'] > df['macdh_1'])

        cond_kdjj_daily = ((df['j_2'] < df['kdj_k']) | (df['kdj_j'] < df['kdj_k'])) & \
                    (df['j_1'] < 30) & \
                    (df['kdj_j'] > df['j_1']) & \
                    (df['j_1'] < df['j_2'])

        df['buy_signal'] = cond_a3 & cond_kdjj_daily & df['week_j_upward'] & (df['volume'] > 0)

        # Sell Condition: Yesterday J > 80, Today J < Yesterday J
        df['sell_signal'] = (df['j_1'] > 80) & (df['kdj_j'] < df['j_1'])

        trades = []
        position = False
        buy_price = 0
        buy_date = None

        initial_capital = 100000.0
        capital = initial_capital
        shares = 0

        total_wins = 0
        total_trades = 0

        for i in range(len(df)):
            row = df.iloc[i]

            if not position and row['buy_signal']:
                # Buy all in at close price
                position = True
                buy_price = row['close']
                buy_date = row['date'].strftime('%Y-%m-%d')

                # Calculate shares (ignoring fees for now)
                shares = capital / buy_price
                capital = 0

            elif position and row['sell_signal']:
                # Sell all at close price
                position = False
                sell_price = row['close']
                sell_date = row['date'].strftime('%Y-%m-%d')

                capital = shares * sell_price
                shares = 0

                profit_pct = (sell_price - buy_price) / buy_price * 100
                total_trades += 1
                if profit_pct > 0:
                    total_wins += 1

                trades.append({
                    'buy_date': buy_date,
                    'buy_price': round(buy_price, 2),
                    'sell_date': sell_date,
                    'sell_price': round(sell_price, 2),
                    'profit_pct': round(profit_pct, 2),
                    'capital_after': round(capital, 2)
                })

        # If still holding at the end, mark it with current price
        if position:
            last_price = df.iloc[-1]['close']
            capital = shares * last_price
            profit_pct = (last_price - buy_price) / buy_price * 100
            trades.append({
                'buy_date': buy_date,
                'buy_price': round(buy_price, 2),
                'sell_date': 'Holding',
                'sell_price': round(last_price, 2),
                'profit_pct': round(profit_pct, 2),
                'capital_after': round(capital, 2)
            })

        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        total_profit_pct = (capital - initial_capital) / initial_capital * 100

        summary = {
            'initial_capital': initial_capital,
            'final_capital': round(capital, 2),
            'total_profit_pct': round(total_profit_pct, 2),
            'total_trades': total_trades,
            'win_rate': round(win_rate, 2)
        }

        return {"trades": trades, "summary": summary}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e), "trades": [], "summary": {}}
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
