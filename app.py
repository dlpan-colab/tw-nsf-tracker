"""
模組名稱：app.py
版本識別：20261109_1335
修改目的：
1. 更新版本識別為 20261109_1335，並僅於頂部呈現系統版本識別。
2. 傳入完整的 Plotly 配置（config），啟用雙指/滾輪縮放（scrollZoom=True），並將預設操作綁定為平移（pan2d）。
3. 移除選取框工具按鈕（select2d, lasso2d, boxzoom），杜絕單指滑動引發灰色選區遮罩。
防呆防錯原因：
1. 嚴格鎖定 ModeBar 的工具項目，防止使用者誤觸進入框選或選取模式。
"""

MODULE_VERSION = "20261109_1335"

import streamlit as st
import datetime
import pandas as pd
import data_loader
import chart_builder
from data_loader import (
    load_policy_events,
    fetch_taiex_data,
    fetch_gov_branch_trades,
    fetch_range_gov_branch_summary,
    GOV_BANKS
)
from chart_builder import build_taiex_chart

# 提取最大版本識別
all_versions = [
    getattr(data_loader, "MODULE_VERSION", "0"),
    getattr(chart_builder, "MODULE_VERSION", "0"),
    MODULE_VERSION
]
SYSTEM_VERSION = max(all_versions)

st.set_page_config(page_title="國安基金動向與八大官股分點分析", layout="wide")

# CSS 深度穿透：鎖定按鈕列同列橫排
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

# 僅顯示系統版本識別
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
start_default = datetime.date(2020, 1, 1)
end_default = datetime.date.today()

col_s, col_e = st.sidebar.columns(2)
start_date = col_s.date_input("大盤載入起日", start_default)
end_date = col_e.date_input("大盤載入迄日", end_default)

if start_date > end_date:
    st.sidebar.error("大盤載入起日不能晚於迄日！")
    st.stop()

# 2. 載入資料
events_df = load_policy_events("policy_events.json")
with st.spinner("載入加權指數數據中..."):
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

# 4. 繪製圖表（配置：單指平移、雙指/滾輪縮放、徹底移除框選遮罩工具）
chart_fig = build_taiex_chart(
    taiex_df,
    events_df,
    display_bars=display_days,
    target_date_idx=st.session_state.focus_target_idx
)
st.plotly_chart(
    chart_fig,
    use_container_width=True,
    config={
        "scrollZoom": True,
        "displayModeBar": True,
        "modeBarButtonsToRemove": [
            "select2d",
            "lasso2d",
            "zoom2d",
            "zoomIn2d",
            "zoomOut2d",
            "autoScale2d",
            "resetScale2d"
        ],
        "modeBarButtonsToAdd": ["pan2d"]
    }
)

st.markdown("---")

# 5. 指定交易日官股分點檢視
st.subheader("【指定交易日】分點進出明細")

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
