"""
模組名稱：data_loader.py
版本識別：20261109_2310
修改目的：
1. 更新版本識別為 20261109_2310。
2. 輸出欄位更名：「買賣超金額(萬元)」改為「金額(萬元)」。
3. 欄位架構維持：['交易日期', '官股分點', '代號', '名稱', '買進張數', '賣出張數', '買賣超張數', '金額(萬元)']。
4. 維持證交所官方盤後端點串接與 Google Drive 同步機制。
防呆防錯原因：
1. 資料欄位更名保持全域一致，避免與 app.py 產生 KeyError。
"""

MODULE_VERSION = "20261109_2310"

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
LOCAL_GOV_FILE = os.path.join(CACHE_DIR, "gov_trades_history.csv")

GOV_BANKS = [
    "臺灣銀行", "台灣土地銀行", "合作金庫", "第一金證券",
    "華南永昌", "彰化銀行", "兆豐證券", "臺灣中小企銀"
]

EMPTY_TRADE_COLUMNS = [
    "交易日期", "官股分點", "代號", "名稱",
    "買進張數", "賣出張數", "買賣超張數", "金額(萬元)"
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

def _clean_num(val) -> float:
    if pd.isnull(val):
        return 0.0
    s = str(val).replace(",", "").strip()
    try:
        return float(s)
    except Exception:
        return 0.0

def _query_twse_gov_ranking(trade_date: str) -> pd.DataFrame:
    """向證交所官方盤後端點請求真實歷史分點交易統計"""
    date_compact = trade_date.replace("-", "")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01"
    }
    twse_url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_compact}&selectType=ALLBUT0999&response=json"
    records = []
    
    try:
        resp = requests.get(twse_url, headers=headers, timeout=8)
        if resp.status_code == 200:
            json_data = resp.json()
            if json_data.get("stat") == "OK" and "data" in json_data:
                raw_rows = json_data["data"]
                for row in raw_rows:
                    if len(row) >= 19:
                        stock_code = str(row[0]).strip()
                        stock_name = str(row[1]).strip()
                        buy_vol = int(_clean_num(row[2]) / 1000)
                        sell_vol = int(_clean_num(row[3]) / 1000)
                        net_vol = int(_clean_num(row[4]) / 1000)
                        net_amt = round(_clean_num(row[4]) * 0.01, 2)
                        
                        records.append({
                            "交易日期": trade_date,
                            "官股分點": "全部官股合計",
                            "代號": stock_code,
                            "名稱": stock_name,
                            "買進張數": buy_vol,
                            "賣出張數": sell_vol,
                            "買賣超張數": net_vol,
                            "金額(萬元)": net_amt
                        })
    except Exception as e:
        print(f"[data_loader] 證交所官方端點請求失敗: {e}")

    if records:
        return pd.DataFrame(records)
    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)

@st.cache_data(ttl=1800)
def fetch_gov_branch_trades(trade_date: str) -> pd.DataFrame:
    """取得真實分點交易資料，具備本機快取與雲端同步機制"""
    if not os.path.exists(LOCAL_GOV_FILE):
        cloud_sync.download_file_from_drive("gov_trades_history.csv", LOCAL_GOV_FILE)
        
    if os.path.exists(LOCAL_GOV_FILE):
        try:
            cached_db = pd.read_csv(LOCAL_GOV_FILE)
            if "買賣超金額(萬元)" in cached_db.columns and "金額(萬元)" not in cached_db.columns:
                cached_db = cached_db.rename(columns={"買賣超金額(萬元)": "金額(萬元)"})
            match_rows = cached_db[cached_db["交易日期"] == trade_date]
            if not match_rows.empty:
                return match_rows
        except Exception:
            pass

    new_df = _query_twse_gov_ranking(trade_date)
    if not new_df.empty:
        try:
            if os.path.exists(LOCAL_GOV_FILE):
                existing_df = pd.read_csv(LOCAL_GOV_FILE)
                if "買賣超金額(萬元)" in existing_df.columns and "金額(萬元)" not in existing_df.columns:
                    existing_df = existing_df.rename(columns={"買賣超金額(萬元)": "金額(萬元)"})
                combined = pd.concat([existing_df, new_df], ignore_index=True)
                combined = combined.drop_duplicates(subset=["交易日期", "官股分點", "代號"], keep="last")
            else:
                combined = new_df
            combined.to_csv(LOCAL_GOV_FILE, index=False)
            cloud_sync.upload_file_to_drive(LOCAL_GOV_FILE, "gov_trades_history.csv")
        except Exception as e:
            print(f"[data_loader] 歷史官股落地同步失敗: {e}")
        return new_df

    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)

@st.cache_data(ttl=1800)
def fetch_range_gov_branch_summary(start_date: str, end_date: str) -> pd.DataFrame:
    """區間統計函式：自歷史資料庫彙總真實資料"""
    if not os.path.exists(LOCAL_GOV_FILE):
        cloud_sync.download_file_from_drive("gov_trades_history.csv", LOCAL_GOV_FILE)

    if os.path.exists(LOCAL_GOV_FILE):
        try:
            cached_db = pd.read_csv(LOCAL_GOV_FILE)
            if "買賣超金額(萬元)" in cached_db.columns and "金額(萬元)" not in cached_db.columns:
                cached_db = cached_db.rename(columns={"買賣超金額(萬元)": "金額(萬元)"})
            if not cached_db.empty and "交易日期" in cached_db.columns:
                mask = (cached_db["交易日期"] >= start_date) & (cached_db["交易日期"] <= end_date)
                return cached_db[mask]
        except Exception:
            pass

    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)
