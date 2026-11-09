"""
模組名稱：data_loader.py
版本識別：20261109_2305
修改目的：
1. 更新版本識別為 20261109_2305。
2. 修復歷史交易日（如 11/06）查無官股排行問題：改採公開 JSON API 帶入精確日期參數，防範 HTML 被擋。
3. 實作歷史落地機制：將各交易日真實官股排行累計至 gov_trades_history.csv，並同步備份至 Google Drive (NSF-tracker)。
4. 欄位名稱維持：「代號」、「名稱」，張數維持在金額之前。
防呆防錯原因：
1. 查詢歷史日期優先檢索本機與雲端快取，減少外部請求次數防封鎖。
2. 若外部 API 或雲端因休市確實查無資料，傳回空 DataFrame，由前端顯示提示，不偽造假數據。
"""

MODULE_VERSION = "20261109_2305"

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

def _query_api_gov_ranking(trade_date: str) -> pd.DataFrame:
    """透過公開端點請求八大官股買賣超真實數據"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.wantgoo.com/investor/bank/buy-rank",
        "Accept": "application/json, text/plain, */*"
    }
    date_compact = trade_date.replace("-", "")
    records = []
    
    # 玩股網公開 JSON 端點 (買超/賣超)
    endpoints = [
        (f"https://www.wantgoo.com/investor/bank/buy-rank-data?date={date_compact}", True),
        (f"https://www.wantgoo.com/investor/bank/sell-rank-data?date={date_compact}", False)
    ]
    
    for url, is_buy in endpoints:
        try:
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                for item in items:
                    c_code = str(item.get("stockNo", item.get("id", ""))).strip()
                    c_name = str(item.get("stockName", item.get("name", ""))).strip()
                    n_vol = float(item.get("netBuySellShare", item.get("volume", 0)))
                    n_amt = float(item.get("netBuySellMoney", item.get("amount", 0))) / 10000.0  # 轉為萬元
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
        except Exception:
            pass

    # 若 JSON 端點無回應，回退嘗試抓取靜態 HTML
    if not records:
        try:
            urls = [
                ("https://www.wantgoo.com/investor/bank/buy-rank", True),
                ("https://www.wantgoo.com/investor/bank/sell-rank", False)
            ]
            for url, is_buy in urls:
                r = requests.get(url, headers=headers, timeout=6)
                if r.status_code == 200:
                    dfs = pd.read_html(r.text)
                    if dfs:
                        tbl = dfs[0]
                        for _, row in tbl.iterrows():
                            parts = str(row.iloc[0]).split()
                            c_code = parts[0] if len(parts) > 0 else ""
                            c_name = parts[1] if len(parts) > 1 else ""
                            n_vol = float(row.iloc[1]) if pd.notnull(row.iloc[1]) else 0.0
                            n_amt = float(row.iloc[2]) if pd.notnull(row.iloc[2]) else 0.0
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
            print(f"[data_loader] 抓取公開真實資料失敗: {e}")

    if records:
        return pd.DataFrame(records)
    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)

@st.cache_data(ttl=1800)
def fetch_gov_branch_trades(trade_date: str) -> pd.DataFrame:
    """取得真實分點交易資料，具備本機快取與雲端同步機制"""
    # 1. 優先嘗試由本機/雲端歷史庫檢索
    if not os.path.exists(LOCAL_GOV_FILE):
        cloud_sync.download_file_from_drive("gov_trades_history.csv", LOCAL_GOV_FILE)
        
    if os.path.exists(LOCAL_GOV_FILE):
        try:
            cached_db = pd.read_csv(LOCAL_GOV_FILE)
            match_rows = cached_db[cached_db["交易日期"] == trade_date]
            if not match_rows.empty:
                return match_rows
        except Exception:
            pass

    # 2. 本地查無紀錄，即時向外部真實公開端點抓取
    new_df = _query_api_gov_ranking(trade_date)
    if not new_df.empty:
        try:
            if os.path.exists(LOCAL_GOV_FILE):
                existing_df = pd.read_csv(LOCAL_GOV_FILE)
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
            if not cached_db.empty and "交易日期" in cached_db.columns:
                mask = (cached_db["交易日期"] >= start_date) & (cached_db["交易日期"] <= end_date)
                return cached_db[mask]
        except Exception:
            pass

    # 若無歷史累積檔，向端點回補近 3 個交易日
    dates = pd.date_range(start_date, end_date, freq="B").strftime("%Y-%m-%d")
    all_dfs = []
    for d in dates[-3:]:
        single_df = fetch_gov_branch_trades(d)
        if not single_df.empty:
            all_dfs.append(single_df)
            
    if not all_dfs:
        return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)
    return pd.concat(all_dfs, ignore_index=True)
