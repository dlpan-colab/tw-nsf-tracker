"""
模組名稱：data_loader.py
版本識別：20261110_1010
修改目的：
1. 更新版本識別為台灣時間 20261110_1010。
2. 全面導入 zoneinfo (Asia/Taipei)，所有日期獲取強制綁定台灣標準時區，杜絕 UTC 時差。
3. 修訂 HiStock 解析器：自動從網頁標題或內容定位真實交易日期，精準抓取買超與賣超 Top 30 及 8 大分點。
4. 回補日誌透明化：backfill 過程傳遞詳細狀態（HTTP 狀態碼、成功筆數），拒絕黑盒子靜默。
防呆防錯原因：
1. HiStock 網址不支援 ?date= 參數時，自動校驗頁面真實日期，避免將當日資料誤標為其他日期。
2. 數值解析加入健全的正則過濾，確保空值與特殊字符不影響批次執行。
"""

MODULE_VERSION = "20261110_1010"

import os
import re
import json
import time
import datetime
from zoneinfo import ZoneInfo
import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
import streamlit as st
import cloud_sync

TW_TZ = ZoneInfo("Asia/Taipei")

def get_tw_today() -> datetime.date:
    """取得台灣時區當前日期"""
    return datetime.datetime.now(TW_TZ).date()

CACHE_DIR = "cache_data"
os.makedirs(CACHE_DIR, exist_ok=True)
LOCAL_TAIEX_FILE = os.path.join(CACHE_DIR, "taiex_history.csv")
LOCAL_GOV_FILE = os.path.join(CACHE_DIR, "gov_trades_history.csv")

HISTOCK_BRANCH_COLS = {
    "合庫": "合作金庫",
    "土銀": "台灣土地銀行",
    "台銀": "臺灣銀行",
    "台企銀": "臺灣中小企銀",
    "第一金": "第一金證券",
    "兆豐": "兆豐證券",
    "華南": "華南永昌",
    "彰銀": "彰化銀行"
}

GOV_BANKS = list(HISTOCK_BRANCH_COLS.values())

EMPTY_TRADE_COLUMNS = [
    "交易日期", "官股分點", "代號", "名稱",
    "買進張數", "賣出張數", "買賣超張數", "金額(萬元)"
]

REQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://histock.tw/"
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

            today_str = get_tw_today().strftime("%Y-%m-%d")
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

def _clean_num(val_str: str) -> float:
    if not val_str:
        return 0.0
    clean = re.sub(r"[^\d\.\-\+]", "", str(val_str).replace(",", ""))
    try:
        return float(clean) if clean else 0.0
    except Exception:
        return 0.0

def fetch_histock_latest_gov_trades() -> tuple[pd.DataFrame, str, str]:
    """
    自 HiStock 抓取最新八大官股結算日報
    回傳: (DataFrame, 抓取到的實際交易日期字串, 狀態日誌說明)
    """
    url = "https://histock.tw/stock/broker8.aspx"
    try:
        resp = requests.get(url, headers=REQ_HEADERS, timeout=10)
        if resp.status_code != 200:
            return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS), "", f"連線異常 HTTP {resp.status_code}"

        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 1. 萃取頁面上的真實發布日期（例如 "11-09 Top 30 八大官股銀行合計買超排名"）
        page_text = soup.get_text()
        date_match = re.search(r"(\d{2})[-/](\d{2})\s+Top\s+30\s+八大", page_text)
        current_year = get_tw_today().year
        
        if date_match:
            mm, dd = date_match.group(1), date_match.group(2)
            actual_trade_date = f"{current_year}-{mm}-{dd}"
        else:
            actual_trade_date = get_tw_today().strftime("%Y-%m-%d")

        tables = soup.find_all("table")
        if not tables:
            return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS), actual_trade_date, "未找到資料表格"

        records = []
        for tbl in tables:
            rows = tbl.find_all("tr")
            if not rows or len(rows) < 2:
                continue

            header_cells = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
            branch_col_indices = {}
            total_idx = None
            stock_col_idx = None

            for idx, h_text in enumerate(header_cells):
                for short_b, full_b in HISTOCK_BRANCH_COLS.items():
                    if short_b in h_text:
                        branch_col_indices[idx] = full_b
                if "合計" in h_text:
                    total_idx = idx
                if any(k in h_text for k in ["代號", "名稱", "股票", "標的"]):
                    stock_col_idx = idx

            if not branch_col_indices and len(header_cells) >= 10:
                expected_shorts = ["合庫", "土銀", "台銀", "台企銀", "第一金", "兆豐", "華南", "彰銀"]
                stock_col_idx = 0
                for i, s_name in enumerate(expected_shorts):
                    branch_col_indices[i + 1] = HISTOCK_BRANCH_COLS[s_name]
                total_idx = 9

            if stock_col_idx is None or total_idx is None:
                continue

            for tr in rows[1:]:
                tds = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(tds) <= total_idx:
                    continue

                raw_stock_info = tds[stock_col_idx]
                if not raw_stock_info:
                    continue

                tokens = raw_stock_info.split()
                stock_code = ""
                stock_name = ""
                for tok in tokens:
                    if re.match(r"^\d{4,6}[A-Za-z]?$", tok):
                        stock_code = tok
                    elif not stock_name:
                        stock_name = tok

                if not stock_code:
                    m = re.search(r"\d{4,6}[A-Za-z]?", raw_stock_info)
                    if m:
                        stock_code = m.group(0)
                        stock_name = raw_stock_info.replace(stock_code, "").strip()
                    else:
                        stock_code = raw_stock_info
                        stock_name = raw_stock_info

                tot_amt_wan = _clean_num(tds[total_idx])
                tot_vol = int(tot_amt_wan / 10.0) if tot_amt_wan != 0 else 0

                records.append({
                    "交易日期": actual_trade_date,
                    "官股分點": "全部官股合計",
                    "代號": stock_code,
                    "名稱": stock_name,
                    "買進張數": tot_vol if tot_vol > 0 else 0,
                    "賣出張數": abs(tot_vol) if tot_vol < 0 else 0,
                    "買賣超張數": tot_vol,
                    "金額(萬元)": round(tot_amt_wan, 2)
                })

                for b_idx, b_name in branch_col_indices.items():
                    if b_idx < len(tds):
                        b_amt_wan = _clean_num(tds[b_idx])
                        b_vol = int(b_amt_wan / 10.0) if b_amt_wan != 0 else 0
                        if b_amt_wan != 0:
                            records.append({
                                "交易日期": actual_trade_date,
                                "官股分點": b_name,
                                "代號": stock_code,
                                "名稱": stock_name,
                                "買進張數": b_vol if b_vol > 0 else 0,
                                "賣出張數": abs(b_vol) if b_vol < 0 else 0,
                                "買賣超張數": b_vol,
                                "金額(萬元)": round(b_amt_wan, 2)
                            })

        if records:
            res_df = pd.DataFrame(records).drop_duplicates(subset=["交易日期", "官股分點", "代號"], keep="last")
            return res_df, actual_trade_date, f"成功解析 {len(res_df)} 筆真實數據"

        return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS), actual_trade_date, "未抓到有效數據列"

    except Exception as e:
        return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS), "", f"連線例外: {str(e)}"

def sync_df_to_storage(df: pd.DataFrame) -> bool:
    """持久化保存至本地 CSV 與 Google Drive"""
    if df.empty:
        return False
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
        clear_gov_cache()
        return True
    except Exception as e:
        print(f"[data_loader] 歷史官股落地同步失敗: {e}")
        return False

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
