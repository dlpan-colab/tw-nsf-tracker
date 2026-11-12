"""
模組名稱：data_loader.py
版本識別：20261112_2252
修改目的：
1. 更新版本識別為台灣時間 20261112_2252。
2. 新增 get_missing_gov_trade_dates() 增量差集比對函式：比對指定期間台股實際交易日（valid_trade_dates）與資料庫已存檔日期，
   僅回傳尚缺漏的交易日清單，避免重複抓取已存在資料。
3. 新增 batch_sync_gov_records() 批次合併落地函式：支援多日增量補抓結果一次性去重合併寫入 CSV 並同步至 Google Drive，
   大幅降低雲端上傳次數與執行耗時。
防呆防錯原因：
1. 排除「今日尚未盤後結算（台灣時間 17:00 前）」之當日日期於缺漏補抓之外，避免對尚未出爐的當日盤後表做無效請求。
2. 保留 HiStock 真實金額（萬元）解析與 MoneyDJ 區間／逐日分點明細（買進-賣出）計算邏輯。
"""

MODULE_VERSION = "20261112_2252"

import os
import re
import json
import time
import datetime
import traceback
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from zoneinfo import ZoneInfo
import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
import streamlit as st
import cloud_sync

TW_TZ = ZoneInfo("Asia/Taipei")


def get_tw_now() -> datetime.datetime:
    """取得台灣時區當前完整時間"""
    return datetime.datetime.now(TW_TZ)


def get_tw_today() -> datetime.date:
    """取得台灣時區當前日期"""
    return get_tw_now().date()


CACHE_DIR = "cache_data"
os.makedirs(CACHE_DIR, exist_ok=True)
LOCAL_TAIEX_FILE = os.path.join(CACHE_DIR, "taiex_history.csv")
LOCAL_GOV_FILE = os.path.join(CACHE_DIR, "gov_trades_history.csv")

# HiStock 網頁欄位順序對應至標準官股分點名稱
HISTOCK_BRANCH_ORDER = [
    ("合庫", "合作金庫"),
    ("土銀", "台灣土地銀行"),
    ("台銀", "臺灣銀行"),
    ("台企銀", "臺灣中小企銀"),
    ("彰銀", "彰化銀行"),
    ("第一金", "第一金證券"),
    ("兆豐銀", "兆豐證券"),
    ("華南永昌", "華南永昌"),
]

GOV_BANKS = [label for _, label in HISTOCK_BRANCH_ORDER]

# 八大官股券商分點名稱前綴（用於過濾 MoneyDJ 全市場分點明細中的各地官股分點）
GOV_BROKER_PREFIXES = (
    "合庫", "合作金庫",
    "土銀", "土地銀行",
    "台銀", "臺銀", "台灣銀行", "臺灣銀行",
    "台企", "臺企", "台灣企銀", "臺灣企銀",
    "彰銀", "彰化銀行",
    "第一金",
    "兆豐",
    "華南永昌"
)

EMPTY_TRADE_COLUMNS = [
    "交易日期", "官股分點", "代號", "名稱",
    "買進張數", "賣出張數", "買賣超張數", "金額(萬元)"
]

REQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://histock.tw/"
}

MDJ_BASE_DOMAIN = "https://fubon-ebrokerdj.fbs.com.tw"
MDJ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": f"{MDJ_BASE_DOMAIN}/"
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
    """移除千分位逗號與空白並轉為浮點數"""
    if val is None or pd.isna(val):
        return 0.0
    clean = re.sub(r"[^\d\.\-\+]", "", str(val).replace(",", "").replace("\xa0", ""))
    if clean in ("", "-", "+", "--", "—"):
        return 0.0
    try:
        return float(clean)
    except Exception:
        return 0.0


def fetch_histock_latest_gov_trades(target_date: str = None) -> tuple[pd.DataFrame, str, str, list]:
    """
    自 HiStock 抓取八大官股結算日報（買超 Top 30 + 賣超 Top 30，單位：萬元）
    - target_date: 可選參數（格式 'YYYY-MM-DD'），若不傳則抓取 HiStock 最新一個交易日
    回傳: (DataFrame, 實際交易日期, 狀態說明, 結構診斷列表)
    """
    url = "https://histock.tw/stock/broker8.aspx"
    if target_date:
        url = f"{url}?d={target_date}"

    debug_tables_info = []

    try:
        resp = requests.get(url, headers=REQ_HEADERS, timeout=15)
        if resp.status_code != 200 or not resp.text:
            return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS), "", f"連線異常 HTTP {resp.status_code}", []

        soup = BeautifulSoup(resp.text, "html.parser")
        stock_lists = soup.find_all("ul", class_="stock-list")
        debug_tables_info.append({
            "來源": "HiStock ul.stock-list 結構檢測",
            "目標網址": url,
            "偵測區塊數": len(stock_lists)
        })

        if len(stock_lists) < 2:
            return (
                pd.DataFrame(columns=EMPTY_TRADE_COLUMNS),
                target_date or "",
                f"未偵測到買超/賣超清單區塊（找到 {len(stock_lists)} 組 ul.stock-list）",
                debug_tables_info
            )

        records = []
        detected_dates = set()

        for ul in stock_lists[:2]:
            li_items = ul.find_all("li", recursive=False)
            for li in li_items:
                title_attr = li.get("title", "")
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})", title_attr)
                row_date = date_match.group(1) if date_match else (target_date or get_tw_today().strftime("%Y-%m-%d"))
                detected_dates.add(row_date)

                onclick_attr = li.get("onclick", "")
                code_match = re.search(r'goUrl\(["\']([^"\']+)["\']\)', onclick_attr)
                stock_code = code_match.group(1).strip() if code_match else ""

                spans = li.find_all("span", recursive=False)
                if len(spans) < 11 or not stock_code:
                    continue

                stock_name = spans[1].get_text(strip=True).replace("\xa0", "")
                bank_amts = [_clean_num(spans[i].get_text(strip=True)) for i in range(2, 10)]
                tot_amt = _clean_num(spans[10].get_text(strip=True))

                records.append({
                    "交易日期": row_date,
                    "官股分點": "全部官股合計",
                    "代號": stock_code,
                    "名稱": stock_name,
                    "買進張數": 0,
                    "賣出張數": 0,
                    "買賣超張數": 0,
                    "金額(萬元)": round(tot_amt, 2)
                })

                for b_idx, (_, bank_std_name) in enumerate(HISTOCK_BRANCH_ORDER):
                    b_amt = bank_amts[b_idx]
                    if b_amt != 0:
                        records.append({
                            "交易日期": row_date,
                            "官股分點": bank_std_name,
                            "代號": stock_code,
                            "名稱": stock_name,
                            "買進張數": 0,
                            "賣出張數": 0,
                            "買賣超張數": 0,
                            "金額(萬元)": round(b_amt, 2)
                        })

        actual_trade_date = sorted(detected_dates)[-1] if detected_dates else (target_date or get_tw_today().strftime("%Y-%m-%d"))

        if records:
            res_df = pd.DataFrame(records).drop_duplicates(subset=["交易日期", "官股分點", "代號"], keep="last")
            debug_tables_info.append({
                "來源": "解析結果摘要",
                "實際交易日期": actual_trade_date,
                "總寫入列數": len(res_df),
                "涵蓋個股數": res_df["代號"].nunique()
            })
            return res_df, actual_trade_date, f"成功解析 {actual_trade_date} 共 {res_df['代號'].nunique()} 檔個股（{len(res_df)} 筆明細）", debug_tables_info

        return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS), actual_trade_date, "未抓到有效個股數據列", debug_tables_info

    except Exception as e:
        print(f"[DEBUG_HISTOCK] 解析拋出例外: {e}", flush=True)
        traceback.print_exc()
        return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS), "", f"解析例外: {str(e)}", debug_tables_info


def sync_df_to_storage(df: pd.DataFrame) -> bool:
    """持久化保存至本地 CSV 與 Google Drive"""
    if df.empty:
        return False
    return batch_sync_gov_records([df])


def batch_sync_gov_records(df_list: list[pd.DataFrame]) -> bool:
    """增量批次合併多日 DataFrame 並一次性寫入本地 CSV 與 Google Drive"""
    valid_dfs = [d for d in df_list if d is not None and not d.empty]
    if not valid_dfs:
        return False
    try:
        if not os.path.exists(LOCAL_GOV_FILE):
            cloud_sync.download_file_from_drive("gov_trades_history.csv", LOCAL_GOV_FILE)

        new_batch = pd.concat(valid_dfs, ignore_index=True)
        new_batch["代號"] = new_batch["代號"].astype(str)

        if os.path.exists(LOCAL_GOV_FILE):
            existing_df = pd.read_csv(LOCAL_GOV_FILE, dtype={"代號": str})
            if "買賣超金額(萬元)" in existing_df.columns and "金額(萬元)" not in existing_df.columns:
                existing_df = existing_df.rename(columns={"買賣超金額(萬元)": "金額(萬元)"})
            combined = pd.concat([existing_df, new_batch], ignore_index=True)
        else:
            combined = new_batch

        combined = combined.drop_duplicates(subset=["交易日期", "官股分點", "代號"], keep="last")
        combined = combined.sort_values(["交易日期", "代號", "官股分點"]).reset_index(drop=True)
        combined.to_csv(LOCAL_GOV_FILE, index=False)
        cloud_sync.upload_file_to_drive(LOCAL_GOV_FILE, "gov_trades_history.csv")
        clear_gov_cache()
        return True
    except Exception as e:
        print(f"[data_loader] 批次歷史官股落地同步失敗: {e}", flush=True)
        return False


def get_missing_gov_trade_dates(start_date: str, end_date: str, valid_trade_dates: list[str]) -> tuple[list[str], list[str]]:
    """
    增量差集比對：計算指定期間內的台股實際交易日（valid_trade_dates）中，
    哪些日期尚未存在於本機／雲端資料庫。
    回傳: (期間內全部應有交易日清單, 尚缺漏交易日清單)
    """
    if not os.path.exists(LOCAL_GOV_FILE):
        cloud_sync.download_file_from_drive("gov_trades_history.csv", LOCAL_GOV_FILE)

    existing_dates = set()
    if os.path.exists(LOCAL_GOV_FILE):
        try:
            cached_db = pd.read_csv(LOCAL_GOV_FILE, usecols=["交易日期"])
            existing_dates = set(cached_db["交易日期"].dropna().astype(str).unique())
        except Exception:
            existing_dates = set()

    now_tw = get_tw_now()
    today_str = now_tw.strftime("%Y-%m-%d")
    # 盤後 17:00 前不將「今日」納入強制缺漏補抓（HiStock 尚未結算）
    cutoff_date = today_str if now_tw.hour >= 17 else (now_tw.date() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    target_trade_days = sorted([
        d for d in set(valid_trade_dates)
        if start_date <= d <= end_date and d <= cutoff_date
    ])
    missing_days = [d for d in target_trade_days if d not in existing_dates]
    return target_trade_days, missing_days


def get_latest_available_gov_date() -> datetime.date:
    """取得資料庫中最新一筆官股交易日；若資料庫為空則回傳台灣今日日期"""
    if not os.path.exists(LOCAL_GOV_FILE):
        cloud_sync.download_file_from_drive("gov_trades_history.csv", LOCAL_GOV_FILE)
    if os.path.exists(LOCAL_GOV_FILE):
        try:
            cached_db = pd.read_csv(LOCAL_GOV_FILE)
            if not cached_db.empty and "交易日期" in cached_db.columns:
                max_d = str(cached_db["交易日期"].dropna().max())
                return datetime.datetime.strptime(max_d, "%Y-%m-%d").date()
        except Exception:
            pass
    return get_tw_today()


@st.cache_data(ttl=1800)
def fetch_gov_branch_trades(trade_date: str) -> pd.DataFrame:
    """純讀取模式：取得指定日期官股資料（自落地歷史庫中讀取）"""
    if not os.path.exists(LOCAL_GOV_FILE):
        cloud_sync.download_file_from_drive("gov_trades_history.csv", LOCAL_GOV_FILE)
    if os.path.exists(LOCAL_GOV_FILE):
        try:
            cached_db = pd.read_csv(LOCAL_GOV_FILE, dtype={"代號": str})
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
    """純讀取模式：自落地歷史庫彙總區間統計"""
    if not os.path.exists(LOCAL_GOV_FILE):
        cloud_sync.download_file_from_drive("gov_trades_history.csv", LOCAL_GOV_FILE)
    if os.path.exists(LOCAL_GOV_FILE):
        try:
            cached_db = pd.read_csv(LOCAL_GOV_FILE, dtype={"代號": str})
            if "買賣超金額(萬元)" in cached_db.columns and "金額(萬元)" not in cached_db.columns:
                cached_db = cached_db.rename(columns={"買賣超金額(萬元)": "金額(萬元)"})
            if not cached_db.empty and "交易日期" in cached_db.columns:
                mask = (cached_db["交易日期"] >= start_date) & (cached_db["交易日期"] <= end_date)
                return cached_db[mask]
        except Exception:
            pass
    return pd.DataFrame(columns=EMPTY_TRADE_COLUMNS)


# =====================================================================
# 個股區間券商分點進出與前五大分點逐日明細（MoneyDJ zco / zco0 引擎）
# =====================================================================

def is_gov_broker_branch(broker_name: str) -> bool:
    """判斷分點名稱是否隸屬於八大官股體系（涵蓋總公司與各地分公司）"""
    clean_name = str(broker_name).strip()
    return any(clean_name.startswith(prefix) for prefix in GOV_BROKER_PREFIXES)


def _normalize_tw_date(date_str: str) -> str:
    """將民國年 (115/10/07) 或西元年 (2026/10/07) 統一轉為 YYYY-MM-DD"""
    s = str(date_str).strip()
    m = re.match(r"^(\d{2,4})[/\-](\d{1,2})[/\-](\d{1,2})$", s)
    if not m:
        return s
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 1911:
        y += 1911
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _build_detail_url_with_range(raw_href: str, s_mdj: str, e_mdj: str) -> str:
    """解析分點明細連結並強制帶入指定起迄日期參數 e 與 f"""
    full_url = urljoin(MDJ_BASE_DOMAIN, raw_href)
    parsed = urlparse(full_url)
    qs = parse_qs(parsed.query)
    qs["e"] = [s_mdj]
    qs["f"] = [e_mdj]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


@st.cache_data(ttl=1800)
def fetch_stock_broker_range_ranking(stock_id: str, start_date: str, end_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    抓取單一股票在指定期間（start_date ~ end_date）的買超與賣超分點排行榜
    回傳: (df_buy, df_sell)，內含「是否官股分點」標記與明細網址
    """
    s_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    e_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    s_mdj = f"{s_dt.year}-{s_dt.month}-{s_dt.day}"
    e_mdj = f"{e_dt.year}-{e_dt.month}-{e_dt.day}"
    main_url = f"{MDJ_BASE_DOMAIN}/z/zc/zco/zco.djhtm?a={stock_id}&e={s_mdj}&f={e_mdj}"

    try:
        resp = requests.get(main_url, headers=MDJ_HEADERS, timeout=15)
        resp.encoding = "big5"
        if resp.status_code != 200:
            return pd.DataFrame(), pd.DataFrame()

        soup = BeautifulSoup(resp.text, "html.parser")
        buy_list = []
        sell_list = []

        for tbl in soup.find_all("table"):
            for tr in tbl.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                texts = [c.get_text(strip=True) for c in cells]
                if len(texts) in (8, 10):
                    half = len(texts) // 2
                    left_txt = texts[:half]
                    right_txt = texts[half:]
                    left_cells = cells[:half]
                    right_cells = cells[half:]

                    if left_txt[0] and left_txt[0] not in ("買超券商", "券商名稱", "分點") and any(c.isdigit() for c in left_txt[-1]):
                        a_tag = left_cells[0].find("a", href=True)
                        detail_url = _build_detail_url_with_range(a_tag["href"], s_mdj, e_mdj) if a_tag else ""
                        b_name = left_txt[0]
                        buy_list.append({
                            "分點名稱": b_name,
                            "體系": "八大官股" if is_gov_broker_branch(b_name) else "一般券商",
                            "買進(張)": int(_clean_num(left_txt[1])),
                            "賣出(張)": int(_clean_num(left_txt[2])),
                            "買賣超(張)": int(_clean_num(left_txt[3])),
                            "佔比": left_txt[4] if len(left_txt) > 4 else "",
                            "明細網址": detail_url
                        })

                    if right_txt[0] and right_txt[0] not in ("賣超券商", "券商名稱", "分點") and any(c.isdigit() for c in right_txt[-1]):
                        a_tag = right_cells[0].find("a", href=True)
                        detail_url = _build_detail_url_with_range(a_tag["href"], s_mdj, e_mdj) if a_tag else ""
                        s_name = right_txt[0]
                        sell_list.append({
                            "分點名稱": s_name,
                            "體系": "八大官股" if is_gov_broker_branch(s_name) else "一般券商",
                            "買進(張)": int(_clean_num(right_txt[1])),
                            "賣出(張)": int(_clean_num(right_txt[2])),
                            "買賣超(張)": int(_clean_num(right_txt[3])),
                            "佔比": right_txt[4] if len(right_txt) > 4 else "",
                            "明細網址": detail_url
                        })

        return pd.DataFrame(buy_list), pd.DataFrame(sell_list)
    except Exception as e:
        print(f"[data_loader] 抓取個股分點區間排行失敗 ({stock_id}): {e}", flush=True)
        return pd.DataFrame(), pd.DataFrame()


@st.cache_data(ttl=1800)
def fetch_single_broker_daily_series(detail_url: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    抓取單一分點在指定區間內的逐日買賣超明細 (zco0.djhtm)
    精準以 買進(張) - 賣出(張) 計算真實淨買賣超張數
    """
    if not detail_url:
        return pd.DataFrame()
    try:
        resp = requests.get(detail_url, headers=MDJ_HEADERS, timeout=15)
        resp.encoding = "big5"
        if resp.status_code != 200:
            return pd.DataFrame()

        soup = BeautifulSoup(resp.text, "html.parser")
        daily_rows = []
        for tbl in soup.find_all("table"):
            for tr in tbl.find_all("tr"):
                tds = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(tds) >= 4 and re.match(r"^\d{2,4}[/\-]\d{1,2}[/\-]\d{1,2}$", tds[0]):
                    norm_date = _normalize_tw_date(tds[0])
                    if not (start_date <= norm_date <= end_date):
                        continue
                    buy_vol = int(_clean_num(tds[1]))
                    sell_vol = int(_clean_num(tds[2]))
                    net_vol = buy_vol - sell_vol
                    daily_rows.append({
                        "日期": norm_date,
                        "買進(張)": buy_vol,
                        "賣出(張)": sell_vol,
                        "買賣超(張)": net_vol
                    })

        if not daily_rows:
            return pd.DataFrame()

        return pd.DataFrame(daily_rows).drop_duplicates(subset=["日期"]).sort_values("日期", ascending=True).reset_index(drop=True)
    except Exception as e:
        print(f"[data_loader] 抓取單一分點逐日明細失敗: {e}", flush=True)
        return pd.DataFrame()
