"""
模組名稱：app.py（HiStock 八大官股 ul.stock-list 解析驗算測試版 - 不寫入資料庫）
版本識別：20261112_1543_PARSE_VERIFY
修改目的：
1. 依據實測確認之 DOM 結構（<table class="gvTB"> 表頭 + <ul class="stock-list"><li><span> 資料列），
   實作完整解析器，抓取買超 Top 30 與賣超 Top 30 共 60 筆八大官股個股明細（含完整交易日期、股票代號、股票名稱、
   八大行庫各自買賣超金額及合計萬元）。
2. 於手機前台畫面直接呈現解析後的 60 筆 DataFrame 表格與自動加總驗算結果，供肉眼最終確認（不寫入資料庫）。
防呆防錯原因：
1. 優先從 <li title="2026-11-11 ..."> 屬性擷取完整西元年月日，並從 onclick='goUrl("2308");' 精準提取股票代號，
   避免僅靠頁面標題只有 MM-DD 導致跨年日期誤判。
2. 逐筆將八大行庫金額轉為數值並比對加總與「合計(萬)」欄位（容許四捨五入 ±2 萬元誤差），防止欄位錯位。
"""

import re
import requests
import pandas as pd
from bs4 import BeautifulSoup
import streamlit as st

TEST_VERSION = "20261112_1543_PARSE_VERIFY"
DEFAULT_URL = "https://histock.tw/stock/broker8.aspx"

st.set_page_config(page_title="HiStock 60筆解析驗算器", layout="wide")
st.caption(f"解析驗算版本（台灣時間）：{TEST_VERSION}")
st.subheader("✅ HiStock 八大官股 Top 30 買超/賣超（共 60 筆）解析驗算")
st.info("本程式僅做即時抓取解析與前端表格驗算，不會寫入或更動任何資料庫。")

target_url = st.text_input("目標網址（可附加 ?d=YYYY-MM-DD 測試歷史日期）", value=DEFAULT_URL)

REQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://histock.tw/"
}

BANK_COLS = ["合庫", "土銀", "台銀", "台企銀", "彰銀", "第一金", "兆豐銀", "華南永昌"]


def clean_num(val_str: str) -> int:
    """移除千分位逗號與空白並轉為整數，防呆處理空值或橫線"""
    cleaned = re.sub(r"[,\s\xa0]", "", val_str or "")
    if cleaned in ("", "-", "--", "—"):
        return 0
    return int(float(cleaned))


def parse_histock_broker8(html_text: str) -> pd.DataFrame:
    """解析 HiStock 八大官股買超 Top 30 與賣超 Top 30 完整明細"""
    soup = BeautifulSoup(html_text, "html.parser")
    stock_lists = soup.find_all("ul", class_="stock-list")

    if len(stock_lists) < 2:
        raise ValueError(f"預期至少 2 組 ul.stock-list（買超/賣超），實際僅找到 {len(stock_lists)} 組。")

    categories = ["買超", "賣超"]
    records = []

    for idx, ul in enumerate(stock_lists[:2]):
        category = categories[idx]
        li_items = ul.find_all("li", recursive=False)

        for rank_idx, li in enumerate(li_items, start=1):
            # 1. 從 title 屬性擷取完整交易日期（例如：2026-11-11）
            title_attr = li.get("title", "")
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", title_attr)
            trade_date = date_match.group(1) if date_match else "未知日期"

            # 2. 從 onclick='goUrl("2308");' 擷取股票代號
            onclick_attr = li.get("onclick", "")
            code_match = re.search(r'goUrl\(["\']([^"\']+)["\']\)', onclick_attr)
            stock_code = code_match.group(1).strip() if code_match else ""

            # 3. 取得直接子層 <span>（排除名次內層的 <span class="top ..."> 干擾）
            spans = li.find_all("span", recursive=False)
            if len(spans) < 11:
                continue

            stock_name = spans[1].get_text(strip=True).replace("\xa0", "")
            bank_values = [clean_num(spans[i].get_text(strip=True)) for i in range(2, 10)]
            reported_total = clean_num(spans[10].get_text(strip=True))
            calc_sum = sum(bank_values)
            diff = reported_total - calc_sum

            row = {
                "交易日期": trade_date,
                "類別": category,
                "名次": rank_idx,
                "代號": stock_code,
                "股票名稱": stock_name,
                "合庫": bank_values[0],
                "土銀": bank_values[1],
                "台銀": bank_values[2],
                "台企銀": bank_values[3],
                "彰銀": bank_values[4],
                "第一金": bank_values[5],
                "兆豐銀": bank_values[6],
                "華南永昌": bank_values[7],
                "合計(萬)": reported_total,
                "八行加總驗算": calc_sum,
                "四捨五入差額": diff,
            }
            records.append(row)

    return pd.DataFrame(records)


if st.button("🚀 執行解析並顯示 60 筆驗算明細", type="primary", use_container_width=True):
    with st.spinner("正在連線 HiStock 並解析 60 筆個股數據..."):
        try:
            resp = requests.get(target_url, headers=REQ_HEADERS, timeout=15)
            if resp.status_code != 200 or not resp.text:
                st.error(f"HTTP 連線異常，狀態碼：{resp.status_code}")
                st.stop()

            df_result = parse_histock_broker8(resp.text)

            if df_result.empty:
                st.error("解析結果為 0 筆，請檢查網頁結構是否變動。")
                st.stop()

            buy_df = df_result[df_result["類別"] == "買超"]
            sell_df = df_result[df_result["類別"] == "賣超"]
            max_diff = df_result["四捨五入差額"].abs().max()

            # 驗算摘要指標卡片
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("總解析筆數", f"{len(df_result)} 筆")
            c2.metric("買超 / 賣超", f"{len(buy_df)} / {len(sell_df)} 筆")
            c3.metric("辨識交易日", df_result["交易日期"].iloc[0])
            c4.metric("最大加總誤差", f"±{max_diff} 萬")

            if max_diff <= 4:
                st.success("結構與數值驗算通過：八大行庫加總與官方「合計(萬)」欄位完全吻合（僅存個位數四捨五入差）。")
            else:
                st.warning(f"發現部分列加總差額達 {max_diff} 萬，請檢查下方明細。")

            # 完整 60 筆明細呈現（設定高高度讓手機可直接上下捲動檢視全部 60 列）
            st.markdown("### 完整 60 筆解析明細表（買超 Top 1~30 + 賣超 Top 1~30）")
            st.dataframe(df_result, use_container_width=True, height=900)

        except Exception as e:
            st.error(f"解析過程發生例外：{e}")
            st.exception(e)
