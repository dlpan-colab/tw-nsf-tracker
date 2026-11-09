"""
模組名稱：app.py
修改目的：
1. 支援預設 30 日（可滑桿調整）K 線可視視圖。
2. 新增 4 組政策事件「上一個／下一個」快速跳轉按鈕（國安基金進場/退場、限空令實施/解除）。
3. 保持單日各分點檢視與區間進出統計功能完整。
防呆防錯原因：
1. 使用 Streamlit session_state 保留當前錨定之事件索引，按鈕觸發時進行邊界檢查（索引不小於 0 且不大於清單長度），避免 IndexOutOfRange。
2. 跳轉時自動將關注交易日連動為該事件日，避免圖表與下方表格日期脫鉤。
"""

import streamlit as st
import datetime
import pandas as pd
from data_loader import (
    load_policy_events,
    fetch_taiex_data,
    fetch_gov_branch_trades,
    fetch_range_gov_branch_summary,
    GOV_BANKS
)
from chart_builder import build_taiex_chart

st.set_page_config(page_title="國安基金動向與八大官股分點分析", layout="wide")

# 1. 初始化 Session State 狀態（防呆維護當前視角與事件索引）
if "focus_target_idx" not in st.session_state:
    st.session_state.focus_target_idx = None  # None 代表預設最新資料
if "focus_date_val" not in st.session_state:
    st.session_state.focus_date_val = datetime.date.today()

# 儲存 4 類事件的當前遊標索引
for key in ["idx_NSF_AUTH", "idx_NSF_EXIT", "idx_SHORT_RESTRICT", "idx_SHORT_LIFT"]:
    if key not in st.session_state:
        st.session_state[key] = -1

# 側邊欄：顯示天數與整體數據加載範圍
st.sidebar.header("圖表顯示設定")
display_days = st.sidebar.slider("K線預設顯示天數", min_value=10, max_value=120, value=30, step=5)

st.sidebar.markdown("---")
st.sidebar.header("歷史行情加載區間")
start_default = datetime.date(2020, 1, 1)
end_default = datetime.date.today()

col_s, col_e = st.sidebar.columns(2)
start_date = col_s.date_input("加載起日", start_default)
end_date = col_e.date_input("加載迄日", end_default)

if start_date > end_date:
    st.sidebar.error("加載起日不能晚於迄日！")
    st.stop()

# 2. 載入資料
events_df = load_policy_events("policy_events.json")
with st.spinner("載入加權指數數據中..."):
    taiex_df = fetch_taiex_data(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))

if taiex_df.empty:
    st.error("加權指數資料取得為空，請檢查網路連線或日期區間。")
    st.stop()

# 日期與索引對照對齊字典（防呆查詢）
date_to_idx = {row["Date"]: idx for idx, row in taiex_df.iterrows()}

st.title("國安基金政策標記與官股分點進出分析 (tw-nsf-tracker)")

# 3. 政策事件跳轉按鈕工具列
st.subheader("政策事件快速定位")

def jump_event(event_type: str, direction: int):
    """
    修改目的：跳轉指定政策事件的上一個或下一個。
    防呆防錯原因：驗證事件子集是否為空，並限制游標在合法索引範圍內，避免邊界溢出。
    """
    sub_df = events_df[events_df["type"] == event_type].sort_values("Date").reset_index(drop=True)
    if sub_df.empty:
        st.warning(f"目前無此事件資料：{event_type}")
        return
    
    state_key = f"idx_{event_type}"
    curr = st.session_state[state_key]
    new_idx = curr + direction
    
    # 邊界防呆
    if new_idx < 0:
        new_idx = 0
        st.info("已達第一個歷史事件。")
    elif new_idx >= len(sub_df):
        new_idx = len(sub_df) - 1
        st.info("已達最後一個歷史事件。")
        
    st.session_state[state_key] = new_idx
    target_date = sub_df.iloc[new_idx]["Date"]
    
    # 查找加權指數對應的行情索引
    if target_date in date_to_idx:
        st.session_state.focus_target_idx = date_to_idx[target_date]
        st.session_state.focus_date_val = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        # 防呆：若該事件日為非交易日（如週末公布），找其後最近的一個交易日
        future_dates = taiex_df[taiex_df["Date"] >= target_date]
        if not future_dates.empty:
            match_date = future_dates.iloc[0]["Date"]
            st.session_state.focus_target_idx = date_to_idx[match_date]
            st.session_state.focus_date_val = datetime.datetime.strptime(match_date, "%Y-%m-%d").date()

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown("**:red[國安基金進場 (▲)]**")
    b1, b2 = st.columns(2)
    if b1.button("上一個", key="prev_nsf_auth"):
        jump_event("NSF_AUTH", -1)
    if b2.button("下一個", key="next_nsf_auth"):
        jump_event("NSF_AUTH", 1)

with c2:
    st.markdown("**:green[國安基金退場 (▼)]**")
    b3, b4 = st.columns(2)
    if b3.button("上一個", key="prev_nsf_exit"):
        jump_event("NSF_EXIT", -1)
    if b4.button("下一個", key="next_nsf_exit"):
        jump_event("NSF_EXIT", 1)

with c3:
    st.markdown("**:orange[金管會限空令 (▲)]**")
    b5, b6 = st.columns(2)
    if b5.button("上一個", key="prev_short_r"):
        jump_event("SHORT_RESTRICT", -1)
    if b6.button("下一個", key="next_short_r"):
        jump_event("SHORT_RESTRICT", 1)

with c4:
    st.markdown("**:blue[限空令解除 (▼)]**")
    b7, b8 = st.columns(2)
    if b7.button("上一個", key="prev_short_l"):
        jump_event("SHORT_LIFT", -1)
    if b8.button("下一個", key="next_short_l"):
        jump_event("SHORT_LIFT", 1)

if st.button("重設回最新交易日視圖"):
    st.session_state.focus_target_idx = None
    st.session_state.focus_date_val = datetime.date.today()

# 4. 繪製圖表（鎖定 Y 軸、動態自適應極值、X 軸右邊界對齊）
chart_fig = build_taiex_chart(
    taiex_df,
    events_df,
    display_bars=display_days,
    target_date_idx=st.session_state.focus_target_idx
)
st.plotly_chart(chart_fig, use_container_width=True)

st.markdown("---")

# 5. 指定交易日官股分點檢視
st.subheader(f"【指定交易日】分點進出明細")

col_sel_date, col_sel_bank = st.columns(2)
with col_sel_date:
    focus_date = st.date_input("選擇關注交易日", value=st.session_state.focus_date_val)
with col_sel_bank:
    selected_bank = st.selectbox("篩選官股券商分點", ["全部官股合計"] + GOV_BANKS)

single_day_df = fetch_gov_branch_trades(focus_date.strftime("%Y-%m-%d"))

if selected_bank != "全部官股合計":
    filtered_day_df = single_day_df[single_day_df["官股分點"] == selected_bank]
else:
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

# 6. 日期區間統計模組
st.subheader("【區間統計】官股分點進出彙總分析")

range_summary_df = fetch_range_gov_branch_summary(
    start_date.strftime("%Y-%m-%d"),
    end_date.strftime("%Y-%m-%d")
)

tab1, tab2 = st.tabs(["各分點進出個股統計", "個股於各分點統計"])

with tab1:
    st.markdown("**各官股分點於所選區間買賣各個股明細（買賣超張數）：**")
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
    pivot_stock["合計買賣超(張)"] = pivot_stock.sum(axis=1)
    st.dataframe(pivot_stock.sort_values(by="合計買賣超(張)", ascending=False), use_container_width=True)
