"""
模組名稱：app.py
修改目的：Streamlit 應用程式進入點，提供介面篩選標的、時間區間與渲染圖表。
防呆防錯原因：
1. 檢查使用者輸入之起訖日期，起始日若大於結束日則提供警示並阻斷查詢。
2. 針對空數據結果提供友善提示，避免後續繪圖拋出 IndexError。
"""

import streamlit as st
import datetime
from data_loader import load_policy_events, fetch_market_data
from chart_builder import build_price_volume_chart

# 頁面配置
st.set_page_config(
    page_title="國安基金動向預判與政策事件標記系統",
    layout="wide"
)

st.title("國安基金動向預判與政策標記 (tw-nsf-tracker)")

# 側邊欄控制項
st.sidebar.header("查詢條件設定")

# 常用權值與大盤清單
TARGET_OPTIONS = {
    "加權指數 (^TWII)": "^TWII",
    "台積電 (2330.TW)": "2330.TW",
    "聯發科 (2454.TW)": "2454.TW",
    "鴻海 (2317.TW)": "2317.TW",
    "台達電 (2308.TW)": "2308.TW",
    "富邦金 (2881.TW)": "2881.TW",
    "國泰金 (2882.TW)": "2882.TW"
}

selected_label = st.sidebar.selectbox("分析標的", list(TARGET_OPTIONS.keys()))
selected_ticker = TARGET_OPTIONS[selected_label]

start_default = datetime.date(2022, 1, 1)
end_default = datetime.date.today()

col_start, col_end = st.sidebar.columns(2)
start_date = col_start.date_input("開始日期", start_default)
end_date = col_end.date_input("結束日期", end_default)

# 防呆防錯：日期有效性驗證
if start_date > end_date:
    st.sidebar.error("開始日期不能晚於結束日期！")
    st.stop()

# 載入政策事件
events_df = load_policy_events("policy_events.json")

# 呈現圖例說明
st.markdown("""
**成交量標記圖例說明：**
* :red[▲ 紅色正三角]：國安基金管理委員會授權進場
* :orange[▲ 黃色正三角]：金管會發布限空令
* :green[▼ 綠色倒三角]：國安基金管理委員會解除授權（退場）
* :blue[▼ 藍色倒三角]：金管會解除限空令
""")

# 讀取行情並渲染圖表
with st.spinner("資料載入中..."):
    market_df = fetch_market_data(
        selected_ticker,
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d")
    )

if market_df.empty:
    st.warning(f"查無 {selected_label} 於指定區間的市場數據，請確認連線或調整日期。")
else:
    fig = build_price_volume_chart(market_df, events_df, selected_label)
    st.plotly_chart(fig, use_container_width=True)

# 顯示所選區間內已記錄之政策事件清單
st.subheader("區間內政策事件明細")
if not events_df.empty:
    filtered_events = events_df[
        (events_df["date"] >= start_date.strftime("%Y-%m-%d")) &
        (events_df["date"] <= end_date.strftime("%Y-%m-%d"))
    ]
    if not filtered_events.empty:
        st.dataframe(
            filtered_events[["date", "name", "description"]].rename(
                columns={"date": "發布日期", "name": "政策事件", "description": "事件說明"}
            ),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("所選時間區間內無國安基金或限空令相關事件。")
