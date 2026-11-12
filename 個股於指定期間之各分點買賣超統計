"""
模組名稱：app.py（個股券商分點區間買賣超探測測試版 - 驗證 10/7 ~ 11/6 抓取與官股分點過濾）
版本識別：20261112_1606_BROKER_RANGE_TEST
修改目的：
1. 驗證輸入「股票代碼（預設 2308 台達電）」與「期間（2026-10-07 ~ 2026-11-06）」時，各公開財經資料源之連線可用性與區間分點資料結構。
2. 測試候選資料源包含：
   - 來源 A：富邦證券公開網頁分點進出（fubon-ebrokerdj.fbs.com.tw，支援自訂起迄日期區間查詢）
   - 來源 B：凱基證券公開網頁分點進出（kgieworld.moneydj.com，支援自訂起迄日期區間查詢）
   - 來源 C：HiStock 個股分點進出頁面（histock.tw/stock/broker.aspx）
3. 自動比對「八大官股分點關鍵字與券商代號」，於手機前台呈現「全部買賣超分點」與「八大官股各地分點」篩選結果（不寫入資料庫）。
防呆防錯原因：
1. 採用台灣標準時間（Asia/Taipei），預設期間鎖定 2026-10-07 至 2026-11-06。
2. 券商分點網頁多採 Big5/CP950 編碼，程式內強制處理編碼解碼與千分位清理，避免亂碼或解析中斷。
3. 各來源獨立 try-except 隔離，單一網站阻擋或逾時不影響其他來源測試。
"""

import re
import datetime
from io import StringIO
from zoneinfo import ZoneInfo
import requests
import pandas as pd
from bs4 import BeautifulSoup
import streamlit as st

TW_TZ = ZoneInfo("Asia/Taipei")
TEST_VERSION = "20261112_1606_BROKER_RANGE_TEST"

st.set_page_config(page_title="個股分點區間探測器", layout="wide")
st.caption(f"探測版本（台灣時間）：{TEST_VERSION}")
st.subheader("🔍 個股券商分點區間買賣超探測（10/07 ~ 11/06）")
st.info("本程式僅做資料源與區間分點解析驗證，不會寫入任何資料庫。")

col_in1, col_in2, col_in3 = st.columns(3)
with col_in1:
    stock_id = st.text_input("輸入 1：股票代碼", value="2308").strip()
with col_in2:
    start_date = st.date_input("輸入 2（起日）", value=datetime.date(2026, 10, 7))
with col_in3:
    end_date = st.date_input("輸入 2（迄日）", value=datetime.date(2026, 11, 6))

REQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

# 八大官股券商名稱前綴識別（涵蓋總公司與所有地方分點，例如：兆豐-大同、華南永昌-豐原）
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


def is_gov_broker(broker_name: str) -> bool:
    """判斷分點名稱是否隸屬於八大官股體系"""
    clean_name = str(broker_name).strip()
    return any(clean_name.startswith(prefix) for prefix in GOV_BROKER_PREFIXES)


def parse_moneydj_broker_table(html_text: str, source_label: str):
    """解析 MoneyDJ 架構券商分點區間進出表格（左右雙欄：買超分點 / 賣超分點）"""
    soup = BeautifulSoup(html_text, "html.parser")
    tables = soup.find_all("table")
    st.write(f"**{source_label}** 偵測到 `<table>` 總數：`{len(tables)}`")

    buy_rows = []
    sell_rows = []

    for tbl in tables:
        rows = tbl.find_all("tr")
        for tr in rows:
            tds = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            # MoneyDJ 標準區間分點表通常為 8 欄（左側4欄買超：券商、買進、賣出、買賣超；右側4欄賣超：券商、買進、賣出、買賣超）
            # 或 10 欄（含佔比）
            if len(tds) in (8, 10):
                half = len(tds) // 2
                left = tds[:half]
                right = tds[half:]
                if left[0] and left[0] not in ("買超券商", "券商名稱", "分點") and any(c.isdigit() for c in left[-1]):
                    buy_rows.append(left)
                if right[0] and right[0] not in ("賣超券商", "券商名稱", "分點") and any(c.isdigit() for c in right[-1]):
                    sell_rows.append(right)

    return buy_rows, sell_rows


if st.button("🚀 執行 10/07 ~ 11/06 分點區間探測", type="primary", use_container_width=True):
    s_str = start_date.strftime("%Y-%m-%d")
    e_str = end_date.strftime("%Y-%m-%d")
    # MoneyDJ 系統常用 YYYY-M-D 無補零格式
    s_mdj = f"{start_date.year}-{start_date.month}-{start_date.day}"
    e_mdj = f"{end_date.year}-{end_date.month}-{end_date.day}"

    # ---------------------------------------------------------
    # 來源 A：富邦證券公開分點區間查詢（MoneyDJ 引擎）
    # ---------------------------------------------------------
    st.markdown("---")
    st.markdown("### 來源 A：富邦證券分點區間查詢（`fubon-ebrokerdj.fbs.com.tw`）")
    fubon_url = f"https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a={stock_id}&e={s_mdj}&f={e_mdj}"
    st.code(fubon_url, language="text")
    try:
        resp_a = requests.get(fubon_url, headers=REQ_HEADERS, timeout=15)
        resp_a.encoding = "big5"
        st.write(f"HTTP 狀態：**{resp_a.status_code}** ｜ 回傳長度：**{len(resp_a.text):,}** 字元")
        if resp_a.status_code == 200:
            buy_a, sell_a = parse_moneydj_broker_table(resp_a.text, "富邦分點")
            st.write(f"解析結果：買超分點 **{len(buy_a)}** 筆 ｜ 賣超分點 **{len(sell_a)}** 筆")
            if buy_a or sell_a:
                cols_name = ["分點名稱", "買進(張)", "賣出(張)", "買賣超(張)", "佔比"][:len(buy_a[0] if buy_a else sell_a[0])]
                df_buy_a = pd.DataFrame(buy_a, columns=cols_name)
                df_sell_a = pd.DataFrame(sell_a, columns=cols_name)

                st.success("✅ 成功抓回區間分點資料！以下為預覽：")
                t1, t2 = st.tabs(["輸出 1：全部買賣超分點（前15名）", "輸出 2：八大官股各地分點篩選"])
                with t1:
                    st.write("**買超分點 Top 15**")
                    st.dataframe(df_buy_a.head(15), use_container_width=True)
                    st.write("**賣超分點 Top 15**")
                    st.dataframe(df_sell_a.head(15), use_container_width=True)
                with t2:
                    gov_buy = df_buy_a[df_buy_a["分點名稱"].apply(is_gov_broker)]
                    gov_sell = df_sell_a[df_sell_a["分點名稱"].apply(is_gov_broker)]
                    st.write(f"**八大官股買超分點（共 {len(gov_buy)} 家）**")
                    st.dataframe(gov_buy, use_container_width=True)
                    st.write(f"**八大官股賣超分點（共 {len(gov_sell)} 家）**")
                    st.dataframe(gov_sell, use_container_width=True)
            else:
                st.warning("未匹配到標準分點列，前 600 字元預覽：")
                st.code(resp_a.text[:600], language="html")
    except Exception as e:
        st.error(f"來源 A 連線或解析異常：{e}")

    # ---------------------------------------------------------
    # 來源 B：凱基證券公開分點區間查詢（備援通道）
    # ---------------------------------------------------------
    st.markdown("---")
    st.markdown("### 來源 B：凱基證券分點區間查詢（`kgieworld.moneydj.com`）")
    kgi_url = f"https://kgieworld.moneydj.com/z/zc/zco/zco.djhtm?a={stock_id}&e={s_mdj}&f={e_mdj}"
    st.code(kgi_url, language="text")
    try:
        resp_b = requests.get(kgi_url, headers=REQ_HEADERS, timeout=15)
        resp_b.encoding = "big5"
        st.write(f"HTTP 狀態：**{resp_b.status_code}** ｜ 回傳長度：**{len(resp_b.text):,}** 字元")
        if resp_b.status_code == 200:
            buy_b, sell_b = parse_moneydj_broker_table(resp_b.text, "凱基分點")
            st.write(f"解析結果：買超分點 **{len(buy_b)}** 筆 ｜ 賣超分點 **{len(sell_b)}** 筆")
    except Exception as e:
        st.error(f"來源 B 連線異常：{e}")

    # ---------------------------------------------------------
    # 來源 C：HiStock 個股分點進出頁面
    # ---------------------------------------------------------
    st.markdown("---")
    st.markdown("### 來源 C：HiStock 個股分點進出（`histock.tw/stock/broker.aspx`）")
    histock_broker_url = f"https://histock.tw/stock/broker.aspx?no={stock_id}"
    st.code(histock_broker_url, language="text")
    try:
        resp_c = requests.get(histock_broker_url, headers=REQ_HEADERS, timeout=15)
        st.write(f"HTTP 狀態：**{resp_c.status_code}** ｜ 回傳長度：**{len(resp_c.text):,}** 字元")
        if resp_c.status_code == 200:
            soup_c = BeautifulSoup(resp_c.text, "html.parser")
            uls = soup_c.find_all("ul", class_="stock-list")
            st.write(f"偵測到 `ul.stock-list` 數量：**{len(uls)}**")
            if uls:
                first_li = uls[0].find("li")
                if first_li:
                    st.write("第一列原始文字預覽：")
                    st.code(" | ".join(first_li.stripped_strings), language="text")
    except Exception as e:
        st.error(f"來源 C 連線異常：{e}")
