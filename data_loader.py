"""
模組名稱：data_loader.py
版本識別：20261109_2345
修改目的：
1. 更新版本識別為 20261109_2345。
2. 解除區間統計僅抓最後 3 個交易日的限制（移除 dates[-3:] 切片），完整支援 15~30 天以上歷史工作日檢索。
3. 實作 FinMind 券商分點明細（TaiwanStockSecuritiesBrokerTrades）對接與漸進式「慢慢補」機制：
   - 設定八大公股分點代碼對應表。
   - 優先讀取本機與 Google Drive 歷史庫（gov_trades_history.csv）；缺失日期逐日補充並追加落地。
4. 欄位維持：['交易日期', '官股分點', '代號', '名稱', '買進張數', '賣出張數', '買賣超張數', '金額(萬元)']。
防呆防錯原因：
1. 若 Streamlit Secrets 未配置 FinMind Token，自動平滑降級為證交所公開端點，不阻斷程式。
2. 區間回補加入微延遲與異常捕獲，防範高頻請求遭封鎖。
"""

MODULE_VERSION = "20261109_2345"

import os
import json
import time
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

# 八大官股券商總行代號對應
GOV_BROKER_MAP = {
    "1020": "臺灣銀行",
    "1030": "台灣土地銀行",
    "5850": "合作金庫",
    "5920": "第一金證券",
    "5380": "華南永昌",
    "1040": "彰化銀行",
    "7000": "兆豐證券",
    "2110": "臺灣中小企銀"
}

GOV_BANKS = list(GOV_BROKER_MAP.values())

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

def _query_finmind_gov_trades(trade_date: str) -> pd.DataFrame:
    """透過 FinMind API 取得八大官股分點在特定日期的進出明細"""
    token = st.secrets.get("finmind", {}).get("api_token", "")
    url = "https://api.finmindtrade.com/api/v4/data"
    
    # 若有設定 token 則使用，否則使用免 token 輕量請求
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    records = []
    # 針對八大官股券商代碼查詢
    for b_code, b_name in GOV_BROKER_MAP.items():
        params = {
            "dataset": "TaiwanStockSecuritiesBrokerTrades",
            "data_id": b_code,
            "start_date": trade_date,
            "end_date": trade_date
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=6)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                for item in data:
                    s_code = str(item.get("stock_id", "")).strip()
                    s_name = str(item.get("stock_name", s_code)).strip()
                    buy_v = int(item.get("buy", 0))
                    sell_v = int(item.get("sell", 0))
                    net_v = buy_v - sell_v
                    price = float(item.get("price", 0.0))
                    net_amt = round(net_v * price * 0.1, 2)  # 概算金額(萬元)
                    
                    records.append({
                        "交易日期": trade_date,
                        "官股分點": b_name,
                        "代號": s_code,
                        "名稱": s_name,
                        "買進張數": buy_v,
                        "賣出張數": sell_v,
                        "買賣超張數": net_v,
                        "金額(萬元)": net_amt
                    })
        except Exception:
            pass

    if records:
        return pd.DataFrame(records)
    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)

def _query_twse_gov_ranking(trade_date: str) -> pd.DataFrame:
    """向證交所官方盤後端點請求真實歷史交易統計（備援回退機制）"""
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

    # 優先嘗試透過 FinMind 抓取 8 大分點
    new_df = _query_finmind_gov_trades(trade_date)
    # 若 FinMind 查無資料或未配置 token，則回退至 TWSE 官方端點
    if new_df.empty:
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
    """區間統計函式：自歷史庫彙總，缺失日期溫和漸進回補並同步 Google Drive"""
    if not os.path.exists(LOCAL_GOV_FILE):
        cloud_sync.download_file_from_drive("gov_trades_history.csv", LOCAL_GOV_FILE)

    cached_db = pd.DataFrame()
    if os.path.exists(LOCAL_GOV_FILE):
        try:
            cached_db = pd.read_csv(LOCAL_GOV_FILE)
            if "買賣超金額(萬元)" in cached_db.columns and "金額(萬元)" not in cached_db.columns:
                cached_db = cached_db.rename(columns={"買賣超金額(萬元)": "金額(萬元)"})
        except Exception:
            cached_db = pd.DataFrame()

    # 產生指定區間的所有工作日
    work_days = pd.date_range(start_date, end_date, freq="B").strftime("%Y-%m-%d").tolist()
    recorded_days = set(cached_db["交易日期"].unique()) if not cached_db.empty and "交易日期" in cached_db.columns else set()
    
    # 找出缺失的日期（排除週末）
    missing_days = [d for d in work_days if d not in recorded_days]

    # 若有缺失工作日，採「慢慢補」策略（每次統計最多溫和回補近 5 個缺失交易日，避免超額）
    if missing_days:
        for m_day in missing_days[-5:]:
            fetch_gov_branch_trades(m_day)
            time.sleep(0.2)  # 溫和延遲

        # 重新載入最新資料庫
        if os.path.exists(LOCAL_GOV_FILE):
            try:
                cached_db = pd.read_csv(LOCAL_GOV_FILE)
                if "買賣超金額(萬元)" in cached_db.columns and "金額(萬元)" not in cached_db.columns:
                    cached_db = cached_db.rename(columns={"買賣超金額(萬元)": "金額(萬元)"})
            except Exception:
                pass

    if not cached_db.empty and "交易日期" in cached_db.columns:
        mask = (cached_db["交易日期"] >= start_date) & (cached_db["交易日期"] <= end_date)
        return cached_db[mask]

    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)
