import sqlite3
import pandas as pd
from backend.data_manager import get_connection, calculate_indicators

def fix():
    conn = get_connection()
    df = pd.read_sql_query("SELECT symbol, date, open, high, low, close, volume FROM kline_daily", conn)

    # Process per symbol
    fixed_dfs = []
    for symbol, group in df.groupby('symbol'):
        # Ensure chronological
        group = group.sort_values('date')
        updated = calculate_indicators(group)
        fixed_dfs.append(updated)

    final_df = pd.concat(fixed_dfs, ignore_index=True)

    # Update DB
    cursor = conn.cursor()
    cursor.execute("DELETE FROM kline_daily")
    conn.commit()

    final_df.to_sql('kline_daily', conn, if_exists='append', index=False)
    conn.close()
    print("Database fixed successfully.")

if __name__ == '__main__':
    fix()
