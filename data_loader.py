"""
模組名稱：modules/data_loader.py
修改目的：負責取得大盤/個股價量資料與政策事件紀錄檔。
防呆防錯原因：
1. 本地讀檔增加 FileNotFoundError 與 JSONDecodeError 例外攔截，避免路徑錯誤造成系統崩潰。
2. yfinance 資料拉取時加入空值檢查與欄位重整，防止資料缺失引發後續計算異常。
"""

import os
import json
import pandas as pd
import yfinance as yf
import streamlit as st

@st.cache_data(ttl=3600)
def load_policy_events(filepath: str = "data/policy_events.json") -> pd.DataFrame:
    """
    修改目的：載入國安基金與限空令政策事件紀錄檔。
    防呆防錯原因：驗證檔案存在與 JSON 結構完整性，並統一日期格式以利後續與行情資料對齊。
    """
    if not os.path.exists(filepath):
        # 防呆機制：若檔案不存在回傳空 DataFrame，避免主畫面崩潰
        return pd.DataFrame(columns=["date", "type", "name", "marker", "color", "description"])
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            events_data = json.load(f)
        df_events = pd.DataFrame(events_data)
        if not df_events.empty and "date" in df_events.columns:
            # 統一轉換為 yyyy-mm-dd 字串與 datetime，避免比對時型態衝突
            df_events["date"] = pd.to_datetime(df_events["date"]).dt.strftime("%Y-%m-%d")
        return df_events
    except (json.JSONDecodeError, Exception) as e:
        st.error(f"讀取政策事件紀錄檔失敗: {e}")
        return pd.DataFrame(columns=["date", "type", "name", "marker", "color", "description"])

@st.cache_data(ttl=1800)
def fetch_market_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    修改目的：透過 yfinance 取得指定標的與期間的日線價量資料。
    防呆防錯原因：
    1. 驗證資料是否為空，若查無資料或連線失敗拋出明確警示。
    2. 攤平 MultiIndex 欄位結構（yfinance 升級後的常見回傳格式），防止欄位索引報錯。
    """
    try:
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
        if df.empty:
            return pd.DataFrame()
        
        # 防呆防錯：若欄位為 MultiIndex 則取第一層
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.reset_index()
        # 統一 Date 欄位格式為字串 YYYY-MM-DD
        df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
        return df
    except Exception as e:
        st.error(f"獲取市場行情數據失敗 ({ticker}): {e}")
        return pd.DataFrame()
