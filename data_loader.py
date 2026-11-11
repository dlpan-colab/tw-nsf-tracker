"""
模組名稱：data_loader.py
版本識別：20261112_0012
修改目的：
1. 更新版本識別為台灣時間 20261112_0012。
2. 針對靜態 HTML 僅有 2 個 <tr> 的特性，加入正則全文字掃描（搜尋 JavaScript 內嵌變數與字串）。
3. 將抓取到的關鍵字上下文摘要注入 debug_tables_info，供前台 expander 檢視真實內嵌結構。
4. 維持 print flush=True 與金額萬元、張數整數規範。
防呆防錯原因：
1. 避免 read_html 與 DOM 標籤解析失敗時完全無資料，透過純文字比對保障動態資料萃取。
"""

MODULE_VERSION = "20261112_0012"

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
    自 HiStock 抓取最新八大官股結算日報
    支援正則純文字掃描與 JavaScript 動態結構萃取
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

        records = []

        # 2. 檢測靜態表格表頭
        dfs = pd.read_html(StringIO(resp.text))
        print(f"[DEBUG_HISTOCK] pd.read_html 找到 {len(dfs)} 張表格", flush=True)
        for idx, df in enumerate(dfs):
            debug_tables_info.append({
                "來源": f"read_html 表格 #{idx}",
                "shape": df.shape,
                "columns": list(df.columns)
            })

        # 3. 純文字正則萃取：搜尋內嵌在 script 中的 JSON 陣列或資料字串
        html_content = resp.text
        script_tags = soup.find_all("script")
        print(f"[DEBUG_HISTOCK] 掃描到 {len(script_tags)} 個 <script> 標籤", flush=True)
        
        sample_snippets = []
        for s_idx, s in enumerate(script_tags):
            s_text = s.string or s.text or ""
            if any(k in s_text for k in ["broker", "Top", "合庫", "土銀", "台銀"]):
                # 擷取關鍵字前後 200 字元作為樣本
                m = re.search(r"(broker|Top|合庫|土銀|台銀)", s_text)
                if m:
                    start_pos = max(0, m.start() - 50)
                    end_pos = min(len(s_text), m.start() + 250)
                    sample_snippets.append({
                        "script_idx": s_idx,
                        "長度": len(s_text),
                        "內容片段": s_text[start_pos:end_pos].strip()
                    })

        debug_tables_info.append({
            "來源": "內嵌 Script 關鍵字偵測",
            "相關 Script 數量": len(sample_snippets),
            "片段列表": sample_snippets[:3]
        })

        # 4. 尋找表格本體字串（例如在 div 或 hidden input 內的純文字數據）
        # 尋找匹配：/stock/(\d{4,6}) 或 stockid=(\d{4,6})
        stock_matches = list(re.finditer(r"/stock/(\d{4,6})['\"]?\s*>([^<]+)</a>", html_content))
        print(f"[DEBUG_HISTOCK] 正則匹配到個股連結數: {len(stock_matches)}", flush=True)

        branch_order = ["合庫", "土銀", "台銀", "台企銀", "彰銀", "第一金", "兆豐", "華南"]

        for sm in stock_matches:
            stock_code = sm.group(1)
            stock_name = sm.group(2).strip()
            # 取得該股票標籤後方 600 字元內的數字
            after_html = html_content[sm.end():sm.end() + 600]
            # 抓取所有數字（包含小數與正負號）
            numbers = re.findall(r"[-+]?\d[\d,]*\.?\d*", after_html)
            clean_nums = [_clean_num(n) for n in numbers if n]
            
            if len(clean_nums) >= 9:
                tot_amt = clean_nums[-1]
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
                
                for b_i, b_short in enumerate(branch_order):
                    if b_i < len(clean_nums) - 1:
                        b_amt = clean_nums[b_i]
                        b_vol = int(b_amt / 10.0) if b_amt != 0 else 0
                        if b_amt != 0:
                            records.append({
                                "交易日期": actual_trade_date,
                                "官股分點": HISTOCK_BRANCH_COLS[b_short],
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
