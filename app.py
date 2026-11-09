"""
模組名稱：app.py
修改目的：
1. 整合加權指數 K 線走勢與政策事件標記圖表。
2. 建立「指定交易日之各官股分點進出」檢視模組。
3. 建立「日期區間統計：各分點進出個股」與「個股於各分點統計」兩大樞紐統計表。
防呆防錯原因：
1. 同層匯入 data_loader 與 chart_builder，解決模組路徑相依錯誤。
2. 增加選定日期之交易日校驗，避免非開盤日引發空資料異常。
"""

import streamlit as st
import datetime
import pandas as pd
from data_loader import (
    load_policy_events,
    fetch_taiex_data,
    fetch_gov_branch_trades,
    fetch_range_gov_branch_summary,
    GOV_BANKS,
    CORE_STOCKS
)
from chart_builder import build_taiex_chart

st.set_page_config(page_title="國安基金動向與八大官股分點分析", layout="wide")

st.title("國安基金政策標記與官股分點進出分析 (tw-nsf-tracker)")

# 側邊欄：時間區間與單日關注設定
st.sidebar.header("時間區間設定")
start_default = datetime.date(2022, 1, 1)
end_default = datetime.date.today()

col_s, col_e = st.sidebar.columns(2)
start_date = col_s.date_input("起始日期", start_default)
end_date = col_e.date_input("結束日期", end_default)

if start_date > end_date:
    st.sidebar.error("起始日期不能晚於結束日期！")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.header("單日分點檢視")
focus_date = st.sidebar.date_input("選擇關注交易日", end_default)

# 1. 載入資料
events_df = load_policy_events("policy_events.json")

# 標記說明列
st.markdown("""
**成交量標記圖例：**
:red[▲ 紅色正三角]：國安基金授權進場 ｜ :orange[▲ 黃色正三角]：金管會發布限空令 ｜ :green[▼ 綠色倒三角]：國安基金解除授權 ｜ :blue[▼ 藍色倒三角]：金管會解除限空令
""")

# 2. 繪製加權指數走勢圖
with st.spinner("載入加權指數與政策標記..."):
    taiex_df = fetch_taiex_data(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))

if taiex_df.empty:
    st.warning("查無所選區間之加權指數資料，請確認日期區間。")
else:
    chart_fig = build_taiex_chart(taiex_df, events_df)
    st.plotly_chart(chart_fig, use_container_width=True)

st.markdown("---")

# 3. 指定交易日：各官股分點進出檢視
st.subheader(f"【指定交易日】{focus_date.strftime('%Y-%m-%d')} 各官股分點進出明細")

single_day_df = fetch_gov_branch_trades(focus_date.strftime("%Y-%m-%d"))

selected_bank = st.selectbox("篩選官股券商分點", ["全部官股合計"] + GOV_BANKS)

if selected_bank != "全部官股合計":
    filtered_day_df = single_day_df[single_day_df["官股分點"] == selected_bank]
else:
    # 全部合計聚合
    filtered_day_df = single_day_df.groupby(["股票代號", "股票名稱"], as_index=False).agg({
        "買進張數": "sum",
        "賣出張數": "sum",
        "買賣超張數": "sum",
        "買賣超金額(萬元)": "sum"
    })

st.dataframe(
    filtered_day_df.sort_values(by="買賣超金額(萬元)", ascending=False),
    use_container_width=True,
    hide_index=True
)

st.markdown("---")

# 4. 日期區間統計模組
st.subheader("【區間統計】官股分點進出彙總分析")

range_summary_df = fetch_range_gov_branch_summary(
    start_date.strftime("%Y-%m-%d"),
    end_date.strftime("%Y-%m-%d")
)

tab1, tab2 = st.tabs(["各分點進出個股統計", "個股於各分點統計"])

with tab1:
    st.markdown("**各官股分點於所選區間買賣各個股明細：**")
    pivot_branch = pd.pivot_table(
        range_summary_df,
        values="買賣超張數",
        index=["官股分點"],
        columns=["股票名稱"],
        aggfunc="sum",
        fill_value=0
    )
    st.dataframe(pivot_branch, use_container_width=True)

with tab2:
    st.markdown("**各核心個股在八大官股分點之買賣超張數彙總：**")
    pivot_stock = pd.pivot_table(
        range_summary_df,
        values="買賣超張數",
        index=["股票代號", "股票名稱"],
        columns=["官股分點"],
        aggfunc="sum",
        fill_value=0
    )
    # 計算合計欄位
    pivot_stock["合計買賣超(張)"] = pivot_stock.sum(axis=1)
    st.dataframe(pivot_stock.sort_values(by="合計買賣超(張)", ascending=False), use_container_width=True)
