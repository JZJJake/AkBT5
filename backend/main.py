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

from backend.data_manager import DB_PATH, get_connection, download_stock_list, download_kline_data, sync_all_data, get_sync_progress, get_screener_progress, _update_screener_progress

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

def run_screener_task():
    _update_screener_progress("running", 0, 100, "正在准备选股数据...", result=None)
    conn = get_connection()
    try:
        # Prevent memory bomb by only loading the last 60 days of data across all stocks
        # (need more days to calculate reliable weekly KDJ).
        max_date_df = pd.read_sql_query("SELECT MAX(date) FROM kline_daily", conn)
        max_date_str = max_date_df.iloc[0, 0]

        if not max_date_str:
            _update_screener_progress("error", 0, 100, "数据库中无数据", result={"error": "No data in database", "stocks": []})
            return

        _update_screener_progress("running", 10, 100, "正在加载并计算日线指标...", result=None)
        # We need at least 150 days to calculate robust weekly MACD (EMA25 needs more history). Let's fetch 180 days.
        cutoff_date = (pd.to_datetime(max_date_str) - pd.Timedelta(days=180)).strftime('%Y-%m-%d')

        # Load daily data needed for A3 and daily KDJJ, plus required columns for weekly resampling
        df = pd.read_sql_query("SELECT symbol, date, open, high, low, close, volume, ma20, ma205, macdh, kdj_k, kdj_j FROM kline_daily WHERE date >= ?", conn, params=(cutoff_date,))

        if df.empty:
            _update_screener_progress("error", 0, 100, "无最近数据", result={"error": "No recent data", "stocks": []})
            return

        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values(by=['symbol', 'date']).reset_index(drop=True)

        _update_screener_progress("running", 30, 100, "执行日线条件过滤...", result=None)
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

        # Daily KDJ Condition:
        # 1. J > K OR J > J_2
        # 2. Previous J (j_1) < 30
        # 3. Current J > Previous J
        cond_kdjj_daily = ((latest_daily['kdj_j'] > latest_daily['kdj_k']) | (latest_daily['kdj_j'] > latest_daily['j_2'])) & \
                    (latest_daily['j_1'] < 30) & \
                    (latest_daily['kdj_j'] > latest_daily['j_1'])

        daily_cond = cond_a3 & cond_kdjj_daily & (latest_daily['volume'] > 0)
        daily_pass_symbols = latest_daily[daily_cond]['symbol'].tolist()

        if not daily_pass_symbols:
            _update_screener_progress("completed", 100, 100, "选股完成", result={"error": None, "stocks": []})
            return

        # Optimization: Only calculate weekly indicator for stocks that passed the daily screener
        df_filtered = df[df['symbol'].isin(daily_pass_symbols)].copy()

        final_symbols = []

        # Group to actual weekly periods
        df_filtered['year_week'] = df_filtered['date'].dt.isocalendar().year.astype(str) + '-' + df_filtered['date'].dt.isocalendar().week.astype(str).str.zfill(2)

        total_daily_pass = len(df_filtered.groupby('symbol'))
        idx = 0
        for sym, group in df_filtered.groupby('symbol'):
            current_progress = 40 + int(60 * (idx / max(1, total_daily_pass)))
            _update_screener_progress("running", current_progress, 100, f"正在进行周线过滤 ({idx+1}/{total_daily_pass})...", result=None)
            idx += 1

            if len(group) < 30: # Not enough data
                continue

            weekly_data = []
            for name, w_group in group.groupby('year_week'):
                if not w_group.empty:
                    weekly_data.append({
                        'date': w_group['date'].iloc[-1],
                        'close': w_group['close'].iloc[-1]
                    })

            weekly = pd.DataFrame(weekly_data)

            if len(weekly) < 3:
                continue

            # Calculate Weekly MA20
            weekly['ma20'] = weekly['close'].rolling(window=20, min_periods=1).mean()

            # Calculate Weekly MACD (10, 25, 7)
            import ta
            macd = ta.trend.MACD(close=weekly['close'], window_slow=25, window_fast=10, window_sign=7)
            weekly['macdh'] = macd.macd_diff()

            # Shifted MACDH
            weekly['macdh_1'] = weekly['macdh'].shift(1)
            weekly['macdh_2'] = weekly['macdh'].shift(2)

            # Weekly Condition:
            # 1. Close > MA20
            # 2. Previous MACDH > Pre-Previous MACDH OR Current MACDH > Previous MACDH
            cond_w_close = weekly['close'].iloc[-1] > weekly['ma20'].iloc[-1]
            cond_w_macd1 = weekly['macdh_1'].iloc[-1] > weekly['macdh_2'].iloc[-1]
            cond_w_macd2 = weekly['macdh'].iloc[-1] > weekly['macdh_1'].iloc[-1]

            if cond_w_close and (cond_w_macd1 or cond_w_macd2):
                final_symbols.append(sym)

        if not final_symbols:
            _update_screener_progress("completed", 100, 100, "选股完成", result={"error": None, "stocks": []})
            return

        placeholders = ','.join(['?'] * len(final_symbols))
        query_names = f"SELECT symbol, name FROM stock_list WHERE symbol IN ({placeholders})"
        df_selected = pd.read_sql_query(query_names, conn, params=final_symbols)

        _update_screener_progress("completed", 100, 100, "选股完成", result={"error": None, "stocks": df_selected.to_dict(orient="records")})

    except Exception as e:
        import traceback
        traceback.print_exc()
        _update_screener_progress("error", 0, 100, f"发生错误: {str(e)}", result={"error": str(e), "stocks": []})
    finally:
        conn.close()

@app.post("/api/screener")
def trigger_screener(background_tasks: BackgroundTasks):
    if get_screener_progress()['status'] == 'running':
        return {"message": "Screener is already running"}
    background_tasks.add_task(run_screener_task)
    return {"message": "Screener task started in the background."}

@app.get("/api/screener_progress")
def screener_progress_api():
    return get_screener_progress()

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

        # Group to actual weekly periods
        df['year_week'] = df['date'].dt.isocalendar().year.astype(str) + '-' + df['date'].dt.isocalendar().week.astype(str).str.zfill(2)

        weekly_data = []
        for name, w_group in df.groupby('year_week'):
            if not w_group.empty:
                weekly_data.append({
                    'year_week': name,
                    'close': w_group['close'].iloc[-1]
                })

        weekly_df = pd.DataFrame(weekly_data)

        # Calculate Weekly MA20
        weekly_df['ma20'] = weekly_df['close'].rolling(window=20, min_periods=1).mean()

        # Calculate Weekly MACD (10, 25, 7)
        import ta
        macd = ta.trend.MACD(close=weekly_df['close'], window_slow=25, window_fast=10, window_sign=7)
        weekly_df['macdh'] = macd.macd_diff()

        # Shifted MACDH
        weekly_df['macdh_1'] = weekly_df['macdh'].shift(1)
        weekly_df['macdh_2'] = weekly_df['macdh'].shift(2)

        # Weekly Condition:
        # 1. Close > MA20
        # 2. Previous MACDH > Pre-Previous MACDH OR Current MACDH > Previous MACDH
        cond_w_close = weekly_df['close'] > weekly_df['ma20']
        cond_w_macd1 = weekly_df['macdh_1'] > weekly_df['macdh_2']
        cond_w_macd2 = weekly_df['macdh'] > weekly_df['macdh_1']

        weekly_df['week_cond'] = cond_w_close & (cond_w_macd1 | cond_w_macd2)

        # We need to map the weekly condition to the daily timeframe *without* look-ahead bias.
        # Approximation avoiding lookahead: For any day, use the weekly condition computed at the END of the PREVIOUS week.
        weekly_df['shifted_week_cond'] = weekly_df['week_cond'].shift(1).fillna(False)

        # Merge back to daily
        df = pd.merge(df, weekly_df[['year_week', 'shifted_week_cond']], on='year_week', how='left')
        df['week_buy_cond'] = df['shifted_week_cond'].fillna(False)

        # Pre-calculate shifted values for conditions
        df['m20_1'] = df['ma20'].shift(1)
        df['macdh_1'] = df['macdh'].shift(1)
        df['dm205'] = df['ma20'] - df['ma205']
        df['dm205_1'] = df['dm205'].shift(1)

        df['j_1'] = df['kdj_j'].shift(1)
        df['j_2'] = df['kdj_j'].shift(2)

        # Buy Condition: A3 + Daily KDJJ + Weekly MACD/MA20 Condition
        cond_a3 = (df['close'] > df['open']) & \
                  (df['ma20'] > df['m20_1']) & \
                  (df['ma20'] > df['ma205']) & \
                  (df['dm205'] > df['dm205_1']) & \
                  (df['macdh'] > df['macdh_1'])

        # Daily KDJ Condition:
        # 1. J > K OR J > J_2
        # 2. Previous J (j_1) < 30
        # 3. Current J > Previous J
        cond_kdjj_daily = ((df['kdj_j'] > df['kdj_k']) | (df['kdj_j'] > df['j_2'])) & \
                    (df['j_1'] < 30) & \
                    (df['kdj_j'] > df['j_1'])

        df['buy_signal'] = cond_a3 & cond_kdjj_daily & df['week_buy_cond'] & (df['volume'] > 0)

        # Pre-calculate shifted values for sell conditions
        df['macd_dif_1'] = df['macd'].shift(1)
        df['macd_dif_2'] = df['macd'].shift(2)
        df['pre_close'] = df['close'].shift(1).fillna(df['open'])

        trades = []
        position = False
        buy_price = 0
        buy_date = None
        buy_idx = -1

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
                buy_idx = i

                # Calculate shares (ignoring fees for now)
                shares = capital / buy_price
                capital = 0

            elif position:
                # Sell Conditions are evaluated after entering the position

                # Condition 1: Single day price change > 5%
                daily_pct_change = (row['close'] - row['pre_close']) / row['pre_close'] * 100
                cond_sell_1 = daily_pct_change > 5

                # Condition 2: Daily MACD Fast Line (DIF) turns downward
                # (Current DIF < Previous DIF) AND (Previous DIF >= Pre-Previous DIF)
                cond_sell_2 = (row['macd'] < row['macd_dif_1']) and (row['macd_dif_1'] >= row['macd_dif_2'])

                # Condition 3: Stop-loss at -3% from buy price
                # If current low drops below buy_price * 0.97, it triggers stop loss. We sell at stop_loss price or open if gap down.
                stop_loss_price = buy_price * 0.97
                cond_sell_3 = row['low'] <= stop_loss_price

                sell_reason = ""
                sell_price = row['close']

                if cond_sell_3:
                    sell_reason = "Stop Loss (-3%)"
                    sell_price = stop_loss_price if row['open'] > stop_loss_price else row['open']
                elif cond_sell_1:
                    sell_reason = "Daily > 5%"
                elif cond_sell_2:
                    sell_reason = "MACD DIF Down"

                if sell_reason:
                    position = False
                    sell_date = row['date'].strftime('%Y-%m-%d')

                    capital = shares * sell_price
                    shares = 0

                    profit_pct = (sell_price - buy_price) / buy_price * 100
                    total_trades += 1
                    if profit_pct > 0:
                        total_wins += 1

                    holding_days = i - buy_idx

                    trades.append({
                        'buy_date': buy_date,
                        'buy_price': round(buy_price, 2),
                        'sell_date': sell_date,
                        'sell_reason': sell_reason,
                        'sell_price': round(sell_price, 2),
                        'profit_pct': round(profit_pct, 2),
                        'holding_days': holding_days,
                        'capital_after': round(capital, 2)
                    })

        # If still holding at the end, mark it with current price
        if position:
            last_price = df.iloc[-1]['close']
            capital = shares * last_price
            profit_pct = (last_price - buy_price) / buy_price * 100
            holding_days = len(df) - 1 - buy_idx

            trades.append({
                'buy_date': buy_date,
                'buy_price': round(buy_price, 2),
                'sell_date': 'Holding',
                'sell_reason': 'None',
                'sell_price': round(last_price, 2),
                'profit_pct': round(profit_pct, 2),
                'holding_days': holding_days,
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
