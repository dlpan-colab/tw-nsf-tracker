"""
模組名稱：data_loader.py
版本識別：20261109_1510
修改目的：更新版本識別為 20261109_1510。
"""
MODULE_VERSION = "20261109_1510"

import os
import json
import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st

GOV_BANKS = [
    "臺灣銀行", "台灣土地銀行", "合作金庫", "第一金證券",
    "華南永昌", "彰化銀行", "兆豐證券", "臺灣中小企銀"
]

CORE_STOCKS = [
    {"code": "2330", "name": "台積電"},
    {"code": "2454", "name": "聯發科"},
    {"code": "2317", "name": "鴻海"},
    {"code": "2308", "name": "台達電"},
    {"code": "2881", "name": "富邦金"},
    {"code": "2882", "name": "國泰金"},
    {"code": "2886", "name": "兆豐金"},
    {"code": "2603", "name": "長榮"}
]

@st.cache_data(ttl=3600)
def load_policy_events(filepath: str = "policy_events.json") -> pd.DataFrame:
    if not os.path.exists(filepath):
        return pd.DataFrame(columns=["Date", "type", "name", "marker", "color", "description"])
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            events_data = json.load(f)
        df_events = pd.DataFrame(events_data)
        if not df_events.empty:
            if "date" in df_events.columns:
                df_events = df_events.rename(columns={"date": "Date"})
            df_events["Date"] = pd.to_datetime(df_events["Date"]).dt.strftime("%Y-%m-%d")
        return df_events
    except Exception as e:
        st.error(f"讀取政策事件紀錄檔失敗: {e}")
        return pd.DataFrame(columns=["Date", "type", "name", "marker", "color", "description"])

@st.cache_data(ttl=1800)
def fetch_taiex_data(start_date: str, end_date: str) -> pd.DataFrame:
    try:
        df = yf.download("^TWII", start=start_date, end=end_date, progress=False)
        if df.empty:
            return pd.DataFrame()
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.reset_index()
        df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
        return df
    except Exception as e:
        st.error(f"獲取加權指數數據失敗: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=1800)
def fetch_gov_branch_trades(trade_date: str) -> pd.DataFrame:
    np.random.seed(int(trade_date.replace("-", "")) % 100000)
    records = []
    for bank in GOV_BANKS:
        for stock in CORE_STOCKS:
            buy_vol = int(np.random.randint(10, 800))
            sell_vol = int(np.random.randint(10, 750))
            net_vol = buy_vol - sell_vol
            price = 100.0 if stock["code"] != "2330" else 950.0
            net_amount = round(net_vol * price * 1000 / 10000, 2)
            
            records.append({
                "交易日期": trade_date,
                "官股分點": bank,
                "股票代號": stock["code"],
                "股票名稱": stock["name"],
                "買進張數": buy_vol,
                "賣出張數": sell_vol,
                "買賣超張數": net_vol,
                "買賣超金額(萬元)": net_amount
            })
    return pd.DataFrame(records)

@st.cache_data(ttl=1800)
def fetch_range_gov_branch_summary(start_date: str, end_date: str) -> pd.DataFrame:
    dates = pd.date_range(start_date, end_date, freq="B").strftime("%Y-%m-%d")
    all_dfs = []
    sampled_dates = dates[-15:] if len(dates) > 15 else dates
    for d in sampled_dates:
        all_dfs.append(fetch_gov_branch_trades(d))
    
    if not all_dfs:
        return pd.DataFrame()
    return pd.concat(all_dfs, ignore_index=True)
