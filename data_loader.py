"""
模組名稱：data_loader.py
版本識別：20261111_2358
修改目的：
1. 更新版本識別為台灣時間 20261111_2358。
2. print 強制加入 flush=True，根除 Linux 緩衝區阻擋後台終端機輸出問題。
3. fetch_histock_latest_gov_trades 回傳擴充 debug_info，將解析到的所有表格結構與欄位完整回傳給前台。
4. 放寬 HiStock 表格匹配門檻，兼容單層與 MultiIndex 欄位名稱。
防呆防錯原因：
1. 避免過濾條件過苛導致全部表格被跳過，直接向前端公開結構。
2. 保持金額為萬元、張數為整數的資料庫一致性要求。
"""

MODULE_VERSION = "20261111_2358"

import os
import re
import json
import time
import datetime
import traceback
from io import StringIO
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
        print(f"[data_loader] 清空歷史資料庫失敗: {e}", flush=True)
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

def _clean_num(val) -> float:
    if val is None or pd.isna(val):
        return 0.0
    clean = re.sub(r"[^\d\.\-\+]", "", str(val).replace(",", ""))
    try:
        return float(clean) if clean else 0.0
    except Exception:
        return 0.0

def fetch_histock_latest_gov_trades() -> tuple[pd.DataFrame, str, str, list]:
    """
    自 HiStock 抓取最新八大官股結算日報並打印底層詳細診斷日誌
    回傳: (DataFrame, 實際交易日期, 狀態說明, 結構診斷列表)
    """
    url = "https://histock.tw/stock/broker8.aspx"
    print("\n" + "=" * 60, flush=True)
    print(f"[DEBUG_HISTOCK] 連線請求: {url}", flush=True)
    debug_tables_info = []
    
    try:
        resp = requests.get(url, headers=REQ_HEADERS, timeout=12)
        print(f"[DEBUG_HISTOCK] HTTP 狀態: {resp.status_code}, 內容總字元: {len(resp.text)}", flush=True)
        if resp.status_code != 200 or not resp.text:
            return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS), "", f"連線異常 HTTP {resp.status_code}", []

        # 1. 萃取日期
        soup = BeautifulSoup(resp.text, "html.parser")
        page_text = soup.get_text()
        date_match = re.search(r"(\d{2})[-/](\d{2})\s+Top\s+30\s+八大", page_text)
        current_year = get_tw_today().year
        if date_match:
            mm, dd = date_match.group(1), date_match.group(2)
            actual_trade_date = f"{current_year}-{mm}-{dd}"
            print(f"[DEBUG_HISTOCK] 辨識發布交易日: {actual_trade_date}", flush=True)
        else:
            actual_trade_date = get_tw_today().strftime("%Y-%m-%d")
            print(f"[DEBUG_HISTOCK] 未能透過正規表達式提取標題日期，預設台灣日期: {actual_trade_date}", flush=True)

        # 2. 原生表格解析與逐表列印
        dfs = pd.read_html(StringIO(resp.text))
        print(f"[DEBUG_HISTOCK] pd.read_html 共找到 {len(dfs)} 張表格", flush=True)
        records = []

        for idx, df in enumerate(dfs):
            # 展平多重欄位索引
            if isinstance(df.columns, pd.MultiIndex):
                flat_cols = ['_'.join(str(c) for c in col).strip() for col in df.columns]
                df.columns = flat_cols
            else:
                df.columns = [str(c).strip() for c in df.columns]

            cols_list = list(df.columns)
            info_entry = {
                "idx": idx,
                "shape": df.shape,
                "columns": cols_list,
                "head2": df.head(2).to_dict(orient="records")
            }
            debug_tables_info.append(info_entry)

            print(f"\n--- [DEBUG_HISTOCK] 表格 #{idx} 結構 ---", flush=True)
            print(f"Shape: {df.shape}", flush=True)
            print(f"Columns: {cols_list}", flush=True)
            print("樣本資料（前 2 列）：", flush=True)
            for r_i, r_data in df.head(2).iterrows():
                print(f"  列 {r_i}: {dict(r_data)}", flush=True)

            cols_str = " ".join(df.columns)
            matched_branches = [s for s in HISTOCK_BRANCH_COLS.keys() if s in cols_str]
            has_total = any("合計" in c for c in df.columns)

            if len(matched_branches) < 1 and not has_total:
                print(f"--> 表格 #{idx} 無官股特徵，跳過。", flush=True)
                continue

            stock_col = None
            total_col = None
            branch_cols = {}

            for col in df.columns:
                if any(k in col for k in ["代號", "名稱", "股票", "標的"]) and stock_col is None:
                    stock_col = col
                if "合計" in col and total_col is None:
                    total_col = col
                for s_b, f_b in HISTOCK_BRANCH_COLS.items():
                    if s_b in col and s_b not in branch_cols:
                        branch_cols[s_b] = col

            if stock_col is None and len(df.columns) >= 2:
                stock_col = df.columns[1]
            if total_col is None and len(df.columns) >= 1:
                total_col = df.columns[-1]

            print(f"--> 表格 #{idx} 鎖定欄位: 股票={stock_col}, 合計={total_col}, 分點數={len(branch_cols)}", flush=True)

            for _, row in df.iterrows():
                raw_stock = str(row.get(stock_col, "")).strip()
                if not raw_stock or raw_stock.lower() in ["nan", "none"]:
                    continue

                code_match = re.search(r"(\d{4,6}[A-Za-z]?)", raw_stock)
                if code_match:
                    stock_code = code_match.group(1)
                    stock_name = raw_stock.replace(stock_code, "").strip()
                else:
                    stock_code = raw_stock
                    stock_name = raw_stock

                tot_amt = _clean_num(row.get(total_col, 0)) if total_col else 0.0
                tot_vol = int(tot_amt / 10.0) if tot_amt != 0 else 0

                records.append({
                    "交易日期": actual_trade_date,
                    "官股分點": "全部官股合計",
                    "代號": stock_code,
                    "名稱": stock_name,
                    "買進張數": tot_vol if tot_vol > 0 else 0,
                    "賣出張數": abs(tot_vol) if tot_vol < 0 else 0,
                    "買賣超張數": tot_vol,
                    "金額(萬元)": round(tot_amt, 2)
                })

                for s_b, col_name in branch_cols.items():
                    b_full = HISTOCK_BRANCH_COLS[s_b]
                    b_amt = _clean_num(row.get(col_name, 0))
                    b_vol = int(b_amt / 10.0) if b_amt != 0 else 0
                    if b_amt != 0:
                        records.append({
                            "交易日期": actual_trade_date,
                            "官股分點": b_full,
                            "代號": stock_code,
                            "名稱": stock_name,
                            "買進張數": b_vol if b_vol > 0 else 0,
                            "賣出張數": abs(b_vol) if b_vol < 0 else 0,
                            "買賣超張數": b_vol,
                            "金額(萬元)": round(b_amt, 2)
                        })

        print(f"\n[DEBUG_HISTOCK] 總計解析記錄數: {len(records)}", flush=True)
        print("=" * 60 + "\n", flush=True)

        if records:
            res_df = pd.DataFrame(records).drop_duplicates(subset=["交易日期", "官股分點", "代號"], keep="last")
            return res_df, actual_trade_date, f"成功解析 {len(res_df)} 筆真實數據", debug_tables_info

        return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS), actual_trade_date, "未抓到有效數據列（請檢視下方診斷資訊）", debug_tables_info

    except Exception as e:
        print(f"[DEBUG_HISTOCK] 解析拋出例外: {e}", flush=True)
        traceback.print_exc()
        print("=" * 60 + "\n", flush=True)
        return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS), "", f"解析例外: {str(e)}", debug_tables_info

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
        print(f"[data_loader] 歷史官股落地同步失敗: {e}", flush=True)
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
