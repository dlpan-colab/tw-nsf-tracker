"""
模組名稱：modules/chart_builder.py
修改目的：使用 Plotly 繪製雙面板互動價量圖，並在成交量軸疊加四種政策三角形標記。
防呆防錯原因：
1. 嚴格對齊日期軸，成交量與標記必須錨定在同一天成交量頂端。
2. 標記座標（y 軸）計算使用量能動態偏移量，避免三角形遭柱狀圖遮蔽或貼底。
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

def build_price_volume_chart(df_market: pd.DataFrame, df_events: pd.DataFrame, title: str) -> go.Figure:
    """
    修改目的：組裝包含 K 線、成交量柱狀圖與政策事件三角形之互動圖表。
    防呆防錯原因：
    1. 使用 make_subplots 分割列高（主圖價 70%、副圖量 30%），且共用 x 軸避免縮放不同步。
    2. 檢查 df_events 與 df_market 日期交集，僅繪製在可見區間內的事件標記，防止坐標軸異常拉伸。
    """
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=(f"{title} 價格走勢", "成交量與政策事件標記"),
        row_heights=[0.7, 0.3]
    )

    # 1. 繪製主圖 K 線
    fig.add_trace(
        go.Candlestick(
            x=df_market["Date"],
            open=df_market["Open"],
            high=df_market["High"],
            low=df_market["Low"],
            close=df_market["Close"],
            name="K線",
            increasing_line_color="#E74C3C",  # 台股紅漲
            decreasing_line_color="#2ECC71"   # 台股綠跌
        ),
        row=1, col=1
    )

    # 2. 繪製副圖成交量柱狀圖
    # 防呆計算：依漲跌幅區分成交量顏色
    colors = [
        "#E74C3C" if row["Close"] >= row["Open"] else "#2ECC71"
        for _, row in df_market.iterrows()
    ]
    
    fig.add_trace(
        go.Bar(
            x=df_market["Date"],
            y=df_market["Volume"],
            marker_color=colors,
            name="成交量",
            opacity=0.6
        ),
        row=2, col=1
    )

    # 3. 疊加成交量之政策事件三角形標記
    if not df_events.empty:
        # 將事件與市場資料日期對齊
        merged = pd.merge(df_events, df_market[["Date", "Volume"]], on="Date", how="inner")
        
        if not merged.empty:
            for _, event in merged.iterrows():
                # 防呆防錯：計算標記放置位置，置於當日成交量柱頂部並預留 5% 緩衝高度
                marker_y = event["Volume"] * 1.05 if event["Volume"] > 0 else 1000
                
                fig.add_trace(
                    go.Scatter(
                        x=[event["Date"]],
                        y=[marker_y],
                        mode="markers+text",
                        marker=dict(
                            symbol=event["marker"],
                            size=14,
                            color=event["color"],
                            line=dict(width=1, color="black")
                        ),
                        text=[event["name"]],
                        textposition="top center",
                        name=event["name"],
                        hovertext=[f"日期: {event['Date']}<br>事件: {event['name']}<br>說明: {event['description']}"],
                        hoverinfo="text",
                        showlegend=False
                    ),
                    row=2, col=1
                )

    # 圖表排版與防破版樣式調整
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=750,
        margin=dict(l=40, r=40, t=50, b=40),
        hovermode="x unified"
    )
    
    fig.update_xaxes(type="category")  # 防呆防錯：使用 category 排除台股非交易日（週末假日）空白間隔
    return fig
