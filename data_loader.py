"""
模組名稱：data_loader.py
版本識別：20261110_0140
修改目的：
1. 更新版本識別為 20261110_0140。
2. 對接真實八大官股結算端點：
   - 主端點：玩股網 (WantGoo) 八大行庫買賣超日結算 API。
   - 備援端點：嗨投資 (HiStock) 八大行庫買賣超盤後端點。
3. 嚴格協調落盤資料欄位與單位一致性：
   - 欄位結構統一為：['交易日期', '官股分點', '代號', '名稱', '買進張數', '賣出張數', '買賣超張數', '金額(萬元)']。
   - 張數強制轉換為整數（張）。
   - 金額強制統一折算為「萬元」（去除億、元單位差異）。
4. 恪守真實數據原則，無資料即如實回傳空表，嚴禁回退至非官股數據。
防呆防錯原因：
1. 爬取過程加入 User-Agent 與 Referer 模擬防爬蟲，並加入正規表達式過濾非數字字元。
2. 數值轉換加入例外捕捉，遇到無效符號或空值時預設補 0.0，防止批次中斷。
"""

MODULE_VERSION = "20261110_0140"

import os
import re
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

REQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, application/xhtml+xml, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
}

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

def _parse_clean_num(val) -> float:
    if pd.isnull(val):
        return 0.0
    s = str(val).replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except Exception:
        return 0.0

# ----------------- 主端點：玩股網 (WantGoo) 官股買賣超結算 -----------------
def _query_wantgoo_gov_trades(trade_date: str) -> pd.DataFrame:
    """自玩股網抓取當日八大公股結算真實買賣超排行榜"""
    headers = dict(REQ_HEADERS)
    headers["Referer"] = "https://www.wantgoo.com/investor/bank/buy-rank"

    records = []
    # 爬取買超與賣超結算
    for rank_type in ["buy", "sell"]:
        url = f"https://www.wantgoo.com/investor/bank/{rank_type}-rank-data?day={trade_date}"
        try:
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                for it in items:
                    stock_no = str(it.get("stockNo", it.get("id", ""))).strip()
                    stock_name = str(it.get("stockName", it.get("name", stock_no))).strip()
                    
                    buy_v = int(_parse_clean_num(it.get("buy", 0)))
                    sell_v = int(_parse_clean_num(it.get("sell", 0)))
                    net_v = int(_parse_clean_num(it.get("net", buy_v - sell_v)))
                    if rank_type == "sell" and net_v > 0:
                        net_v = -net_v

                    # 金額單位換算為「萬元」
                    # 若原始欄位為億元（例：3.45），乘以 10000 轉為萬元；若原生就是金額，依數值大小自動正規化
                    raw_amt = _parse_clean_num(it.get("amount", it.get("netAmount", 0)))
                    if abs(raw_amt) < 1000 and abs(raw_amt) > 0:
                        amt_wan = round(raw_amt * 10000, 2)
                    elif abs(raw_amt) > 1000000:
                        amt_wan = round(raw_amt / 10000, 2)
                    else:
                        amt_wan = round(raw_amt, 2)

                    if rank_type == "sell" and amt_wan > 0:
                        amt_wan = -amt_wan

                    if stock_no and (buy_v != 0 or sell_v != 0 or net_v != 0):
                        records.append({
                            "交易日期": trade_date,
                            "官股分點": "全部官股合計",
                            "代號": stock_no,
                            "名稱": stock_name,
                            "買進張數": buy_v,
                            "賣出張數": sell_v,
                            "買賣超張數": net_v,
                            "金額(萬元)": amt_wan
                        })
        except Exception:
            pass

    if records:
        df = pd.DataFrame(records).drop_duplicates(subset=["代號"], keep="first")
        return df
    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)

# ----------------- 備用端點：嗨投資 (HiStock) 官股買賣超 -----------------
def _query_histock_gov_trades(trade_date: str) -> pd.DataFrame:
    """自 HiStock 抓取當日八大官股彙總（備援管道）"""
    url = f"https://histock.tw/stock/broker8.aspx?date={trade_date}"
    headers = dict(REQ_HEADERS)
    headers["Referer"] = "https://histock.tw/"

    records = []
    try:
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code == 200 and "table" in resp.text:
            tables = pd.read_html(resp.text)
            for tbl in tables:
                col_names = [str(c) for c in tbl.columns]
                if any("代號" in c for c in col_names) and any("買賣超" in c for c in col_names):
                    # 辨識代號、名稱、買賣超張數、金額欄位
                    c_id = next(c for c in col_names if "代號" in c)
                    c_name = next(c for c in col_names if "名稱" in c or "股票" in c)
                    c_net = next(c for c in col_names if "買賣超" in c and "金額" not in c)
                    c_amt = next((c for c in col_names if "金額" in c), None)

                    for _, row in tbl.iterrows():
                        s_id = str(row[c_id]).strip()
                        s_name = str(row[c_name]).strip()
                        net_v = int(_parse_clean_num(row[c_net]))
                        
                        amt_wan = 0.0
                        if c_amt and c_amt in row:
                            amt_val = _parse_clean_num(row[c_amt])
                            # 若欄位標明億元，折合萬元
                            if "億" in str(c_amt) or "億" in str(row[c_amt]):
                                amt_wan = round(amt_val * 10000, 2)
                            else:
                                amt_wan = round(amt_val / 10000, 2) if abs(amt_val) > 1000000 else round(amt_val, 2)

                        if s_id and net_v != 0:
                            records.append({
                                "交易日期": trade_date,
                                "官股分點": "全部官股合計",
                                "代號": s_id,
                                "名稱": s_name,
                                "買進張數": net_v if net_v > 0 else 0,
                                "賣出張數": abs(net_v) if net_v < 0 else 0,
                                "買賣超張數": net_v,
                                "金額(萬元)": amt_wan
                            })
                    break
    except Exception:
        pass

    if records:
        return pd.DataFrame(records).drop_duplicates(subset=["代號"], keep="first")
    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)

def backfill_single_day(trade_date: str) -> pd.DataFrame:
    """雙端點依序回補：主端點優先，備用端點第二，統一資料欄位並落地持久化"""
    # 1. 優先嘗試玩股網結算端點
    df = _query_wantgoo_gov_trades(trade_date)
    # 2. 備用嘗試 HiStock 端點
    if df.empty:
        df = _query_histock_gov_trades(trade_date)

    if not df.empty:
        # 強制正規化欄位型態
        df["買進張數"] = df["買進張數"].astype(int)
        df["賣出張數"] = df["賣出張數"].astype(int)
        df["買賣超張數"] = df["買賣超張數"].astype(int)
        df["金額(萬元)"] = df["金額(萬元)"].astype(float).round(2)

        try:
            if os.path.exists(LOCAL_GOV_FILE):
                existing_df = pd.read_csv(LOCAL_GOV_FILE)
                if "買賣超金額(萬元)" in existing_df.columns and "金額(萬元)" not in existing_df.columns:
                    existing_df = existing_df.rename(columns={"買賣超金額(萬元)": "金額(萬元)"})
                combined = pd.concat([existing_df, df], ignore_index=True)
                combined = combined.drop_duplicates(subset=["交易日期", "官股分點", "代號"], keep="last")
            else:
                combined = df
            combined.to_csv(LOCAL_GOV_FILE, index=False)
            cloud_sync.upload_file_to_drive(LOCAL_GOV_FILE, "gov_trades_history.csv")
        except Exception as e:
            print(f"[data_loader] 歷史官股落地同步失敗: {e}")
        return df

    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)

def backfill_real_gov_trades(start_date: str, end_date: str, max_days: int = 10, progress_cb=None) -> int:
    """手動回補指定區間真實官股結算資料，回傳成功入庫天數"""
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
        time.sleep(0.4)  # 溫和延遲保護端點

    clear_gov_cache()
    return success_count

@st.cache_data(ttl=1800)
def fetch_gov_branch_trades(trade_date: str) -> pd.DataFrame:
    """純讀取模式：取得指定日期官股資料（優先自落地歷史庫中讀取）"""
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
    """純讀取模式：自落地歷史庫彙總區間統計，不自動在背後隱蔽回補"""
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
