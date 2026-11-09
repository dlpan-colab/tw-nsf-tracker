"""
模組名稱：app.py
版本識別：20261109_2330
修改目的：
1. 更新版本識別為 20261109_2330。
2. 「個股於各分點統計」拆分子頁籤為「🟢 區間買超個股統計」與「🔴 區間賣超個股統計」。
3. 增加個股穿透功能：於個股統計表下方提供個股選單，自動篩選期間內進出最大的 5 個分點，
   並繪製 5 張各分點每日買賣超柱狀圖（紅買綠賣）。
4. 維持買賣超前 30 名排行、無名次欄位、張數在金額之前等既有設定。
防呆防錯原因：
1. 若所選個股進出的分點不足 5 個，自動依實際分點家數繪圖，避免切片引發 IndexError。
2. 圖表設定 autosize 與響應式佈局，並對無資料狀態進行防呆提示。
"""

MODULE_VERSION = "20261109_2330"

import streamlit as st
import datetime
import pandas as pd
import plotly.graph_objects as go
import data_loader
import chart_builder
import frontend
import cloud_sync
from data_loader import (
    load_policy_events,
    fetch_taiex_data,
    fetch_gov_branch_trades,
    fetch_range_gov_branch_summary,
    GOV_BANKS
)
from chart_builder import build_taiex_chart
from frontend import render_interactive_chart

all_versions = [
    getattr(data_loader, "MODULE_VERSION", "0"),
    getattr(chart_builder, "MODULE_VERSION", "0"),
    getattr(frontend, "MODULE_VERSION", "0"),
    getattr(cloud_sync, "MODULE_VERSION", "0"),
    MODULE_VERSION
]
SYSTEM_VERSION = max(all_versions)

st.set_page_config(page_title="國安基金動向與八大官股分點分析", layout="wide")

st.markdown("""
<style>
div[data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    gap: 6px !important;
    align-items: center !important;
}
div[data-testid="stHorizontalBlock"] > div {
    min-width: 0 !important;
    flex: 1 1 auto !important;
}
.action-title {
    font-size: 14px;
    font-weight: bold;
    white-space: nowrap;
}
</style>
""", unsafe_allow_html=True)

st.caption(f"系統版本識別：{SYSTEM_VERSION}")
st.subheader("國安基金政策標記與官股分點進出分析 (tw-nsf-tracker)")

# 1. 初始化 Session State
if "focus_target_idx" not in st.session_state:
    st.session_state.focus_target_idx = None
if "focus_date_val" not in st.session_state:
    st.session_state.focus_date_val = datetime.date.today()

for key in ["idx_NSF_AUTH", "idx_NSF_EXIT", "idx_SHORT_RESTRICT", "idx_SHORT_LIFT"]:
    if key not in st.session_state:
        st.session_state[key] = -1

# 側邊欄設定
st.sidebar.header("圖表顯示設定")
display_days = st.sidebar.slider("K線預設顯示天數", min_value=10, max_value=120, value=30, step=5)

st.sidebar.markdown("---")
st.sidebar.header("大盤行情載入區間")
start_default = datetime.date(2000, 1, 1)
end_default = datetime.date.today()

col_s, col_e = st.sidebar.columns(2)
start_date = col_s.date_input("大盤載入起日", start_default)
end_date = col_e.date_input("大盤載入迄日", end_default)

if start_date > end_date:
    st.sidebar.error("大盤載入起日不能晚於迄日！")
    st.stop()

# 2. 載入資料
events_df = load_policy_events("policy_events.json")
with st.spinner("載入加權指數歷史數據與雲端同步中..."):
    taiex_df = fetch_taiex_data(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))

if taiex_df.empty:
    st.error("加權指數資料取得為空，請檢查網路連線或日期區間。")
    st.stop()

date_to_idx = {row["Date"]: idx for idx, row in taiex_df.iterrows()}

# 3. 政策事件快速跳轉控制區
st.subheader("政策事件快速定位")

def jump_event(event_type: str, direction: int):
    sub_df = events_df[events_df["type"] == event_type].sort_values("Date").reset_index(drop=True)
    if sub_df.empty:
        st.warning(f"目前無此事件資料：{event_type}")
        return
    
    state_key = f"idx_{event_type}"
    curr = st.session_state[state_key]
    new_idx = curr + direction
    
    if new_idx < 0:
        new_idx = 0
        st.info("已達第一個歷史事件。")
    elif new_idx >= len(sub_df):
        new_idx = len(sub_df) - 1
        st.info("已達最後一個歷史事件。")
        
    st.session_state[state_key] = new_idx
    target_date = sub_df.iloc[new_idx]["Date"]
    
    if target_date in date_to_idx:
        st.session_state.focus_target_idx = int(date_to_idx[target_date])
        st.session_state.focus_date_val = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        future_dates = taiex_df[taiex_df["Date"] >= target_date]
        if not future_dates.empty:
            match_date = future_dates.iloc[0]["Date"]
            st.session_state.focus_target_idx = int(date_to_idx[match_date])
            st.session_state.focus_date_val = datetime.datetime.strptime(match_date, "%Y-%m-%d").date()

def render_event_buttons(title_html: str, event_key: str):
    c_title, c_prev, c_next = st.columns([4, 3, 3])
    with c_title:
        st.markdown(f"<div class='action-title'>{title_html}</div>", unsafe_allow_html=True)
    with c_prev:
        if st.button("上一個", key=f"prev_{event_key}", use_container_width=True):
            jump_event(event_key, -1)
    with c_next:
        if st.button("下一個", key=f"next_{event_key}", use_container_width=True):
            jump_event(event_key, 1)

render_event_buttons("<span style='color:red;'>國安基金進場 (▲)</span>", "NSF_AUTH")
render_event_buttons("<span style='color:green;'>國安基金退場 (▼)</span>", "NSF_EXIT")
render_event_buttons("<span style='color:#D4AC0D;'>金管會限空令 (▲)</span>", "SHORT_RESTRICT")
render_event_buttons("<span style='color:#2980B9;'>限空令解除 (▼)</span>", "SHORT_LIFT")

if st.button("重設回最新交易日視圖", use_container_width=True):
    st.session_state.focus_target_idx = None
    st.session_state.focus_date_val = datetime.date.today()

# 4. 繪製圖表
chart_fig = build_taiex_chart(
    taiex_df,
    events_df,
    display_bars=display_days,
    target_date_idx=st.session_state.focus_target_idx
)
render_interactive_chart(chart_fig, taiex_df, height=580)

st.markdown("---")

# 5. 指定交易日官股分點檢視（買超前 30 名 / 賣超前 30 名）
st.subheader("【指定交易日】八大官股分點買賣超標的排名")

col_sel_date, col_sel_bank = st.columns(2)
with col_sel_date:
    focus_date = st.date_input("選擇關注交易日", value=st.session_state.focus_date_val)
with col_sel_bank:
    selected_bank = st.selectbox("篩選官股券商分點", ["全部官股合計"] + GOV_BANKS)

single_day_df = fetch_gov_branch_trades(focus_date.strftime("%Y-%m-%d"))

DISPLAY_COLS = ["代號", "名稱", "買進張數", "賣出張數", "買賣超張數", "金額(萬元)"]

if single_day_df.empty:
    st.info(f"{focus_date.strftime('%Y-%m-%d')} 尚無官方公布之八大官股買賣超排行紀錄（可能逢假日休市或盤後數據尚未產出）。")
else:
    if selected_bank != "全部官股合計":
        day_target_df = single_day_df[single_day_df["官股分點"] == selected_bank]
    else:
        day_target_df = single_day_df.groupby(["代號", "名稱"], as_index=False).agg({
            "買進張數": "sum",
            "賣出張數": "sum",
            "買賣超張數": "sum",
            "金額(萬元)": "sum"
        })

    # 嚴格依金額排序：買超正值降冪；賣超負值升冪
    buy_pool = day_target_df[day_target_df["金額(萬元)"] > 0].copy()
    sell_pool = day_target_df[day_target_df["金額(萬元)"] < 0].copy()

    top_buy_30 = buy_pool.sort_values(by="金額(萬元)", ascending=False).head(30).reset_index(drop=True)
    top_sell_30 = sell_pool.sort_values(by="金額(萬元)", ascending=True).head(30).reset_index(drop=True)

    tab_buy, tab_sell = st.tabs(["🟢 官股買超前 30 名", "🔴 官股賣超前 30 名"])

    with tab_buy:
        st.markdown(f"**{focus_date.strftime('%Y-%m-%d')} 【{selected_bank}】 買超金額前 30 名：**")
        if not top_buy_30.empty:
            st.dataframe(top_buy_30[DISPLAY_COLS], use_container_width=True, hide_index=True)
        else:
            st.info("當日無官股買超標的紀錄。")

    with tab_sell:
        st.markdown(f"**{focus_date.strftime('%Y-%m-%d')} 【{selected_bank}】 賣超金額前 30 名：**")
        if not top_sell_30.empty:
            st.dataframe(top_sell_30[DISPLAY_COLS], use_container_width=True, hide_index=True)
        else:
            st.info("當日無官股賣超標的紀錄。")

st.markdown("---")

# 6. 日期區間統計模組
st.subheader("【區間統計】官股分點進出彙總分析")

col_qs, col_qe = st.columns(2)
stat_start_default = end_default - datetime.timedelta(days=30)
stat_start = col_qs.date_input("統計起始日期", stat_start_default)
stat_end = col_qe.date_input("統計結束日期", end_default)

if stat_start > stat_end:
    st.error("統計起始日期不可晚於結束日期！")
    st.stop()

st.info(f"當前彙總統計區間：**{stat_start.strftime('%Y-%m-%d')}** 至 **{stat_end.strftime('%Y-%m-%d')}**")

range_summary_df = fetch_range_gov_branch_summary(
    stat_start.strftime("%Y-%m-%d"),
    stat_end.strftime("%Y-%m-%d")
)

if range_summary_df.empty:
    st.info("所選統計區間內查無官股進出紀錄。")
else:
    tab_branch, tab_stock = st.tabs(["各分點進出個股統計", "個股於各分點統計"])

    with tab_branch:
        st.markdown("**各官股分點於所選區間買賣各個股明細（買賣超張數）：**")
        pivot_branch = pd.pivot_table(
            range_summary_df,
            values="買賣超張數",
            index=["官股分點"],
            columns=["名稱"],
            aggfunc="sum",
            fill_value=0
        )
        st.dataframe(pivot_branch, use_container_width=True)

    with tab_stock:
        # 計算每檔個股在各分點的合計
        pivot_stock = pd.pivot_table(
            range_summary_df,
            values="買賣超張數",
            index=["代號", "名稱"],
            columns=["官股分點"],
            aggfunc="sum",
            fill_value=0
        )
        pivot_stock["合計買賣超(張)"] = pivot_stock.sum(axis=1)

        # 區分買超與賣超子頁籤
        stock_buy_df = pivot_stock[pivot_stock["合計買賣超(張)"] > 0].sort_values(by="合計買賣超(張)", ascending=False)
        stock_sell_df = pivot_stock[pivot_stock["合計買賣超(張)"] < 0].sort_values(by="合計買賣超(張)", ascending=True)

        tab_stock_buy, tab_stock_sell = st.tabs(["🟢 區間買超個股統計", "🔴 區間賣超個股統計"])

        with tab_stock_buy:
            st.markdown("**所選區間【買超】個股於各分點分佈：**")
            if not stock_buy_df.empty:
                st.dataframe(stock_buy_df, use_container_width=True)
            else:
                st.info("此區間無合計買超之個股。")

        with tab_stock_sell:
            st.markdown("**所選區間【賣超】個股於各分點分佈：**")
            if not stock_sell_df.empty:
                st.dataframe(stock_sell_df, use_container_width=True)
            else:
                st.info("此區間無合計賣超之個股。")

        st.markdown("---")
        st.markdown("#### 🔍 個股穿透檢視：最大買賣超五大分點每日進出明細")

        # 彙整所有出現過的個股代號與名稱作為下拉選單
        available_stocks = range_summary_df[["代號", "名稱"]].drop_duplicates().sort_values("代號")
        stock_options = [f"{r['代號']} {r['名稱']}" for _, r in available_stocks.iterrows()]

        if stock_options:
            selected_stock_label = st.selectbox("請選擇欲深入檢視的個股：", stock_options, index=0)
            selected_code = selected_stock_label.split()[0]
            selected_name = selected_stock_label.split()[1] if len(selected_stock_label.split()) > 1 else ""

            # 提取該個股的歷史進出紀錄
            target_stock_df = range_summary_df[range_summary_df["代號"] == selected_code]

            # 計算該個股在各分點的絕對值累計進出，取前 5 大主力分點
            branch_activity = target_stock_df.groupby("官股分點")["買賣超張數"].apply(lambda s: s.abs().sum()).sort_values(ascending=False)
            top_5_branches = branch_activity.head(5).index.tolist()

            st.markdown(f"**【{selected_stock_label}】 區間內最大買賣超 5 大分點每日走勢圖：**")

            # 依序呈現 5 張柱狀圖（以 2~3 欄位清晰呈現）
            chart_cols = st.columns(min(len(top_5_branches), 3)) if top_5_branches else []
            for i, branch_name in enumerate(top_5_branches):
                col_target = chart_cols[i % len(chart_cols)]
                b_df = target_stock_df[target_stock_df["官股分點"] == branch_name].sort_values("交易日期")
                
                # 柱狀顏色：買超為紅、賣超為綠
                colors = ["#E74C3C" if v >= 0 else "#2ECC71" for v in b_df["買賣超張數"]]
                
                fig_branch = go.Figure(data=[
                    go.Bar(
                        x=b_df["交易日期"],
                        y=b_df["買賣超張數"],
                        marker_color=colors,
                        hovertemplate="日期: %{x}<br>買賣超: %{y}張<extra></extra>"
                    )
                ])
                fig_branch.update_layout(
                    title=dict(text=f"<b>{branch_name}</b>", font=dict(size=13)),
                    height=240,
                    margin=dict(l=20, r=10, t=35, b=25),
                    xaxis=dict(type="category", showticklabels=True, tickfont=dict(size=9)),
                    yaxis=dict(title="張數", title_font=dict(size=10), tickfont=dict(size=9)),
                    showlegend=False
                )
                with col_target:
                    st.plotly_chart(fig_branch, use_container_width=True)
        else:
            st.info("所選區間無個股資料可供繪製柱狀圖。")
