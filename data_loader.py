"""
模組名稱：data_loader.py 
版本識別：20261110_0110
修改目的：
1. 更新版本識別為 20261110_0110。
2. 徹底拔除證交所三大法人 T86 請求代碼與假官股降級邏輯，嚴禁使用非官股數據充數。
3. 八大官股分點唯一對接 FinMind TaiwanStockSecuritiesBrokerTrades 真實券商代碼。
4. 獨立提供 purge_gov_database() 清除髒資料庫函式，供手動清理按鈕調用。
5. 獨立提供 backfill_real_gov_trades() 回補函式，支援天數參數化與前端進度回報回呼。
防呆防錯原因：
1. 若 FinMind 未配置 Token 或查無資料，如實回傳空表，絕不偷跑其他外部數據填補。
2. 清除資料庫時同步覆蓋本機與 Google Drive 空檔，避免舊污染快取被重新下載。
"""

MODULE_VERSION = "20261110_0110"

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

# 八大官股券商總行代號與名稱（精確真實分點）
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

def purge_gov_database() -> bool:
    """手動專用：清空本機與 Google Drive 上的官股歷史資料庫"""
    try:
        empty_df = pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)
        empty_df.to_csv(LOCAL_GOV_FILE, index=False)
        cloud_sync.upload_file_to_drive(LOCAL_GOV_FILE, "gov_trades_history.csv")
        clear_gov_cache()
        return True
    except Exception as e:
        print(f"[data_loader] 清空歷史資料庫失敗: {e}")
        return False

def clear_gov_cache():
    """清除 Streamlit 記憶體快取"""
    fetch_range_gov_branch_summary.clear()
    fetch_gov_branch_trades.clear()

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

def _query_finmind_gov_trades(trade_date: str) -> pd.DataFrame:
    """純真實來源：自 FinMind 取得 8 大公股券商總行當日明細"""
    token = st.secrets.get("finmind", {}).get("api_token", "")
    url = "https://api.finmindtrade.com/api/v4/data"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    records = []
    
    for b_code, b_name in GOV_BROKER_MAP.items():
        params = {
            "dataset": "TaiwanStockSecuritiesBrokerTrades",
            "data_id": b_code,
            "start_date": trade_date,
            "end_date": trade_date
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                for item in data:
                    s_code = str(item.get("stock_id", "")).strip()
                    s_name = str(item.get("stock_name", s_code)).strip()
                    buy_v = int(item.get("buy", 0))
                    sell_v = int(item.get("sell", 0))
                    net_v = buy_v - sell_v
                    price = float(item.get("price", 0.0))
                    net_amt = round(net_v * price * 0.1, 2)
                    
                    if buy_v > 0 or sell_v > 0:
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
        df_rec = pd.DataFrame(records)
        # 由真實 8 大分點聚合一筆「全部官股合計」
        df_sum = df_rec.groupby(["交易日期", "代號", "名稱"], as_index=False).agg({
            "買進張數": "sum",
            "賣出張數": "sum",
            "買賣超張數": "sum",
            "金額(萬元)": "sum"
        })
        df_sum["官股分點"] = "全部官股合計"
        return pd.concat([df_rec, df_sum], ignore_index=True)

    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)

def backfill_single_day(trade_date: str) -> pd.DataFrame:
    """回補單日真實官股資料並落地持久化"""
    new_df = _query_finmind_gov_trades(trade_date)
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

def backfill_real_gov_trades(start_date: str, end_date: str, max_days: int = 10, progress_cb=None) -> int:
    """
    手動專用：回補指定區間內的真實官股日報資料
    回傳：成功補齊入庫的交易天數
    """
    if not os.path.exists(LOCAL_GOV_FILE):
        cloud_sync.download_file_from_drive("gov_trades_history.csv", LOCAL_GOV_FILE)

    cached_db = pd.DataFrame()
    if os.path.exists(LOCAL_GOV_FILE):
        try:
            cached_db = pd.read_csv(LOCAL_GOV_FILE)
        except Exception:
            cached_db = pd.DataFrame()

    work_days = pd.date_range(start_date, end_date, freq="B").strftime("%Y-%m-%d").tolist()
    recorded_days = set(cached_db["交易日期"].unique()) if not cached_db.empty and "交易日期" in cached_db.columns else set()
    missing_days = [d for d in work_days if d not in recorded_days]

    targets = missing_days[-max_days:] if max_days > 0 else missing_days
    success_count = 0

    for idx, t_day in enumerate(targets):
        if progress_cb:
            progress_cb((idx + 1) / len(targets), t_day)
        res = backfill_single_day(t_day)
        if not res.empty:
            success_count += 1
        time.sleep(0.3)  # 溫和延遲保護 API

    clear_gov_cache()
    return success_count

@st.cache_data(ttl=1800)
def fetch_gov_branch_trades(trade_date: str) -> pd.DataFrame:
    """純讀取模式：取得指定日期的官股資料（優先自落地庫提取）"""
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

    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)

@st.cache_data(ttl=1800)
def fetch_range_gov_branch_summary(start_date: str, end_date: str) -> pd.DataFrame:
    """純讀取模式：自乾淨歷史庫彙整區間統計，不自動在背後隱蔽回補"""
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
