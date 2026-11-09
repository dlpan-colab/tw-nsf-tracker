"""
模組名稱：chart_builder.py
版本識別：20261109_1348
修改目的：
1. 更新版本識別為 20261109_1348。
2. 徹底根除灰色遮罩與白色手柄：
   - 在 go.Candlestick 與 layout 所有軸層面徹底撲滅 rangeslider。
3. 確保單手指（滑鼠）直接平移 X 軸（dragmode="pan"）。
4. 鎖定 Y 軸絕對固定（fixedrange=True），禁止上下滑動。
5. 預設最新交易日對齊最右邊界，不留空白。
防呆防錯原因：
1. Plotly 的 Candlestick 預設自帶 rangeslider，必須在 update_layout 與 update_xaxes 雙重關閉，否則手機觸控會誤觸拉桿導致全圖反灰。
2. 數值欄位強制轉換 float，排除空值與型別衝突。
"""

MODULE_VERSION = "20261109_1348"

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

def build_taiex_chart(
    df_market: pd.DataFrame,
    df_events: pd.DataFrame,
    display_bars: int = 30,
    target_date_idx: int = None
) -> go.Figure:
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=("加權指數 (^TWII) 日K線走勢", "成交量 與 政策事件標記 (▲/▼)"),
        row_heights=[0.7, 0.3]
    )

    total_bars = len(df_market)
    if total_bars == 0:
        return fig

    # 數值型別防呆轉換
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df_market.columns:
            df_market[col] = pd.to_numeric(df_market[col], errors="coerce")

    # 1. 計算切片整數索引界限
    if target_date_idx is None or target_date_idx >= total_bars:
        end_idx = total_bars - 1
        start_idx = max(0, end_idx - int(display_bars) + 1)
    else:
        half = int(display_bars) // 2
        start_idx = max(0, int(target_date_idx) - half)
        end_idx = min(total_bars - 1, start_idx + int(display_bars) - 1)
        start_idx = max(0, end_idx - int(display_bars) + 1)

    # 2. 自適應 Y 軸極值
    visible_slice = df_market.iloc[start_idx : end_idx + 1]
    if not visible_slice.empty:
        valid_low = visible_slice["Low"].dropna()
        valid_high = visible_slice["High"].dropna()
        if not valid_low.empty and not valid_high.empty:
            y_min = float(valid_low.min())
            y_max = float(valid_high.max())
            y_pad = (y_max - y_min) * 0.05 if y_max > y_min else 100.0
            price_y_range = [y_min - y_pad, y_max + y_pad]
        else:
            price_y_range = None
    else:
        price_y_range = None

    # 3. 繪製 K 線主圖
    fig.add_trace(
        go.Candlestick(
            x=df_market["Date"],
            open=df_market["Open"],
            high=df_market["High"],
            low=df_market["Low"],
            close=df_market["Close"],
            name="加權指數",
            increasing_line_color="#E74C3C",
            decreasing_line_color="#2ECC71"
        ),
        row=1, col=1
    )

    # 4. 繪製成交量副圖
    vol_colors = [
        "#E74C3C" if r["Close"] >= r["Open"] else "#2ECC71"
        for _, r in df_market.iterrows()
    ]
    
    fig.add_trace(
        go.Bar(
            x=df_market["Date"],
            y=df_market["Volume"],
            marker_color=vol_colors,
            name="成交量",
            opacity=0.65
        ),
        row=2, col=1
    )

    # 5. 政策標記
    if not df_events.empty and "Date" in df_events.columns and "Date" in df_market.columns:
        merged = pd.merge(df_events, df_market[["Date", "Volume"]], on="Date", how="inner")
        
        if not merged.empty:
            for _, event in merged.iterrows():
                val_vol = float(event["Volume"]) if pd.notnull(event["Volume"]) else 0
                marker_y = val_vol * 1.08 if val_vol > 0 else 500000000

                fig.add_trace(
                    go.Scatter(
                        x=[event["Date"]],
                        y=[marker_y],
                        mode="markers+text",
                        marker=dict(
                            symbol=event["marker"],
                            size=15,
                            color=event["color"],
                            line=dict(width=1.5, color="#1C2833")
                        ),
                        text=[event["name"]],
                        textposition="top center",
                        textfont=dict(size=10, color="#1C2833"),
                        name=event["name"],
                        hovertext=[f"日期: {event['Date']}<br>事件: {event['name']}<br>說明: {event['description']}"],
                        hoverinfo="text",
                        showlegend=False
                    ),
                    row=2, col=1
                )

    # 6. 配置座標軸與手勢控制（徹底根治遮罩拉桿）
    fig.update_layout(
        dragmode="pan",                    # 鎖定單指/滑鼠為平移
        xaxis_rangeslider_visible=False,   # 徹底關閉 X 軸 rangeslider
        height=720,
        margin=dict(l=40, r=20, t=30, b=30),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    # 鎖定 Y 軸不隨平移上下位移 (fixedrange=True)
    if price_y_range:
        fig.update_yaxes(range=price_y_range, fixedrange=True, row=1, col=1)
    else:
        fig.update_yaxes(fixedrange=True, row=1, col=1)

    fig.update_yaxes(fixedrange=True, row=2, col=1)

    # 設定 X 軸起訖日期與徹底關閉任何子軸的 rangeslider
    start_date_str = str(df_market.iloc[start_idx]["Date"])
    end_date_str = str(df_market.iloc[end_idx]["Date"])

    # 全局覆蓋所有 xaxes 關閉 rangeslider 並啟用 rangebreaks
    fig.update_xaxes(
        type="date",
        range=[start_date_str, end_date_str],
        fixedrange=False,                 # 允許 X 軸平移
        rangeslider=dict(visible=False),  # 防呆防錯：雙重確保 rangeslider 徹底隱藏
        rangebreaks=[dict(bounds=["sat", "mon"])]
    )
    
    return fig
