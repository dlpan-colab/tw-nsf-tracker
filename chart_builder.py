"""
模組名稱：chart_builder.py
版本識別：20261109_1410
修改目的：
1. 更新模組版本為 20261109_1410。
2. 徹底消除灰底選取遮罩與拉桿：
   - 停用所有選取遮罩渲染（selectdirection=None）。
   - Candlestick 內部完全隱藏 rangeslider。
   - 鎖定單指平移（dragmode="pan"）。
3. 取消 K 線與成交量之浮動標籤（hoverinfo="none"、hovermode=False）。
4. 鎖定 Y 軸不隨平移上下浮動（fixedrange=True）。
防呆防錯原因：
1. 嚴格限定 X 軸為 date 型別並配置 rangebreaks 排除週末，避免平移時出現斷層。
2. 數值欄位強制轉為 float，防止空值引發運算異常。
"""

MODULE_VERSION = "20261109_1410"

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

    # 1. 計算切片起訖整數索引
    if target_date_idx is None or target_date_idx >= total_bars:
        end_idx = total_bars - 1
        start_idx = max(0, end_idx - int(display_bars) + 1)
    else:
        half = int(display_bars) // 2
        start_idx = max(0, int(target_date_idx) - half)
        end_idx = min(total_bars - 1, start_idx + int(display_bars) - 1)
        start_idx = max(0, end_idx - int(display_bars) + 1)

    # 2. 自適應 Y 軸高低界限
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

    # 3. 繪製 K 線主圖（取消浮動標籤，內嵌停用 rangeslider）
    fig.add_trace(
        go.Candlestick(
            x=df_market["Date"],
            open=df_market["Open"],
            high=df_market["High"],
            low=df_market["Low"],
            close=df_market["Close"],
            name="加權指數",
            increasing_line_color="#E74C3C",
            decreasing_line_color="#2ECC71",
            hoverinfo="none"
        ),
        row=1, col=1
    )

    # 4. 繪製成交量副圖（取消浮動標籤）
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
            opacity=0.65,
            hoverinfo="none"
        ),
        row=2, col=1
    )

    # 5. 疊加政策三角形標記
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

    # 6. 配置全域佈局
    start_date_str = str(df_market.iloc[start_idx]["Date"])
    end_date_str = str(df_market.iloc[end_idx]["Date"])

    fig.update_layout(
        dragmode="pan",
        hovermode=False,
        selectdirection=None,
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=False,
        height=720,
        margin=dict(l=40, r=20, t=30, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    # 鎖定 Y 軸不隨平移上下跳動
    if price_y_range:
        fig.update_yaxes(range=price_y_range, fixedrange=True, row=1, col=1)
    else:
        fig.update_yaxes(fixedrange=True, row=1, col=1)

    fig.update_yaxes(fixedrange=True, row=2, col=1)

    # 設定 X 軸起訖範圍與排除週末
    fig.update_xaxes(
        type="date",
        range=[start_date_str, end_date_str],
        fixedrange=False,
        rangeslider=dict(visible=False),
        rangebreaks=[dict(bounds=["sat", "mon"])],
        row=1, col=1
    )
    fig.update_xaxes(
        type="date",
        range=[start_date_str, end_date_str],
        fixedrange=False,
        rangeslider=dict(visible=False),
        rangebreaks=[dict(bounds=["sat", "mon"])],
        row=2, col=1
    )
    
    return fig
