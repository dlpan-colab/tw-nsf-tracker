"""
模組名稱：app.py
版本識別：20261112_0007
修改目的：
1. 更新版本識別為台灣時間 20261112_0007。
2. 診斷展開區全面改用防呆取值（.get()），徹底排除 KeyError: 'idx' 崩潰。
3. 終端機 print 加入 flush=True，確保後台日誌不再被緩衝區吞沒。
防呆防錯原因：
1. 避免 data_loader.py 回傳不同字典結構時造成取值中斷，保證前台穩定運行。
"""

MODULE_VERSION = "20261112_0007"

import streamlit as st
import datetime
from zoneinfo import ZoneInfo
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
    purge_gov_database,
    fetch_histock_latest_gov_trades,
    sync_df_to_storage,
    GOV_BANKS,
    get_tw_today
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

st.caption(f"系統版本識別（台灣時間）：{SYSTEM_VERSION}")
st.subheader("國安基金政策標記與官股分點進出分析 (tw-nsf-tracker)")

today_tw = get_tw_today()

if "focus_target_idx" not in st.session_state:
    st.session_state.focus_target_idx = None
if "focus_date_val" not in st.session_state:
    st.session_state.focus_date_val = today_tw

for key in ["idx_NSF_AUTH", "idx_NSF_EXIT", "idx_SHORT_RESTRICT", "idx_SHORT_LIFT"]:
    if key not in st.session_state:
        st.session_state[key] = -1

# 側邊欄設定
st.sidebar.header("圖表顯示設定")
display_days = st.sidebar.slider("K線預設顯示天數", min_value=10, max_value=120, value=30, step=5)

st.sidebar.markdown("---")
st.sidebar.header("大盤行情載入區間")
start_default = datetime.date(2000, 1, 1)
end_default = today_tw
col_s, col_e = st.sidebar.columns(2)
start_date = col_s.date_input("大盤載入起日", start_default)
end_date = col_e.date_input("大盤載入迄日", end_default)

if start_date > end_date:
    st.sidebar.error("大盤載入起日不能晚於迄日！")
    st.stop()

# 側邊欄：獨立「資料庫維護與真實回補」功能區
st.sidebar.markdown("---")
st.sidebar.header("官股資料維護與回補")

if st.sidebar.button("⚡ 抓取 HiStock 最新真實官股結算", use_container_width=True):
    print("\n" + "#" * 60, flush=True)
    print("[APP] 使用者觸發【抓取 HiStock 最新真實官股結算】，執行診斷日誌...", flush=True)
    with st.spinner("正在抓取 HiStock 並解析表格結構..."):
        df_real, actual_d, status_msg, debug_info = fetch_histock_latest_gov_trades()
        print(f"[APP] 執行結果: 取得筆數={len(df_real)}, 日期={actual_d}, 訊息={status_msg}", flush=True)
        print("#" * 60 + "\n", flush=True)
        
        st.session_state["histock_debug_info"] = debug_info
        st.session_state["histock_status_msg"] = status_msg
        
        if not df_real.empty:
            ok = sync_df_to_storage(df_real)
            if ok:
                st.session_state.focus_date_val = datetime.datetime.strptime(actual_d, "%Y-%m-%d").date()
                st.sidebar.success(f"【成功入庫】已取得 {actual_d} 共 {len(df_real)} 筆官股資料！")
                st.rerun()
            else:
                st.sidebar.error("寫入 Google Drive 失敗，請檢查憑證。")
        else:
            st.sidebar.info(f"回報：{status_msg}")

if "histock_debug_info" in st.session_state and st.session_state["histock_debug_info"]:
    with st.sidebar.expander("🔍 查看 HiStock 表格結構診斷"):
        st.write(f"狀態：{st.session_state.get('histock_status_msg', '')}")
        for idx, t in enumerate(st.session_state["histock_debug_info"]):
            src_label = t.get("來源", f"表格 #{t.get('idx', idx)}")
            shape_info = f" (形狀: {t['shape']})" if "shape" in t else ""
            st.markdown(f"**{src_label}{shape_info}**")
            if "columns" in t:
                st.code(str(t["columns"]), language="python")
            if t.get("head2"):
                st.json(t["head2"])
            other_info = {k: v for k, v in t.items() if k not in ["來源", "idx", "shape", "columns", "head2"]}
            if other_info:
                st.json(other_info)

if st.sidebar.button("🗑️ 清除歷史資料庫", use_container_width=True):
    print("\n[APP] 使用者觸發【清除歷史資料庫】...", flush=True)
    if purge_gov_database():
        st.sidebar.success("已成功清空本機與雲端舊資料庫！")
        st.rerun()
    else:
        st.sidebar.error("清空資料庫失敗，請檢查雲端金鑰連線。")

# 2. 載入大盤資料
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
    st.session_state.focus_date_val = today_tw

# 4. 繪製大盤圖表
chart_fig = build_taiex_chart(
    taiex_df,
    events_df,
    display_bars=display_days,
    target_date_idx=st.session_state.focus_target_idx
)
render_interactive_chart(chart_fig, taiex_df, height=580)

st.markdown("---")

# 5. 指定交易日官股分點檢視
st.subheader("【指定交易日】八大官股分點買賣超標的排名")
col_sel_date, col_sel_bank = st.columns(2)
with col_sel_date:
    focus_date = st.date_input("選擇關注交易日", value=st.session_state.focus_date_val)
with col_sel_bank:
    selected_bank = st.selectbox("篩選官股券商分點", ["全部官股合計"] + GOV_BANKS)

single_day_df = fetch_gov_branch_trades(focus_date.strftime("%Y-%m-%d"))
DISPLAY_COLS = ["代號", "名稱", "買進張數", "賣出張數", "買賣超張數", "金額(萬元)"]

if single_day_df.empty:
    st.info(f"{focus_date.strftime('%Y-%m-%d')} 目前資料庫尚無該日真實官股紀錄。若需補充，請於左側欄點擊「⚡ 抓取 HiStock 最新真實官股結算」。")
else:
    if selected_bank != "全部官股合計":
        day_target_df = single_day_df[single_day_df["官股分點"] == selected_bank]
    else:
        day_target_df = single_day_df[single_day_df["官股分點"] != "全部官股合計"].groupby(
            ["代號", "名稱"], as_index=False
        ).agg({
            "買進張數": "sum",
            "賣出張數": "sum",
            "買賣超張數": "sum",
            "金額(萬元)": "sum"
        })
        if day_target_df.empty:
            day_target_df = single_day_df[single_day_df["官股分點"] == "全部官股合計"]

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

# 6. 日期區間統計模組（純讀取模式）
st.subheader("【區間統計】官股分點進出彙總分析")
col_qs, col_qe = st.columns(2)
stat_start_default = today_tw - datetime.timedelta(days=30)
stat_start = col_qs.date_input("統計起始日期", stat_start_default)
stat_end = col_qe.date_input("統計結束日期", today_tw)

if stat_start > stat_end:
    st.error("統計起始日期不可晚於結束日期！")
    st.stop()

st.info(f"當前彙總統計區間：**{stat_start.strftime('%Y-%m-%d')}** 至 **{stat_end.strftime('%Y-%m-%d')}**（純讀取真實資料庫）")

range_summary_df = fetch_range_gov_branch_summary(
    stat_start.strftime("%Y-%m-%d"),
    stat_end.strftime("%Y-%m-%d")
)

if range_summary_df.empty:
    st.info("所選統計區間內查無官股進出紀錄。請先於左側側邊欄點擊「⚡ 抓取 HiStock 最新真實官股結算」。")
else:
    tab_branch, tab_stock = st.tabs(["各分點進出個股統計", "個股於各分點統計"])
    with tab_branch:
        st.markdown("**各官股分點於所選區間買賣各個股明細（買賣超張數）：**")
        real_branches_only = range_summary_df[range_summary_df["官股分點"] != "全部官股合計"]
        if not real_branches_only.empty:
            pivot_branch = pd.pivot_table(
                real_branches_only,
                values="買賣超張數",
                index=["官股分點"],
                columns=["名稱"],
                aggfunc="sum",
                fill_value=0
            )
            st.dataframe(pivot_branch, use_container_width=True)
        else:
            st.info("目前資料庫尚無實體分點明細。")

    with tab_stock:
        real_stock_subset = range_summary_df[range_summary_df["官股分點"] != "全部官股合計"]
        if not real_stock_subset.empty:
            pivot_stock = pd.pivot_table(
                real_stock_subset,
                values="買賣超張數",
                index=["代號", "名稱"],
                columns=["官股分點"],
                aggfunc="sum",
                fill_value=0
            )
            pivot_stock["官股買賣超(張)"] = pivot_stock.sum(axis=1)
        else:
            pivot_stock = pd.pivot_table(
                range_summary_df,
                values="買賣超張數",
                index=["代號", "名稱"],
                columns=["官股分點"],
                aggfunc="sum",
                fill_value=0
            )
            if "全部官股合計" in pivot_stock.columns:
                pivot_stock = pivot_stock.rename(columns={"全部官股合計": "官股買賣超(張)"})
            elif "官股買賣超(張)" not in pivot_stock.columns:
                pivot_stock["官股買賣超(張)"] = pivot_stock.sum(axis=1)

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

    stock_summary = range_summary_df[range_summary_df["官股分點"] != "全部官股合計"].groupby(
        ["代號", "名稱"], as_index=False
    )["買賣超張數"].sum()
    if stock_summary.empty:
        stock_summary = range_summary_df.groupby(["代號", "名稱"], as_index=False)["買賣超張數"].sum()

    buy_sorted = stock_summary[stock_summary["買賣超張數"] > 0].copy()
    buy_sorted["abs_vol"] = buy_sorted["買賣超張數"].abs()
    buy_sorted = buy_sorted.sort_values(by="abs_vol", ascending=False)

    sell_sorted = stock_summary[stock_summary["買賣超張數"] < 0].copy()
    sell_sorted["abs_vol"] = sell_sorted["買賣超張數"].abs()
    sell_sorted = sell_sorted.sort_values(by="abs_vol", ascending=True)

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
        if total_stock_df.empty:
            total_stock_df = target_stock_df.groupby("交易日期", as_index=False)["買賣超張數"].sum().sort_values("交易日期")

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

        # 2. 排除合計後的 5 大主力實體分點每日走勢圖
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
