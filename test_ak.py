import akshare as ak

try:
    stock_info_df = ak.stock_info_a_code_name()
    print("Success")
except Exception as e:
    print(f"Error: {e}")
