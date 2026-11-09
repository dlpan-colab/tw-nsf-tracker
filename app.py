"""
模組名稱：app.py
版本識別：20261110_0030
修改目的：
1. 更新版本識別為 20261110_0030。
2. 區間個股統計表欄位整併：
   - 移除重複的「合計買賣超(張)」欄位。
   - 若欄位中包含「全部官股合計」，直接重新命名為「官股買賣超(張)」，確保欄位單一不重複。
3. 個股穿透檢視選單剔除 0 張標的：移除 zero_sorted，僅保留買超與賣超張數非 0 的標的。
4. 維持回補天數參數化滑桿與「⚡ 強制回補缺失交易日資料」功能鍵。
5. 維持買賣超前 30 名、無名次欄位、張數在金額之前等既有設定。
防呆防錯原因：
1. 重命名欄位時加入條件判斷，避免欄位不存在引發 KeyError。
2. 剔除 0 張標的後，若無買賣超標的則以友善提示說明，防範下拉選單為空引發 IndexError。
"""

MODULE_VERSION = "20261110_0030"

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
    clear_gov_cache,
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

col_fill_param, col_btn = st.columns([3, 2])
with col_fill_param:
    fill_days_param = st.slider("單次回補缺失天數上限", min_value=5, max_value=30, value=10, step=5)
with col_btn:
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
    if st.button("⚡ 強制回補缺失交易日資料", use_container_width=True):
        clear_gov_cache()
        with st.spinner(f"正在強制回補近 {fill_days_param} 個缺失交易日數據並同步雲端..."):
            fetch_range_gov_branch_summary(
                stat_start.strftime("%Y-%m-%d"),
                stat_end.strftime("%Y-%m-%d"),
                max_fill_days=fill_days_param
            )
        st.success("回補作業完成，資料庫已更新並同步！")
        st.rerun()

st.info(f"當前彙總統計區間：**{stat_start.strftime('%Y-%m-%d')}** 至 **{stat_end.strftime('%Y-%m-%d')}**")

range_summary_df = fetch_range_gov_branch_summary(
    stat_start.strftime("%Y-%m-%d"),
    stat_end.strftime("%Y-%m-%d"),
    max_fill_days=fill_days_param
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
        # 透視表：代號、名稱為 index，官股分點為 columns
        pivot_stock = pd.pivot_table(
            range_summary_df,
            values="買賣超張數",
            index=["代號", "名稱"],
            columns=["官股分點"],
            aggfunc="sum",
            fill_value=0
        )

        # 欄位整併：若包含「全部官股合計」，更名為「官股買賣超(張)」；若有多分點則加總為該單一欄位
        if "全部官股合計" in pivot_stock.columns:
            pivot_stock = pivot_stock.rename(columns={"全部官股合計": "官股買賣超(張)"})
        elif "官股買賣超(張)" not in pivot_stock.columns:
            pivot_stock["官股買賣超(張)"] = pivot_stock.sum(axis=1)

        # 區分買超與賣超子頁籤（純粹依「官股買賣超(張)」進行篩選與排序）
        stock_buy_df = pivot_stock[pivot_stock["官股買賣超(張)"] > 0].sort_values(by="官股買賣超(張)", ascending=False)
        stock_sell_df = pivot_stock[pivot_stock["官股買賣超(張)"] < 0].sort_values(by="官股買賣超(張)", ascending=True)

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
        st.markdown("#### 🔍 個股穿透檢視：官股合計與五大主力分點每日進出走勢")

        stock_summary = range_summary_df.groupby(["代號", "名稱"], as_index=False)["買賣超張數"].sum()

        # 1. 買超個股：買賣超張數 > 0，絕對值由大到小
        buy_sorted = stock_summary[stock_summary["買賣超張數"] > 0].copy()
        buy_sorted["abs_vol"] = buy_sorted["買賣超張數"].abs()
        buy_sorted = buy_sorted.sort_values(by="abs_vol", ascending=False)

        # 2. 賣超個股：買賣超張數 < 0，絕對值由小到大（賣超最少至賣超最多）
        sell_sorted = stock_summary[stock_summary["買賣超張數"] < 0].copy()
        sell_sorted["abs_vol"] = sell_sorted["買賣超張數"].abs()
        sell_sorted = sell_sorted.sort_values(by="abs_vol", ascending=True)

        # 嚴格排除買賣超為 0 張之標的，僅串接非零買賣超標的
        ordered_summary = pd.concat([buy_sorted, sell_sorted], ignore_index=True)

        if not ordered_summary.empty:
            stock_options = [
                f"{r['代號']} {r['名稱']} ({'+' if r['買賣超張數'] > 0 else ''}{int(r['買賣超張數']):,}張)"
                for _, r in ordered_summary.iterrows()
            ]

            selected_stock_label = st.selectbox("請選擇欲深入檢視的個股：", stock_options, index=0)
            selected_code = selected_stock_label.split()[0]
            selected_name = selected_stock_label.split()[1] if len(selected_stock_label.split()) > 1 else ""

            target_stock_df = range_summary_df[range_summary_df["代號"] == selected_code]

            # 1. 全部官股合計走勢圖
            total_stock_df = target_stock_df[target_stock_df["官股分點"] == "全部官股合計"].sort_values("交易日期")
            if not total_stock_df.empty:
                st.markdown(f"**【{selected_code} {selected_name}】 全部官股合計每日買賣超走勢：**")
                tot_colors = ["#E74C3C" if v >= 0 else "#2ECC71" for v in total_stock_df["買賣超張數"]]
                fig_total = go.Figure(data=[
                    go.Bar(
                        x=total_stock_df["交易日期"],
                        y=total_stock_df["買賣超張數"],
                        marker_color=tot_colors,
                        hovertemplate="日期: %{x}<br>合計買賣超: %{y}張<extra></extra>"
                    )
                ])
                fig_total.update_layout(
                    title=dict(text="<b>全部官股合計</b>", font=dict(size=14)),
                    height=260,
                    margin=dict(l=20, r=10, t=35, b=25),
                    xaxis=dict(type="category", showticklabels=True, tickfont=dict(size=9)),
                    yaxis=dict(title="張數", title_font=dict(size=10), tickfont=dict(size=9)),
                    showlegend=False
                )
                st.plotly_chart(fig_total, use_container_width=True)

            # 2. 排除合計後的 5 大主力實體分點
            specific_branch_df = target_stock_df[target_stock_df["官股分點"] != "全部官股合計"]
            if not specific_branch_df.empty:
                branch_activity = specific_branch_df.groupby("官股分點")["買賣超張數"].apply(lambda s: s.abs().sum()).sort_values(ascending=False)
                top_5_branches = branch_activity.head(5).index.tolist()

                st.markdown(f"**【{selected_code} {selected_name}】 區間內最大買賣超 5 大實體分點每日走勢圖：**")
                chart_cols = st.columns(min(len(top_5_branches), 3)) if top_5_branches else []
                for i, branch_name in enumerate(top_5_branches):
                    col_target = chart_cols[i % len(chart_cols)]
                    b_df = specific_branch_df[specific_branch_df["官股分點"] == branch_name].sort_values("交易日期")
                    
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
                st.info("所選期間之各實體券商分點明細尚在陸續回補入庫中，目前先提供官股合計總覽圖。")
        else:
            st.info("所選區間無買賣超非 0 之個股資料可供繪製柱狀圖。")
