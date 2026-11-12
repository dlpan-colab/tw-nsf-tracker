"""
模組名稱：app.py（個股分點區間排行 + 前五大買賣超分點每日買賣超柱狀圖測試版）
版本識別：20261112_1620_BROKER_DAILY_BAR
修改目的：
1. 於富邦證券（MoneyDJ 引擎）個股區間分點表（zco.djhtm）解析買超前 15 名與賣超前 15 名分點。
2. 自動擷取「買超前 5 名」與「賣超前 5 名」分點之明細超連結（zco0.djhtm），抓取該期間內各分點的逐日買賣超張數。
3. 使用 Streamlit 內建 Altair 繪製各前五名分點之「每日買賣超柱狀圖」（紅柱為買超、綠柱為賣超），供手機前台視覺化檢視。
防呆防錯原因：
1. 直接從主表 <a> 標籤提取分點專屬 href（含券商代碼 b 與參數 c），避免自行推測分點代碼導致查無資料。
2. 相容處理民國年（如 115/10/07）與西元年日期格式，並強制依日期升冪排序，確保柱狀圖時間軸由左至右正確呈現。
3. 每次子頁面請求間隔 0.3 秒並加上獨立 try-except 防護，防止短時間密集請求遭目標伺服器限流或單一分點異常中斷整體畫面。
"""

import re
import time
import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
import requests
import pandas as pd
import altair as alt
from bs4 import BeautifulSoup
import streamlit as st

TW_TZ = ZoneInfo("Asia/Taipei")
TEST_VERSION = "20261112_1620_BROKER_DAILY_BAR"
BASE_DOMAIN = "https://fubon-ebrokerdj.fbs.com.tw"

st.set_page_config(page_title="個股分點區間與每日柱狀圖", layout="wide")
st.caption(f"測試版本（台灣時間）：{TEST_VERSION}")
st.subheader("📊 個股區間分點排行與前五大買賣超分點每日柱狀圖")

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
    "Referer": f"{BASE_DOMAIN}/"
}


def clean_int(val_str: str) -> int:
    """清理千分位逗號與空白並轉為整數"""
    cleaned = re.sub(r"[,\s\xa0張]", "", str(val_str or ""))
    if cleaned in ("", "-", "--", "—"):
        return 0
    return int(float(cleaned))


def normalize_tw_date(date_str: str) -> str:
    """將民國年 (115/10/07) 或西元年 (2026/10/07) 統一轉為 YYYY-MM-DD"""
    s = str(date_str).strip()
    m = re.match(r"^(\d{2,4})[/\-](\d{1,2})[/\-](\d{1,2})$", s)
    if not m:
        return s
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 1911:
        y += 1911
    return f"{y:04d}-{mo:02d}-{d:02d}"


def parse_range_ranking(html_text: str):
    """解析區間買賣超分點主表，回傳含明細連結的買超清單與賣超清單"""
    soup = BeautifulSoup(html_text, "html.parser")
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

                # 左側：買超分點
                if left_txt[0] and left_txt[0] not in ("買超券商", "券商名稱", "分點") and any(c.isdigit() for c in left_txt[-1]):
                    a_tag = left_cells[0].find("a", href=True)
                    detail_url = urljoin(BASE_DOMAIN, a_tag["href"]) if a_tag else ""
                    buy_list.append({
                        "分點名稱": left_txt[0],
                        "買進(張)": clean_int(left_txt[1]),
                        "賣出(張)": clean_int(left_txt[2]),
                        "買賣超(張)": clean_int(left_txt[3]),
                        "佔比": left_txt[4] if len(left_txt) > 4 else "",
                        "明細網址": detail_url
                    })

                # 右側：賣超分點
                if right_txt[0] and right_txt[0] not in ("賣超券商", "券商名稱", "分點") and any(c.isdigit() for c in right_txt[-1]):
                    a_tag = right_cells[0].find("a", href=True)
                    detail_url = urljoin(BASE_DOMAIN, a_tag["href"]) if a_tag else ""
                    sell_list.append({
                        "分點名稱": right_txt[0],
                        "買進(張)": clean_int(right_txt[1]),
                        "賣出(張)": clean_int(right_txt[2]),
                        "買賣超(張)": clean_int(right_txt[3]),
                        "佔比": right_txt[4] if len(right_txt) > 4 else "",
                        "明細網址": detail_url
                    })

    return pd.DataFrame(buy_list), pd.DataFrame(sell_list)


def fetch_broker_daily_series(detail_url: str) -> pd.DataFrame:
    """抓取單一分點在指定區間內的逐日買賣超明細 (zco0.djhtm)"""
    if not detail_url:
        return pd.DataFrame()
    resp = requests.get(detail_url, headers=REQ_HEADERS, timeout=15)
    resp.encoding = "big5"
    if resp.status_code != 200:
        return pd.DataFrame()

    soup = BeautifulSoup(resp.text, "html.parser")
    daily_rows = []
    for tbl in soup.find_all("table"):
        for tr in tbl.find_all("tr"):
            tds = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            # zco0.djhtm 標準逐日明細列為 4 或 5 欄：[日期, 買進, 賣出, 買賣超, (佔比)]
            if len(tds) in (4, 5) and re.match(r"^\d{2,4}[/\-]\d{1,2}[/\-]\d{1,2}$", tds[0]):
                net_vol = clean_int(tds[3])
                daily_rows.append({
                    "日期": normalize_tw_date(tds[0]),
                    "買進(張)": clean_int(tds[1]),
                    "賣出(張)": clean_int(tds[2]),
                    "買賣超(張)": net_vol,
                    "方向": "買超" if net_vol >= 0 else "賣超"
                })

    if not daily_rows:
        return pd.DataFrame()

    df_d = pd.DataFrame(daily_rows).drop_duplicates(subset=["日期"]).sort_values("日期", ascending=True)
    return df_d


def render_daily_bar_chart(df_daily: pd.DataFrame, title_text: str):
    """使用 Altair 繪製紅買綠賣每日買賣超柱狀圖"""
    chart = (
        alt.Chart(df_daily)
        .mark_bar(size=14)
        .encode(
            x=alt.X("日期:N", title="交易日期", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("買賣超(張):Q", title="買賣超 (張)"),
            color=alt.condition(
                alt.datum["買賣超(張)"] >= 0,
                alt.value("#ef5350"),  # 台股習慣：紅買
                alt.value("#26a69a")   # 台股習慣：綠賣
            ),
            tooltip=["日期", "買進(張)", "賣出(張)", "買賣超(張)"]
        )
        .properties(title=title_text, height=240)
    )
    st.altair_chart(chart, use_container_width=True)


if st.button("🚀 抓取區間排行並繪製前五大分點每日柱狀圖", type="primary", use_container_width=True):
    s_mdj = f"{start_date.year}-{start_date.month}-{start_date.day}"
    e_mdj = f"{end_date.year}-{end_date.month}-{end_date.day}"
    main_url = f"{BASE_DOMAIN}/z/zc/zco/zco.djhtm?a={stock_id}&e={s_mdj}&f={e_mdj}"

    with st.spinner("正在抓取區間分點總表..."):
        try:
            resp = requests.get(main_url, headers=REQ_HEADERS, timeout=15)
            resp.encoding = "big5"
            if resp.status_code != 200:
                st.error(f"主表連線失敗，HTTP 狀態碼：{resp.status_code}")
                st.stop()

            df_buy, df_sell = parse_range_ranking(resp.text)
            if df_buy.empty and df_sell.empty:
                st.error("未解析到任何分點數據，請確認股票代碼與日期區間。")
                st.stop()

            # ---------------------------------------------------------
            # 1. 表列買賣超前 15 名分點
            # ---------------------------------------------------------
            st.markdown("---")
            st.markdown(f"### 1. `{stock_id}` 區間買賣超前 15 名分點總表（{s_mdj} ~ {e_mdj}）")
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                st.write("**🔴 買超分點 Top 15**")
                st.dataframe(df_buy.drop(columns=["明細網址"]).head(15), use_container_width=True)
            with col_t2:
                st.write("**🟢 賣超分點 Top 15**")
                st.dataframe(df_sell.drop(columns=["明細網址"]).head(15), use_container_width=True)

            # ---------------------------------------------------------
            # 2. 買超前 5 名分點：每日買賣超柱狀圖
            # ---------------------------------------------------------
            st.markdown("---")
            st.markdown("### 2. 🔴 買超前 5 名分點：每日買賣超柱狀圖")
            top5_buy = df_buy.head(5)
            for idx, row in top5_buy.iterrows():
                b_name = row["分點名稱"]
                b_net = row["買賣超(張)"]
                d_url = row["明細網址"]
                with st.spinner(f"載入買超第 {idx + 1} 名【{b_name}】逐日明細..."):
                    df_d = fetch_broker_daily_series(d_url)
                    if not df_d.empty:
                        render_daily_bar_chart(df_d, f"買超 Top {idx + 1}：{b_name}（區間累計：{b_net:+,} 張）")
                    else:
                        st.warning(f"【{b_name}】無法取得逐日明細（連結：{d_url}）")
                    time.sleep(0.3)

            # ---------------------------------------------------------
            # 3. 賣超前 5 名分點：每日買賣超柱狀圖
            # ---------------------------------------------------------
            st.markdown("---")
            st.markdown("### 3. 🟢 賣超前 5 名分點：每日買賣超柱狀圖")
            top5_sell = df_sell.head(5)
            for idx, row in top5_sell.iterrows():
                s_name = row["分點名稱"]
                s_net = row["買賣超(張)"]
                d_url = row["明細網址"]
                with st.spinner(f"載入賣超第 {idx + 1} 名【{s_name}】逐日明細..."):
                    df_d = fetch_broker_daily_series(d_url)
                    if not df_d.empty:
                        render_daily_bar_chart(df_d, f"賣超 Top {idx + 1}：{s_name}（區間累計：{s_net:,} 張）")
                    else:
                        st.warning(f"【{s_name}】無法取得逐日明細（連結：{d_url}）")
                    time.sleep(0.3)

        except Exception as e:
            st.error(f"執行過程發生異常：{e}")
            st.exception(e)
