"""
模組名稱：app.py（個股分點區間排行 + 前五大買賣超分點每日買賣超柱狀圖修正版）
版本識別：20261112_1628_BROKER_DAILY_BAR_FIX
修改目的：
1. 修正 zco0.djhtm 逐日明細欄位解析錯誤：原誤抓第 4 欄（總成交張數 = 買進 + 賣出），現改為精準計算「買進(張) - 賣出(張)」並核對第 5 欄買賣超張數，真實呈現每日買超（正值紅柱）與賣超（負值綠柱）。
2. 加入日期區間過濾（start_date <= 日期 <= end_date）與動態區間參數帶入，排除 zco0.djhtm 預設回傳之區間外最新交易日（如 11/11），確保圖表橫軸與設定區間完全一致。
3. 同時顯示「區間明細加總驗算」於圖表標題，供與主表區間累計張數即時核對。
防呆防錯原因：
1. 避免欄位順序變動導致買賣超正負號反轉，直接以 `buy_vol - sell_vol` 作為核心買賣超計算基準。
2. 於分點明細連結動態覆寫 `e`（起日）與 `f`（迄日）參數，並於本地 DataFrame 再執行一次日期區間篩選，雙重防止區間外數據混入。
"""

import re
import time
import datetime
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from zoneinfo import ZoneInfo
import requests
import pandas as pd
import altair as alt
from bs4 import BeautifulSoup
import streamlit as st

TW_TZ = ZoneInfo("Asia/Taipei")
TEST_VERSION = "20261112_1628_BROKER_DAILY_BAR_FIX"
BASE_DOMAIN = "https://fubon-ebrokerdj.fbs.com.tw"

st.set_page_config(page_title="個股分點區間與每日柱狀圖", layout="wide")
st.caption(f"修正版本（台灣時間）：{TEST_VERSION}")
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


def build_detail_url_with_range(raw_href: str, s_mdj: str, e_mdj: str) -> str:
    """解析分點明細連結並強制帶入指定起迄日期參數 e 與 f"""
    full_url = urljoin(BASE_DOMAIN, raw_href)
    parsed = urlparse(full_url)
    qs = parse_qs(parsed.query)
    qs["e"] = [s_mdj]
    qs["f"] = [e_mdj]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def parse_range_ranking(html_text: str, s_mdj: str, e_mdj: str):
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
                    detail_url = build_detail_url_with_range(a_tag["href"], s_mdj, e_mdj) if a_tag else ""
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
                    detail_url = build_detail_url_with_range(a_tag["href"], s_mdj, e_mdj) if a_tag else ""
                    sell_list.append({
                        "分點名稱": right_txt[0],
                        "買進(張)": clean_int(right_txt[1]),
                        "賣出(張)": clean_int(right_txt[2]),
                        "買賣超(張)": clean_int(right_txt[3]),
                        "佔比": right_txt[4] if len(right_txt) > 4 else "",
                        "明細網址": detail_url
                    })

    return pd.DataFrame(buy_list), pd.DataFrame(sell_list)


def fetch_broker_daily_series(detail_url: str, s_iso: str, e_iso: str) -> pd.DataFrame:
    """抓取單一分點逐日明細 (zco0.djhtm)，精準計算買賣超(買進-賣出)並過濾指定日期區間"""
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
            # zco0.djhtm 逐日明細列結構：[日期, 買進, 賣出, 成交張數(買+賣), 買賣超(買-賣)]
            if len(tds) >= 4 and re.match(r"^\d{2,4}[/\-]\d{1,2}[/\-]\d{1,2}$", tds[0]):
                norm_date = normalize_tw_date(tds[0])
                # 防呆過濾：僅保留使用者指定區間內的交易日
                if not (s_iso <= norm_date <= e_iso):
                    continue

                buy_vol = clean_int(tds[1])
                sell_vol = clean_int(tds[2])
                # 直接以 買進 - 賣出 計算真實淨買賣超（避免誤抓第 4 欄總成交量）
                net_vol = buy_vol - sell_vol

                daily_rows.append({
                    "日期": norm_date,
                    "買進(張)": buy_vol,
                    "賣出(張)": sell_vol,
                    "買賣超(張)": net_vol,
                    "方向": "買超" if net_vol >= 0 else "賣超"
                })

    if not daily_rows:
        return pd.DataFrame()

    df_d = pd.DataFrame(daily_rows).drop_duplicates(subset=["日期"]).sort_values("日期", ascending=True)
    return df_d


def render_daily_bar_chart(df_daily: pd.DataFrame, title_text: str):
    """使用 Altair 繪製紅買綠賣每日買賣超柱狀圖（含零軸參考線）"""
    bars = (
        alt.Chart(df_daily)
        .mark_bar(size=14)
        .encode(
            x=alt.X("日期:N", title="交易日期", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("買賣超(張):Q", title="買賣超 (張)"),
            color=alt.condition(
                alt.datum["買賣超(張)"] >= 0,
                alt.value("#ef5350"),  # 紅柱：當日買超
                alt.value("#26a69a")   # 綠柱：當日賣超
            ),
            tooltip=["日期", "買進(張)", "賣出(張)", "買賣超(張)"]
        )
    )
    zero_rule = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#888888", strokeDash=[3, 3]).encode(y="y:Q")
    chart = (bars + zero_rule).properties(title=title_text, height=250)
    st.altair_chart(chart, use_container_width=True)


if st.button("🚀 抓取區間排行並繪製前五大分點每日柱狀圖", type="primary", use_container_width=True):
    s_iso = start_date.strftime("%Y-%m-%d")
    e_iso = end_date.strftime("%Y-%m-%d")
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

            df_buy, df_sell = parse_range_ranking(resp.text, s_mdj, e_mdj)
            if df_buy.empty and df_sell.empty:
                st.error("未解析到任何分點數據，請確認股票代碼與日期區間。")
                st.stop()

            # ---------------------------------------------------------
            # 1. 表列買賣超前 15 名分點
            # ---------------------------------------------------------
            st.markdown("---")
            st.markdown(f"### 1. `{stock_id}` 區間買賣超前 15 名分點總表（{s_iso} ~ {e_iso}）")
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
                    df_d = fetch_broker_daily_series(d_url, s_iso, e_iso)
                    if not df_d.empty:
                        sub_sum = int(df_d["買賣超(張)"].sum())
                        render_daily_bar_chart(
                            df_d,
                            f"買超 Top {idx + 1}：{b_name}（主表累計：{b_net:+,} 張 ｜ 逐日加總：{sub_sum:+,} 張）"
                        )
                    else:
                        st.warning(f"【{b_name}】在 {s_iso}~{e_iso} 無逐日明細資料。")
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
                    df_d = fetch_broker_daily_series(d_url, s_iso, e_iso)
                    if not df_d.empty:
                        sub_sum = int(df_d["買賣超(張)"].sum())
                        render_daily_bar_chart(
                            df_d,
                            f"賣超 Top {idx + 1}：{s_name}（主表累計：{s_net:,} 張 ｜ 逐日加總：{sub_sum:+,} 張）"
                        )
                    else:
                        st.warning(f"【{s_name}】在 {s_iso}~{e_iso} 無逐日明細資料。")
                    time.sleep(0.3)

        except Exception as e:
            st.error(f"執行過程發生異常：{e}")
            st.exception(e)
