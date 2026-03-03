import baostock as bs
import pandas as pd
import time

def fetch_baostock():
    start = time.time()
    lg = bs.login()
    print('login respond error_code:'+lg.error_code)
    print('login respond  error_msg:'+lg.error_msg)

    # 详细指标参数，需要在API文档中查阅
    rs = bs.query_history_k_data_plus("sz.000001",
        "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
        start_date='2010-01-01', end_date='2024-01-01',
        frequency="d", adjustflag="3")

    print('query_history_k_data_plus respond error_code:'+rs.error_code)
    print('query_history_k_data_plus respond  error_msg:'+rs.error_msg)

    data_list = []
    while (rs.error_code == '0') & rs.next():
        data_list.append(rs.get_row_data())
    result = pd.DataFrame(data_list, columns=rs.fields)

    bs.logout()
    print(f"Time taken for one stock (baostock): {time.time() - start:.2f}s, rows: {len(result)}")
    return result

fetch_baostock()
