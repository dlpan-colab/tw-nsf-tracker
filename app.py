"""
模組名稱：app.py
版本識別：20261112_2235
修改目的：
1. 更新版本識別為台灣時間 20261112_2235。
2. 模組一（指定日八大官股買/賣超前 30 名）：參數化交易日選擇器，預設為系統最後一個有效交易日（get_latest_available_gov_date），
   若本地/雲端庫尚無該日資料則自動向 HiStock 即時抓取指定日結算（?d=YYYY-MM-DD）並入庫，完整表列買超與賣超前 30 名（單位：萬元）。
3. 模組二（指定期間八大官股買/賣超合計各前 30 名）：參數化起迄日期，預設為「最後一個交易日前 1 個月（30 天）至最後一個交易日」，
   依據真實「金額(萬元)」彙總表列區間買超前 30 名與賣超前 30 名個股及八大行庫分佈明細。
4. 模組三（買賣超前五名個股下拉選單＋指定期間各分點每日買賣超柱狀圖）：自動篩選指定期間官股買超前 5 名與賣超前 5 名個股放入下拉選單，
   選定個股後即時抓取該期間買超前 5 大分點與賣超前 5 大分點之逐日淨買賣超張數（買進 - 賣出），以紅買綠賣柱狀圖並列呈現。
防呆防錯原因：
1. 全面修正舊版 app.py 依賴「買賣超張數」之錯誤邏輯（HiStock 僅提供金額萬元），所有排行、加總與圖表標題皆改用真實「金額(萬元)」。
2. 指定日若遇假日或資料庫尚未回補，自動觸發 fetch_histock_latest_gov_trades(target_date) 線上補抓並顯示實際成交日提示，避免空白畫面。
3. 各分點逐日明細請求加入 0.25 秒間隔與獨立異常防護，確保 Streamlit Cloud 穩定連線不逾時。
"""

MODULE_VERSION = "20261112_2235"

import time
import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
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
    get_latest_available_gov_date,
    fetch_stock_broker_range_ranking,
    fetch_single_broker_daily_series,
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

# 1. 初始化預設「最後一個交易日」（優先取資料庫最新交易日，若無則即時抓取 HiStock 最新日）
if "latest_trade_date" not in st.session_state:
    db_latest = get_latest_available_gov_date()
    check_df = fetch_gov_branch_trades(db_latest.strftime("%Y-%m-%d"))
    if check_df.empty:
        df_init, actual_init_d, _, _ = fetch_histock_latest_gov_trades()
        if not df_init.empty and actual_init_d:
            sync_df_to_storage(df_init)
            db_latest = datetime.datetime.strptime(actual_init_d, "%Y-%m-%d").date()
    st.session_state.latest_trade_date = db_latest

latest_trade_dt = st.session_state.latest_trade_date

if "focus_target_idx" not in st.session_state:
    st.session_state.focus_target_idx = None
if "focus_date_val" not in st.session_state:
    st.session_state.focus_date_val = latest_trade_dt
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

# 側邊欄：資料庫維護與真實回補功能區
st.sidebar.markdown("---")
st.sidebar.header("官股資料維護與回補")
if st.sidebar.button("⚡ 抓取 HiStock 最新真實官股結算", use_container_width=True):
    with st.spinner("正在抓取 HiStock 最新結算並解析 ul.stock-list..."):
        df_real, actual_d, status_msg, debug_info = fetch_histock_latest_gov_trades()
        st.session_state["histock_debug_info"] = debug_info
        st.session_state["histock_status_msg"] = status_msg
        if not df_real.empty and actual_d:
            ok = sync_df_to_storage(df_real)
            new_dt = datetime.datetime.strptime(actual_d, "%Y-%m-%d").date()
            st.session_state.latest_trade_date = new_dt
            st.session_state.focus_date_val = new_dt
            if ok:
                st.sidebar.success(f"【成功入庫】已取得 {actual_d} 共 {len(df_real)} 筆官股資料！")
            else:
                st.sidebar.warning(f"已取得 {actual_d} 資料（本地已保存，雲端同步未完成）。")
            st.rerun()
        else:
            st.sidebar.info(f"回報：{status_msg}")

if "histock_debug_info" in st.session_state and st.session_state["histock_debug_info"]:
    with st.sidebar.expander("🔍 查看 HiStock 結構解析診斷"):
        st.write(f"狀態：{st.session_state.get('histock_status_msg', '')}")
        for idx, t in enumerate(st.session_state["histock_debug_info"]):
            src_label = t.get("來源", f"區塊 #{idx}")
            st.markdown(f"**{src_label}**")
            other_info = {k: v for k, v in t.items() if k != "來源"}
            if other_info:
                st.json(other_info)

if st.sidebar.button("🗑️ 清除歷史資料庫", use_container_width=True):
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
    st.session_state.focus_date_val = latest_trade_dt

# 4. 繪製大盤圖表
chart_fig = build_taiex_chart(
    taiex_df,
    events_df,
    display_bars=display_days,
    target_date_idx=st.session_state.focus_target_idx
)
render_interactive_chart(chart_fig, taiex_df, height=580)

st.markdown("---")

# =====================================================================
# 模組 (1)：指定日八大官股買/賣超合計各前 30 名（參數化，預設最後一個交易日）
# =====================================================================
st.subheader("【1. 指定交易日】八大官股買／賣超合計各前 30 名")
col_sel_date, col_sel_bank = st.columns(2)
with col_sel_date:
    focus_date = st.date_input("指定交易日（預設最後交易日）", value=st.session_state.focus_date_val, key="single_focus_date")
with col_sel_bank:
    selected_bank = st.selectbox("篩選官股券商分點", ["全部官股合計"] + GOV_BANKS, key="single_bank_select")

focus_date_str = focus_date.strftime("%Y-%m-%d")
single_day_df = fetch_gov_branch_trades(focus_date_str)

# 若資料庫尚無該指定日紀錄，自動向 HiStock 即時抓取該指定日並入庫
if single_day_df.empty:
    with st.spinner(f"資料庫尚無 {focus_date_str} 紀錄，正在向 HiStock 即時查詢該日結算..."):
        fetched_df, actual_fetched_d, fetch_msg, _ = fetch_histock_latest_gov_trades(target_date=focus_date_str)
        if not fetched_df.empty:
            sync_df_to_storage(fetched_df)
            if actual_fetched_d != focus_date_str:
                st.info(f"所選日期 {focus_date_str} 非交易日或尚未結算，HiStock 實際回傳交易日為 **{actual_fetched_d}**。")
            single_day_df = fetched_df[fetched_df["交易日期"] == actual_fetched_d]
            focus_date_str = actual_fetched_d

if single_day_df.empty:
    st.warning(f"{focus_date_str} 查無八大官股買賣超資料，請確認是否為台股開盤日。")
else:
    if selected_bank != "全部官股合計":
        day_target_df = single_day_df[single_day_df["官股分點"] == selected_bank].copy()
    else:
        day_target_df = single_day_df[single_day_df["官股分點"] == "全部官股合計"].copy()
        if day_target_df.empty:
            day_target_df = (
                single_day_df[single_day_df["官股分點"] != "全部官股合計"]
                .groupby(["代號", "名稱"], as_index=False)["金額(萬元)"]
                .sum()
            )

    # 若選「全部官股合計」，額外橫向展開八大行庫各自金額明細供對照
    if selected_bank == "全部官股合計":
        branch_only_day = single_day_df[single_day_df["官股分點"] != "全部官股合計"]
        if not branch_only_day.empty:
            piv_day = pd.pivot_table(
                branch_only_day,
                values="金額(萬元)",
                index=["代號", "名稱"],
                columns=["官股分點"],
                aggfunc="sum",
                fill_value=0.0
            ).reset_index()
            day_merged = pd.merge(day_target_df[["代號", "名稱", "金額(萬元)"]], piv_day, on=["代號", "名稱"], how="left")
            ordered_bank_cols = [b for b in GOV_BANKS if b in day_merged.columns]
            show_cols_day = ["代號", "名稱", "金額(萬元)"] + ordered_bank_cols
        else:
            day_merged = day_target_df[["代號", "名稱", "金額(萬元)"]]
            show_cols_day = ["代號", "名稱", "金額(萬元)"]
    else:
        day_merged = day_target_df[["代號", "名稱", "金額(萬元)"]]
        show_cols_day = ["代號", "名稱", "金額(萬元)"]

    buy_pool = day_merged[day_merged["金額(萬元)"] > 0].sort_values(by="金額(萬元)", ascending=False).head(30).reset_index(drop=True)
    sell_pool = day_merged[day_merged["金額(萬元)"] < 0].sort_values(by="金額(萬元)", ascending=True).head(30).reset_index(drop=True)
    buy_pool.index = buy_pool.index + 1
    sell_pool.index = sell_pool.index + 1

    tab_buy_day, tab_sell_day = st.tabs(["🔴 官股買超前 30 名（萬元）", "🟢 官股賣超前 30 名（萬元）"])
    with tab_buy_day:
        st.markdown(f"**{focus_date_str} 【{selected_bank}】 買超金額前 30 名（單位：萬元）：**")
        if not buy_pool.empty:
            st.dataframe(buy_pool[show_cols_day], use_container_width=True)
        else:
            st.info("當日無官股買超標的紀錄。")
    with tab_sell_day:
        st.markdown(f"**{focus_date_str} 【{selected_bank}】 賣超金額前 30 名（單位：萬元）：**")
        if not sell_pool.empty:
            st.dataframe(sell_pool[show_cols_day], use_container_width=True)
        else:
            st.info("當日無官股賣超標的紀錄。")

st.markdown("---")

# =====================================================================
# 模組 (2)：指定期間八大官股買/賣超合計各前 30 名（預設最後交易日前 1 個月）
# =====================================================================
st.subheader("【2. 指定期間】八大官股買／賣超合計各前 30 名")
col_qs, col_qe = st.columns(2)
stat_start_default = latest_trade_dt - datetime.timedelta(days=30)
stat_start = col_qs.date_input("期間起始日（預設前 1 個月）", value=stat_start_default, key="range_start_date")
stat_end = col_qe.date_input("期間結束日（預設最後交易日）", value=latest_trade_dt, key="range_end_date")

if stat_start > stat_end:
    st.error("期間起始日不可晚於結束日！")
    st.stop()

s_range_str = stat_start.strftime("%Y-%m-%d")
e_range_str = stat_end.strftime("%Y-%m-%d")
st.info(f"當前統計期間：**{s_range_str}** 至 **{e_range_str}**（單位：萬元）")

range_summary_df = fetch_range_gov_branch_summary(s_range_str, e_range_str)

top5_buy_stocks = pd.DataFrame()
top5_sell_stocks = pd.DataFrame()

if range_summary_df.empty:
    st.warning("所選統計期間內資料庫尚無官股紀錄。請先使用上方指定日查詢或左側欄「⚡ 抓取 HiStock 最新真實官股結算」累積資料。")
else:
    # 計算區間「全部官股合計」各個股總金額
    range_total_df = range_summary_df[range_summary_df["官股分點"] == "全部官股合計"]
    if range_total_df.empty:
        range_total_df = range_summary_df[range_summary_df["官股分點"] != "全部官股合計"]

    stock_agg_df = (
        range_total_df.groupby(["代號", "名稱"], as_index=False)["金額(萬元)"]
        .sum()
        .rename(columns={"金額(萬元)": "官股合計(萬元)"})
    )

    # 橫向展開八大行庫於該期間各自累計金額
    range_branch_only = range_summary_df[range_summary_df["官股分點"] != "全部官股合計"]
    if not range_branch_only.empty:
        piv_range = pd.pivot_table(
            range_branch_only,
            values="金額(萬元)",
            index=["代號", "名稱"],
            columns=["官股分點"],
            aggfunc="sum",
            fill_value=0.0
        ).reset_index()
        range_merged = pd.merge(stock_agg_df, piv_range, on=["代號", "名稱"], how="left")
        ordered_range_banks = [b for b in GOV_BANKS if b in range_merged.columns]
        range_display_cols = ["代號", "名稱", "官股合計(萬元)"] + ordered_range_banks
    else:
        range_merged = stock_agg_df
        range_display_cols = ["代號", "名稱", "官股合計(萬元)"]

    range_buy_top30 = range_merged[range_merged["官股合計(萬元)"] > 0].sort_values(by="官股合計(萬元)", ascending=False).head(30).reset_index(drop=True)
    range_sell_top30 = range_merged[range_merged["官股合計(萬元)"] < 0].sort_values(by="官股合計(萬元)", ascending=True).head(30).reset_index(drop=True)
    range_buy_top30.index = range_buy_top30.index + 1
    range_sell_top30.index = range_sell_top30.index + 1

    # 保留買超前 5 名與賣超前 5 名個股供模組 (3) 下拉選單使用
    top5_buy_stocks = range_buy_top30.head(5).copy()
    top5_sell_stocks = range_sell_top30.head(5).copy()

    tab_r_buy, tab_r_sell = st.tabs(["🔴 期間買超合計前 30 名（萬元）", "🟢 期間賣超合計前 30 名（萬元）"])
    with tab_r_buy:
        st.markdown(f"**{s_range_str} ~ {e_range_str} 八大官股買超合計前 30 名（單位：萬元）：**")
        if not range_buy_top30.empty:
            st.dataframe(range_buy_top30[range_display_cols], use_container_width=True)
        else:
            st.info("此期間無合計買超之個股。")
    with tab_r_sell:
        st.markdown(f"**{s_range_str} ~ {e_range_str} 八大官股賣超合計前 30 名（單位：萬元）：**")
        if not range_sell_top30.empty:
            st.dataframe(range_sell_top30[range_display_cols], use_container_width=True)
        else:
            st.info("此期間無合計賣超之個股。")

st.markdown("---")

# =====================================================================
# 模組 (3)：買賣超前五名個股下拉式選單＋指定期間各分點每日買賣超柱狀圖
# =====================================================================
st.subheader("【3. 前五大買賣超個股】指定期間各分點每日買賣超柱狀圖")

dropdown_items = []
if not top5_buy_stocks.empty:
    for rank_i, r in top5_buy_stocks.iterrows():
        dropdown_items.append({
            "label": f"[官股買超 Top {rank_i}] {r['代號']} {r['名稱']}（官股合計：{r['官股合計(萬元)']:+,.0f} 萬）",
            "code": str(r["代號"]).strip(),
            "name": str(r["名稱"]).strip()
        })
if not top5_sell_stocks.empty:
    for rank_i, r in top5_sell_stocks.iterrows():
        dropdown_items.append({
            "label": f"[官股賣超 Top {rank_i}] {r['代號']} {r['名稱']}（官股合計：{r['官股合計(萬元)']:,.0f} 萬）",
            "code": str(r["代號"]).strip(),
            "name": str(r["名稱"]).strip()
        })

if not dropdown_items:
    st.info("目前指定期間尚無官股買賣超前五名個股清單，請先確認模組 (2) 已有該期間官股資料。")
else:
    option_labels = [item["label"] for item in dropdown_items]
    selected_opt_label = st.selectbox(
        f"選擇官股買賣超前五名個股（分析期間：{s_range_str} ~ {e_range_str}）：",
        options=option_labels,
        index=0,
        key="top5_stock_dropdown"
    )
    selected_item = next(item for item in dropdown_items if item["label"] == selected_opt_label)
    sel_code = selected_item["code"]
    sel_name = selected_item["name"]

    def plot_broker_daily_bar(df_daily: pd.DataFrame, title_str: str):
        """繪製單一分點指定期間每日買賣超柱狀圖（紅買綠賣）"""
        bar_colors = ["#E74C3C" if v >= 0 else "#2ECC71" for v in df_daily["買賣超(張)"]]
        fig = go.Figure(
            data=[
                go.Bar(
                    x=df_daily["日期"],
                    y=df_daily["買賣超(張)"],
                    marker_color=bar_colors,
                    customdata=df_daily[["買進(張)", "賣出(張)"]].values,
                    hovertemplate=(
                        "日期：%{x}<br>"
                        "買進：%{customdata[0]:,} 張<br>"
                        "賣出：%{customdata[1]:,} 張<br>"
                        "買賣超：%{y:+,} 張<extra></extra>"
                    )
                )
            ]
        )
        fig.update_layout(
            title=dict(text=f"<b>{title_str}</b>", font=dict(size=13)),
            height=250,
            margin=dict(l=20, r=10, t=38, b=25),
            xaxis=dict(type="category", showticklabels=True, tickfont=dict(size=9)),
            yaxis=dict(title="買賣超(張)", title_font=dict(size=10), tickfont=dict(size=9), zeroline=True, zerolinecolor="#888888"),
            showlegend=False
        )
        st.plotly_chart(fig, use_container_width=True)

    with st.spinner(f"正在抓取【{sel_code} {sel_name}】於 {s_range_str} ~ {e_range_str} 之分點進出與逐日明細..."):
        df_b_rank, df_s_rank = fetch_stock_broker_range_ranking(sel_code, s_range_str, e_range_str)

        if df_b_rank.empty and df_s_rank.empty:
            st.warning(f"無法取得【{sel_code} {sel_name}】在 {s_range_str} ~ {e_range_str} 的券商分點數據。")
        else:
            # 先呈現該期間買賣超分點總表（含八大官股體系標記）
            with st.expander(f"📋 查看【{sel_code} {sel_name}】指定期間買賣超前 15 大分點總表（含八大官股篩選）", expanded=False):
                c_b_tbl, c_s_tbl = st.columns(2)
                with c_b_tbl:
                    st.markdown("**🔴 買超分點 Top 15**")
                    if not df_b_rank.empty:
                        st.dataframe(df_b_rank.drop(columns=["明細網址"]).head(15), use_container_width=True, hide_index=True)
                with c_s_tbl:
                    st.markdown("**🟢 賣超分點 Top 15**")
                    if not df_s_rank.empty:
                        st.dataframe(df_s_rank.drop(columns=["明細網址"]).head(15), use_container_width=True, hide_index=True)

            # 繪製買超前 5 名分點每日買賣超柱狀圖
            st.markdown(f"#### 🔴【{sel_code} {sel_name}】買超前 5 名分點：每日買賣超柱狀圖（張）")
            if not df_b_rank.empty:
                for idx, row in df_b_rank.head(5).iterrows():
                    b_name = row["分點名稱"]
                    b_sys = f" [{row['體系']}]" if row["體系"] == "八大官股" else ""
                    b_tot = row["買賣超(張)"]
                    df_daily = fetch_single_broker_daily_series(row["明細網址"], s_range_str, e_range_str)
                    if not df_daily.empty:
                        plot_broker_daily_bar(
                            df_daily,
                            f"買超 Top {idx + 1}：{b_name}{b_sys}（區間累計：{b_tot:+,} 張）"
                        )
                    else:
                        st.caption(f"買超 Top {idx + 1}：{b_name} 無逐日明細資料。")
                    time.sleep(0.25)

            # 繪製賣超前 5 名分點每日買賣超柱狀圖
            st.markdown(f"#### 🟢【{sel_code} {sel_name}】賣超前 5 名分點：每日買賣超柱狀圖（張）")
            if not df_s_rank.empty:
                for idx, row in df_s_rank.head(5).iterrows():
                    s_name = row["分點名稱"]
                    s_sys = f" [{row['體系']}]" if row["體系"] == "八大官股" else ""
                    s_tot = row["買賣超(張)"]
                    df_daily = fetch_single_broker_daily_series(row["明細網址"], s_range_str, e_range_str)
                    if not df_daily.empty:
                        plot_broker_daily_bar(
                            df_daily,
                            f"賣超 Top {idx + 1}：{s_name}{s_sys}（區間累計：{s_tot:,} 張）"
                        )
                    else:
                        st.caption(f"賣超 Top {idx + 1}：{s_name} 無逐日明細資料。")
                    time.sleep(0.25)
