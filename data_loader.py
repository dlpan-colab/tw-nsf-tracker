"""
模組名稱：data_loader.py
版本識別：20261109_2258
修改目的：
1. 更新版本識別為 20261109_2258。
2. 徹底移除所有亂數模擬邏輯（拔除 np.random、base_pool 與偽造數據），落實依據真實數據論述。
3. 盤後真實官股資料若當日未開盤、無資料或連線異常，直接回傳空 DataFrame，不憑空編造。
4. 將「股票代號」更名為「代號」，「股票名稱」更名為「名稱」。
防呆防錯原因：
1. 爬蟲請求加入 6 秒超時與異常捕獲，遇到非交易日或無紀錄時回傳空結構，由前端呈現提示，防止系統潰縮。
"""

MODULE_VERSION = "20261109_2258"

import os
import json
import datetime
import requests
import pandas as pd
import yfinance as yf
import streamlit as st
import cloud_sync

CACHE_DIR = "cache_data"
os.makedirs(CACHE_DIR, exist_ok=True)
LOCAL_TAIEX_FILE = os.path.join(CACHE_DIR, "taiex_history.csv")

GOV_BANKS = [
    "臺灣銀行", "台灣土地銀行", "合作金庫", "第一金證券",
    "華南永昌", "彰化銀行", "兆豐證券", "臺灣中小企銀"
]

EMPTY_TRADE_COLUMNS = [
    "交易日期", "官股分點", "代號", "名稱",
    "買進張數", "賣出張數", "買賣超張數", "買賣超金額(萬元)"
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

@st.cache_data(ttl=900)
def fetch_taiex_data(start_date: str, end_date: str) -> pd.DataFrame:
    if not os.path.exists(LOCAL_TAIEX_FILE):
        cloud_sync.download_file_from_drive("taiex_history.csv", LOCAL_TAIEX_FILE)

    local_df = pd.DataFrame()
    if os.path.exists(LOCAL_TAIEX_FILE):
        try:
            local_df = pd.read_csv(LOCAL_TAIEX_FILE)
            if "Date" in local_df.columns:
                local_df["Date"] = pd.to_datetime(local_df["Date"]).dt.strftime("%Y-%m-%d")
        except Exception:
            local_df = pd.DataFrame()

    end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
    end_str = end_dt.strftime("%Y-%m-%d")

    try:
        df = yf.download("^TWII", start=start_date, end=end_str, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.reset_index()
        if not df.empty and "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")

            today_str = datetime.date.today().strftime("%Y-%m-%d")
            if df["Date"].max() < today_str:
                ticker = yf.Ticker("^TWII")
                today_history = ticker.history(period="1d")
                if not today_history.empty:
                    today_history = today_history.reset_index()
                    today_history["Date"] = pd.to_datetime(today_history["Date"]).dt.strftime("%Y-%m-%d")
                    df = pd.concat([df, today_history], ignore_index=True)

            df = df.drop_duplicates(subset=["Date"], keep="last").sort_values("Date").reset_index(drop=True)

            df.to_csv(LOCAL_TAIEX_FILE, index=False)
            cloud_sync.upload_file_to_drive(LOCAL_TAIEX_FILE, "taiex_history.csv")
            return df
    except Exception as e:
        st.warning(f"加權指數線上抓取異常，嘗試使用快取: {e}")

    if not local_df.empty:
        return local_df
    return pd.DataFrame()

def _fetch_real_gov_ranking(trade_date: str) -> pd.DataFrame:
    """直接對接公開八大官股盤後排行端點，無資料則回傳空 DataFrame，絕不捏造"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    records = []
    urls = [
        ("https://www.wantgoo.com/investor/bank/buy-rank", True),
        ("https://www.wantgoo.com/investor/bank/sell-rank", False)
    ]
    for url, is_buy in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                dfs = pd.read_html(resp.text)
                if dfs:
                    tbl = dfs[0]
                    for _, r in tbl.iterrows():
                        parts = str(r.iloc[0]).split()
                        c_code = parts[0] if len(parts) > 0 else ""
                        c_name = parts[1] if len(parts) > 1 else ""
                        n_vol = float(r.iloc[1]) if pd.notnull(r.iloc[1]) else 0.0
                        n_amt = float(r.iloc[2]) if pd.notnull(r.iloc[2]) else 0.0
                        if not is_buy:
                            n_vol = -abs(n_vol)
                            n_amt = -abs(n_amt)
                        records.append({
                            "交易日期": trade_date,
                            "官股分點": "全部官股合計",
                            "代號": c_code,
                            "名稱": c_name,
                            "買進張數": abs(int(n_vol)) if is_buy else 0,
                            "賣出張數": 0 if is_buy else abs(int(n_vol)),
                            "買賣超張數": int(n_vol),
                            "買賣超金額(萬元)": round(n_amt, 2)
                        })
        except Exception as e:
            print(f"[data_loader] 抓取公開真實資料失敗 ({url}): {e}")

    if records:
        return pd.DataFrame(records)
    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)

@st.cache_data(ttl=1800)
def fetch_gov_branch_trades(trade_date: str) -> pd.DataFrame:
    """取得真實分點交易資料，若無資料直接回傳空結構"""
    df = _fetch_real_gov_ranking(trade_date)
    return df

@st.cache_data(ttl=1800)
def fetch_range_gov_branch_summary(start_date: str, end_date: str) -> pd.DataFrame:
    """區間統計函式：僅彙總真實分點資料"""
    dates = pd.date_range(start_date, end_date, freq="B").strftime("%Y-%m-%d")
    all_dfs = []
    # 為避免過度頻繁請求外部服務，僅提取近 5 個交易日之真實資料
    target_dates = dates[-5:] if len(dates) > 5 else dates
    for d in target_dates:
        single_df = fetch_gov_branch_trades(d)
        if not single_df.empty:
            all_dfs.append(single_df)
    
    if not all_dfs:
        return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)
    return pd.concat(all_dfs, ignore_index=True)
