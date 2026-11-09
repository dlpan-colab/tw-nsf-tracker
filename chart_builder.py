"""
模組名稱：chart_builder.py
修改目的：
1. 繪製加權指數 K 線與成交量整合圖。
2. 修正 KeyError：確保以一致的 'Date' 欄位進行 merge。
3. 於成交量頂端疊加國安基金授權/退場（紅/綠）與限空令實施/解除（黃/藍）三角形標記。
防呆防錯原因：
1. 嚴格檢查 df_events 是否含有 'Date' 欄位，若缺失則略過標記疊加，確保主圖正常顯示。
2. 標記座標（y 軸）以當日成交量（Volume）加成 8% 繪製，避免三角形標記遮蔽成交量柱體。
3. 使用 category 型別 x 軸，排除週末非交易日空檔。
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

def build_taiex_chart(df_market: pd.DataFrame, df_events: pd.DataFrame) -> go.Figure:
    """
    修改目的：建立加權指數 K 線與標記成交量主副圖。
    防呆防錯原因：
    - 合併時強制確認鍵值名稱為 'Date'。
    - 採用 inner join 僅繪製落在當前顯示時間軸內的事件，防坐標軸被極端歷史日期拉爆。
    """
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        subplot_titles=("加權指數 (^TWII) 日K線走勢", "當日成交量 與 政策事件標記 (▲/▼)"),
        row_heights=[0.68, 0.32]
    )

    # 1. 主圖：加權指數 K 線
    fig.add_trace(
        go.Candlestick(
            x=df_market["Date"],
            open=df_market["Open"],
            high=df_market["High"],
            low=df_market["Low"],
            close=df_market["Close"],
            name="加權指數",
            increasing_line_color="#E74C3C",  # 台股紅漲
            decreasing_line_color="#2ECC71"   # 台股綠跌
        ),
        row=1, col=1
    )

    # 2. 副圖：成交量柱狀圖
    vol_colors = [
        "#E74C3C" if row["Close"] >= row["Open"] else "#2ECC71"
        for _, row in df_market.iterrows()
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

    # 3. 疊加成交量之政策事件標記（防呆對齊）
    if not df_events.empty and "Date" in df_events.columns and "Date" in df_market.columns:
        merged = pd.merge(df_events, df_market[["Date", "Volume"]], on="Date", how="inner")
        
        if not merged.empty:
            for _, event in merged.iterrows():
                # 防呆計算：將三角形標記浮貼於成交量柱頂部 8% 處
                val_vol = float(event["Volume"]) if pd.notnull(event["Volume"]) else 0
                marker_y = val_vol * 1.08 if val_vol > 0 else 500000000

                fig.add_trace(
                    go.Scatter(
                        x=[event["Date"]],
                        y=[marker_y],
                        mode="markers+text",
                        marker=dict(
                            symbol=event["marker"],
                            size=16,
                            color=event["color"],
                            line=dict(width=1.5, color="#1C2833")
                        ),
                        text=[event["name"]],
                        textposition="top center",
                        textfont=dict(size=11, color="#1C2833"),
                        name=event["name"],
                        hovertext=[f"日期: {event['Date']}<br>事件: {event['name']}<br>內容: {event['description']}"],
                        hoverinfo="text",
                        showlegend=False
                    ),
                    row=2, col=1
                )

    # 圖表整體佈局微調
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=720,
        margin=dict(l=40, r=40, t=40, b=30),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    # 排除非交易日斷層
    fig.update_xaxes(type="category")
    return fig
