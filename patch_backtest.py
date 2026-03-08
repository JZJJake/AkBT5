import re

with open('backend/main.py', 'r') as f:
    content = f.read()

backtest_api = """
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

        # Forward fill the weekly condition to daily
        # Week ends on Friday. The condition calculated for the week ending on Friday
        # is applicable for the days within that week.
        # So we merge based on the week ending date.

        df['week_end'] = df['date'] + pd.to_timedelta((4 - df['date'].dt.dayofweek) % 7, unit='d')
        df = pd.merge(df, weekly_df[['week_j_upward']], left_on='week_end', right_index=True, how='left')
        df['week_j_upward'] = df['week_j_upward'].fillna(False)

        # Pre-calculate shifted values for conditions
        df['m20_1'] = df['ma20'].shift(1)
        df['macdh_1'] = df['macdh'].shift(1)
        df['dm205'] = df['ma20'] - df['ma205']
        df['dm205_1'] = df['dm205'].shift(1)

        df['j_1'] = df['kdj_j'].shift(1)
        df['j_2'] = df['kdj_j'].shift(2)

        # Buy Condition: A3 + Daily KDJJ + Weekly J upward
        cond_a3 = (df['close'] > df['open']) & \\
                  (df['ma20'] > df['m20_1']) & \\
                  (df['ma20'] > df['ma205']) & \\
                  (df['dm205'] > df['dm205_1']) & \\
                  (df['macdh'] > df['macdh_1'])

        cond_kdjj_daily = ((df['j_2'] < df['kdj_k']) | (df['kdj_j'] < df['kdj_k'])) & \\
                    (df['j_1'] < 30) & \\
                    (df['kdj_j'] > df['j_1']) & \\
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

"""

# Insert before the background tasks section
content = content.replace("def background_download_task(symbol: str = None):", backtest_api + "\ndef background_download_task(symbol: str = None):")

with open('backend/main.py', 'w') as f:
    f.write(content)
print("Backtest API added.")
