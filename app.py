"""
模組名稱：app.py（方向二：多資料源八大官股買賣超探測測試版 - 不寫入資料庫）
版本識別：20261112_1529_DIR2_TEST
修改目的：
1. 針對台股八大官股買賣超公開財經網站進行多源平行探測（不執行任何本地或雲端資料庫寫入）。
2. 測試對象涵蓋：
   - 來源 A：玩股網 WantGoo（八大官股買賣超排行與 JSON API 端點）
   - 來源 B：Stock-AI / 股狗網 / 公開券商分點統計頁面
   - 來源 C：Yahoo 奇摩股市（八大官股買賣超排行）
   - 來源 D：HiStock 帶日期參數與特定 User-Agent/Cookie 標頭測試（比對是否為參數缺失）
3. 直接於手機前台呈現各來源的 HTTP 狀態、表格欄位與前 5 筆真實解析數據，供肉眼核對正確性。
防呆防錯原因：
1. 各來源獨立 try-except 隔離，單一網站阻擋或逾時不影響其他來源測試結果。
2. 表格預覽限制顯示前 5 列，確保手機畫面清晰易讀。
"""

import re
import json
import datetime
from io import StringIO
from zoneinfo import ZoneInfo
import requests
import pandas as pd
from bs4 import BeautifulSoup
import streamlit as st

TW_TZ = ZoneInfo("Asia/Taipei")
TEST_VERSION = "20261112_1529_DIR2_TEST"

st.set_page_config(page_title="八大官股多資料源驗證器", layout="wide")
st.caption(f"方向二測試版本（台灣時間）：{TEST_VERSION}")
st.subheader("🧪 八大官股買賣超：多資料源與解析正確性驗證")
st.info("本程式僅執行即時連線與解析驗證，不會寫入或更動任何資料庫檔案。")

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; SM-S9380) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

DESKTOP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

def inspect_html_tables(html_text: str, source_name: str):
    """通用 HTML 表格與關鍵文字探測器"""
    soup = BeautifulSoup(html_text, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else "無標題"
    st.write(f"**網頁標題：** `{title}`")

    try:
        dfs = pd.read_html(StringIO(html_text))
        st.write(f"**`pd.read_html` 偵測表格數：** `{len(dfs)}` 張")
        valid_count = 0
        for idx, df in enumerate(dfs):
            if df.shape[0] >= 3 and df.shape[1] >= 4:
                valid_count += 1
                st.success(f"表格 #{idx} 具備有效資料列（形狀: {df.shape}）")
                st.dataframe(df.head(5), use_container_width=True)
        if valid_count == 0:
            st.warning("所有靜態 `<table>` 皆無有效個股資料列（列數 < 3）。")
    except ValueError:
        st.warning("頁面中無標準 HTML `<table>` 標籤。")
    except Exception as e:
        st.error(f"表格解析異常：{e}")

if st.button("🚀 開始平行驗證所有候選資料源", type="primary", use_container_width=True):

    # ---------------------------------------------------------
    # 來源 1：玩股網 WantGoo（八大官股買賣超排行頁面與內部 API）
    # ---------------------------------------------------------
    st.markdown("---")
    st.markdown("### 來源 1：玩股網 WantGoo（八大官股進出排行）")
    wantgoo_urls = [
        ("WantGoo 官股主頁", "https://www.wantgoo.com/stock/public-bank/buy-sell"),
        ("WantGoo 官股 JSON API 探測", "https://www.wantgoo.com/stock/public-bank/buy-sell-data"),
    ]
    for label, url in wantgoo_urls:
        with st.expander(f"測試：{label} (`{url}`)", expanded=True):
            try:
                headers = DESKTOP_HEADERS.copy()
                headers["Referer"] = "https://www.wantgoo.com/stock/public-bank/buy-sell"
                resp = requests.get(url, headers=headers, timeout=12)
                st.write(f"HTTP 狀態：**{resp.status_code}** ｜ 回傳長度：**{len(resp.text):,}** 字元")
                if resp.status_code == 200:
                    if "application/json" in resp.headers.get("Content-Type", "") or resp.text.strip().startswith(("{", "[")):
                        st.success("回傳為 JSON 格式！前 800 字元預覽：")
                        st.code(resp.text[:800], language="json")
                    else:
                        inspect_html_tables(resp.text, label)
                        # 檢查是否有內嵌 JSON
                        json_hits = re.findall(r"(?:var|const|let)\s+\w+\s*=\s*(\[\{.*?\}\]);", resp.text)
                        if json_hits:
                            st.info(f"發現內嵌 JSON 陣列（共 {len(json_hits)} 組），第一組預覽：")
                            st.code(json_hits[0][:500], language="json")
            except Exception as e:
                st.error(f"連線失敗：{e}")

    # ---------------------------------------------------------
    # 來源 2：Yahoo 奇摩股市（八大官股買賣超排行）
    # ---------------------------------------------------------
    st.markdown("---")
    st.markdown("### 來源 2：Yahoo 奇摩股市（八大官股買賣超）")
    yahoo_urls = [
        ("Yahoo 股市官股買超", "https://tw.stock.yahoo.com/rank/government-bank-buy"),
        ("Yahoo 股市官股賣超", "https://tw.stock.yahoo.com/rank/government-bank-sell"),
    ]
    for label, url in yahoo_urls:
        with st.expander(f"測試：{label} (`{url}`)", expanded=True):
            try:
                resp = requests.get(url, headers=DESKTOP_HEADERS, timeout=12)
                st.write(f"HTTP 狀態：**{resp.status_code}** ｜ 回傳長度：**{len(resp.text):,}** 字元")
                if resp.status_code == 200:
                    inspect_html_tables(resp.text, label)
                    # Yahoo 股市常使用 Next.js / App.main JSON 內嵌數據
                    soup = BeautifulSoup(resp.text, "html.parser")
                    rows = soup.select("li.List\\(n\\)")
                    if rows:
                        st.info(f"偵測到列表式排版（`li.List(n)`）共 {len(rows)} 列，前 3 列純文字預覽：")
                        for r in rows[:3]:
                            st.text(" | ".join(r.stripped_strings))
            except Exception as e:
                st.error(f"連線失敗：{e}")

    # ---------------------------------------------------------
    # 來源 3：鉅亨網 Anue / 財經 M 平方 / 股狗網公開排行
    # ---------------------------------------------------------
    st.markdown("---")
    st.markdown("### 來源 3：鉅亨網 / 公開財經站點（八大官股買賣超）")
    other_urls = [
        ("鉅亨網台股官股進出", "https://www.cnyes.com/twstock/a_official.aspx"),
        ("StockQ / 富聯網八大官股", "https://www.money-link.com.tw/RealtimeNews/index.aspx"),
    ]
    for label, url in other_urls:
        with st.expander(f"測試：{label} (`{url}`)", expanded=True):
            try:
                resp = requests.get(url, headers=DESKTOP_HEADERS, timeout=12)
                resp.encoding = resp.apparent_encoding
                st.write(f"HTTP 狀態：**{resp.status_code}** ｜ 回傳長度：**{len(resp.text):,}** 字元")
                if resp.status_code == 200:
                    inspect_html_tables(resp.text, label)
            except Exception as e:
                st.error(f"連線失敗：{e}")

    # ---------------------------------------------------------
    # 來源 4：HiStock 帶明確日期參數與 Desktop Cookie 驗證
    # ---------------------------------------------------------
    st.markdown("---")
    st.markdown("### 來源 4：HiStock 帶日期參數（`?d=2026-11-11`）驗證")
    with st.expander("測試：HiStock 指定交易日 URL", expanded=True):
        try:
            test_histock_url = "https://histock.tw/stock/broker8.aspx?d=2026-11-11"
            resp = requests.get(test_histock_url, headers=DESKTOP_HEADERS, timeout=12)
            st.write(f"HTTP 狀態：**{resp.status_code}** ｜ 回傳長度：**{len(resp.text):,}** 字元")
            if resp.status_code == 200:
                inspect_html_tables(resp.text, "HiStock 指定日期")
        except Exception as e:
            st.error(f"連線失敗：{e}")
