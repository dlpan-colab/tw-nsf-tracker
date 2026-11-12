"""
模組名稱：app.py（獨立探測測試版 - 僅供驗證 HiStock 資料端點與結構，不寫入資料庫）
版本識別：20261112_1517_TEST
修改目的：
1. 獨立執行 HiStock (https://histock.tw/stock/broker8.aspx) 原始碼深度探測，不執行任何資料庫讀寫與雲端同步。
2. 直接於前台手機介面分段列印所有包含 ajax、post、json、broker 或個股陣列之完整 <script> 原文。
3. 列出所有包含資料之 table、tr、hidden input 及外部引用的自訂 .js 檔名，精準鎖定真實資料接口。
防呆防錯原因：
1. 完全隔離主系統模組，避免測試過程污染本地或雲端 CSV 資料庫。
2. 採用可折疊區塊（st.expander）呈現大量原始碼，確保手機瀏覽器不卡頓且方便複製查閱。
"""

import re
import datetime
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
import streamlit as st

TW_TZ = ZoneInfo("Asia/Taipei")
TEST_VERSION = "20261112_1517_TEST"

st.set_page_config(page_title="HiStock 資料端點探測器", layout="wide")
st.caption(f"獨立探測版本（台灣時間）：{TEST_VERSION}")
st.subheader("🔍 HiStock 八大官股真實資料源探測（手機驗證模式）")

target_url = st.text_input("目標網址", value="https://histock.tw/stock/broker8.aspx")

REQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://histock.tw/"
}

if st.button("🚀 執行深度探測（不寫入資料庫）", type="primary", use_container_width=True):
    with st.spinner("正在連線並剖析 HiStock 原始碼..."):
        try:
            resp = requests.get(target_url, headers=REQ_HEADERS, timeout=15)
            st.success(f"HTTP 狀態碼：{resp.status_code} ｜ 原始碼總長度：{len(resp.text):,} 字元")

            if resp.status_code != 200 or not resp.text:
                st.error("無法取得有效網頁內容，請檢查狀態碼。")
                st.stop()

            html_text = resp.text
            soup = BeautifulSoup(html_text, "html.parser")

            # 1. 標題與日期確認
            st.markdown("### 1. 頁面標題與交易日辨識")
            title_str = soup.title.string.strip() if soup.title and soup.title.string else "無標題"
            st.write(f"**網頁 Title：** `{title_str}`")
            date_matches = re.findall(r"(\d{2,4}[-/]\d{2}(?:[-/]\d{2})?\s*Top\s*30[^\n<]*)", soup.get_text())
            st.write(f"**頁面日期字樣匹配：** `{date_matches}`")

            # 2. 外部引入的 JS 檔案（過濾掉常見廣告/統計，保留 histock 自家腳本）
            st.markdown("### 2. 外部引用 JS 腳本清單")
            ext_scripts = []
            for s in soup.find_all("script", src=True):
                src = s["src"]
                if not any(ad in src.lower() for ad in ["google", "facebook", "doubleclick", "criteo", "analytics", "gtag"]):
                    ext_scripts.append(src)
            st.code("\n".join(ext_scripts) if ext_scripts else "無自訂外部 JS", language="text")

            # 3. 關鍵內嵌 <script> 完整原始碼檢視
            st.markdown("### 3. 關鍵內嵌 `<script>` 完整原始碼")
            keywords = ["ajax", "post", "getjson", "fetch", "broker", "top", "合庫", "土銀", "台銀", "ashx", "asmx", "api", "bind", "grid"]
            inline_scripts = [s for s in soup.find_all("script") if not s.get("src")]
            st.write(f"共找到 **{len(inline_scripts)}** 個內嵌 `<script>` 區塊，以下列出包含資料請求或官股關鍵字的完整原文：")

            matched_count = 0
            for idx, s in enumerate(inline_scripts):
                raw_js = (s.string or s.get_text() or "").strip()
                if not raw_js:
                    continue
                lower_js = raw_js.lower()
                hit_keys = [k for k in keywords if k in lower_js]
                if hit_keys:
                    matched_count += 1
                    with st.expander(f"內嵌 Script #{idx}（長度: {len(raw_js)} 字元 ｜ 命中關鍵字: {', '.join(hit_keys)}）", expanded=(matched_count <= 2)):
                        st.code(raw_js, language="javascript")

            if matched_count == 0:
                st.warning("未在內嵌 Script 中命中任何資料請求關鍵字。")

            # 4. 隱藏表單欄位（ASP.NET ViewState / Hidden Inputs）
            st.markdown("### 4. 頁面隱藏欄位（Hidden Inputs）")
            hidden_inputs = []
            for inp in soup.find_all("input", type="hidden"):
                name = inp.get("name") or inp.get("id") or "未命名"
                val = inp.get("value", "")
                # 排除過長的 ViewState 雜訊，但標示其長度
                if name in ["__VIEWSTATE", "__EVENTVALIDATION", "__VIEWSTATEGENERATOR"]:
                    hidden_inputs.append({"name": name, "value_preview": f"[系統狀態碼，長度 {len(val)} 字元]"})
                else:
                    hidden_inputs.append({"name": name, "value": val})
            st.json(hidden_inputs)

            # 5. 所有 Table 與非空 TR 檢查
            st.markdown("### 5. HTML `<table>` 與 `<tr>` 實體結構掃描")
            tables = soup.find_all("table")
            st.write(f"總計找到 **{len(tables)}** 個 `<table>` 標籤：")
            for t_idx, tbl in enumerate(tables):
                trs = tbl.find_all("tr")
                with st.expander(f"Table #{t_idx}（id={tbl.get('id')}, class={tbl.get('class')}, 總列數={len(trs)}）"):
                    for r_idx, tr in enumerate(trs[:5]):
                        cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
                        st.write(f"列 {r_idx}: `{cells}`")

            # 6. 全文搜尋疑似 AJAX 端點路徑（.ashx / .asmx / .aspx/方法）
            st.markdown("### 6. 全文正則萃取疑似後端端點（.ashx / .asmx / .aspx）")
            endpoints = sorted(set(re.findall(r"['\"]([^'\"\s]+?\.(?:ashx|asmx|aspx(?:/[a-zA-Z0-9_]+)?)[^'\"\s]*)['\"]", html_text, re.IGNORECASE)))
            st.code("\n".join(endpoints) if endpoints else "未匹配到明確後端端點路徑", language="text")

        except Exception as e:
            st.error(f"探測過程發生例外：{e}")
            st.exception(e)
