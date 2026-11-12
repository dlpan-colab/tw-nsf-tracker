"""
模組名稱：app.py（HiStock 外部 JS 腳本與 AJAX 端點逆向探測測試版 - 不寫入資料庫）
版本識別：20261112_1535_JS_PROBE
修改目的：
1. 針對 https://histock.tw/stock/broker8.aspx 頁面引用的所有自家外部 .js 檔案進行自動抓取與關鍵字檢索。
2. 搜尋包含 broker8、gvTB、ajax、post、ashx、asmx 等關鍵字的 JS 程式碼片段，精準定位前端動態載入 30 檔官股資料的真實 API 網址與參數。
3. 同步檢查 HTML 原始碼中距離 gvTB 表格前後 1,500 字元內的完整 DOM 與隱藏標籤結構（確認是否藏於非標準標籤內）。
防呆防錯原因：
1. 僅執行 HTTP GET 唯讀探測，絕不觸碰或寫入任何本地與雲端資料庫。
2. 排除第三方套件（如 jquery.min.js、SuperSlide 等），集中檢視 HiStock 自研業務邏輯 JS 檔案。
"""

import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import streamlit as st

TEST_VERSION = "20261112_1535_JS_PROBE"
TARGET_URL = "https://histock.tw/stock/broker8.aspx"

st.set_page_config(page_title="HiStock JS 端點逆向探測器", layout="wide")
st.caption(f"探測版本（台灣時間）：{TEST_VERSION}")
st.subheader("🕵️ HiStock 外部 JS 與真實 API 端點逆向探測（不寫入資料庫）")

REQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://histock.tw/"
}

# 排除常見第三方通用函式庫，聚焦 HiStock 自家業務腳本
IGNORE_JS_PATTERNS = [
    "jquery.min.js", "jquery-ui", "mmenu", "superslide", "flipsnap",
    "lazyload", "highcharts", "highstock", "bootstrap", "google",
    "facebook", "doubleclick", "criteo", "analytics", "gtag"
]

if st.button("🚀 執行 HiStock JS 與 DOM 結構深度逆向探測", type="primary", use_container_width=True):
    with st.spinner("正在解析主頁面並追蹤所有外部 JS 腳本..."):
        try:
            resp = requests.get(TARGET_URL, headers=REQ_HEADERS, timeout=15)
            st.success(f"主頁面 HTTP 狀態：{resp.status_code} ｜ 總長度：{len(resp.text):,} 字元")

            if resp.status_code != 200 or not resp.text:
                st.error("主頁面無法取得有效內容。")
                st.stop()

            html_text = resp.text
            soup = BeautifulSoup(html_text, "html.parser")

            # ---------------------------------------------------------
            # 1. 檢視 gvTB 表格前後的原始 HTML 結構（確認資料是否藏於 div/span/ul）
            # ---------------------------------------------------------
            st.markdown("### 1. `gvTB` 表格區塊前後原始 HTML 結構檢視")
            gv_matches = [m.start() for m in re.finditer(r"gvTB", html_text)]
            st.write(f"HTML 中共出現 **{len(gv_matches)}** 次 `gvTB`：")
            for idx, pos in enumerate(gv_matches):
                snippet = html_text[max(0, pos - 200): min(len(html_text), pos + 1500)]
                with st.expander(f"gvTB 區塊 #{idx + 1}（字元位置 {pos}）原始 HTML", expanded=(idx == 0)):
                    st.code(snippet, language="html")

            # ---------------------------------------------------------
            # 2. 列出並剖析所有 HiStock 自家外部 JS 檔案
            # ---------------------------------------------------------
            st.markdown("### 2. HiStock 自家外部 JS 腳本清單與 AJAX 關鍵字搜尋")
            all_js_urls = []
            for s in soup.find_all("script", src=True):
                full_url = urljoin(TARGET_URL, s["src"])
                if "histock.tw" in full_url.lower():
                    if not any(ign in full_url.lower() for ign in IGNORE_JS_PATTERNS):
                        if full_url not in all_js_urls:
                            all_js_urls.append(full_url)

            st.write(f"過濾第三方套件後，鎖定 **{len(all_js_urls)}** 支 HiStock 自家業務 JS 腳本：")
            for u in all_js_urls:
                st.text(u)

            search_keywords = ["broker8", "gvtb", "ajax", "post", "ashx", "asmx", "bind", "render", "handler"]

            for js_idx, js_url in enumerate(all_js_urls):
                try:
                    js_resp = requests.get(js_url, headers=REQ_HEADERS, timeout=10)
                    if js_resp.status_code == 200 and js_resp.text:
                        js_code = js_resp.text
                        hits = []
                        for kw in search_keywords:
                            for m in re.finditer(re.escape(kw), js_code, re.IGNORECASE):
                                start_p = max(0, m.start() - 120)
                                end_p = min(len(js_code), m.end() + 280)
                                hits.append((kw, js_code[start_p:end_p].strip()))

                        with st.expander(f"JS #{js_idx + 1}: `{js_url.split('/')[-1]}`（長度: {len(js_code):,} ｜ 命中: {len(hits)} 處）", expanded=(len(hits) > 0)):
                            if hits:
                                # 去除高度重疊的片段，最多顯示前 8 處最具代表性的程式碼
                                shown_snippets = []
                                for kw, snip in hits:
                                    if not any(snip[:80] in existing for existing in shown_snippets):
                                        shown_snippets.append(snip)
                                        st.markdown(f"**命中關鍵字：`{kw}`**")
                                        st.code(snip, language="javascript")
                                        if len(shown_snippets) >= 8:
                                            break
                            else:
                                st.info("此 JS 檔案未包含 AJAX 或表格渲染關鍵字。")
                except Exception as js_err:
                    st.warning(f"讀取 `{js_url}` 失敗：{js_err}")

            # ---------------------------------------------------------
            # 3. 檢查主頁面所有 Inline Script（不含第 1 支圖表腳本）
            # ---------------------------------------------------------
            st.markdown("### 3. 主頁面其餘內嵌 `<script>` 總覽")
            inline_scripts = [s for s in soup.find_all("script") if not s.get("src")]
            for i_idx, s in enumerate(inline_scripts):
                txt = (s.string or s.get_text() or "").strip()
                if txt and "loadChart" not in txt:
                    with st.expander(f"Inline Script #{i_idx}（長度: {len(txt)} 字元）"):
                        st.code(txt[:2000], language="javascript")

        except Exception as e:
            st.error(f"探測發生例外：{e}")
            st.exception(e)
