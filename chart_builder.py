"""
模組名稱：chart_builder.py
修改目的：
1. 實作 K 線預設顯示 N 日與 X 軸可視範圍控制。
2. 鎖定 Y 軸禁止上下拖曳（fixedrange=True），僅保留 X 軸橫向平移能力。
3. 根據目前可視範圍切片動態計算 High 最高值與 Low 最低值，自適應設定 Y 軸範圍。
4. 當包含最後一個交易日時，X 軸右側範圍精確對齊最新索引，避免右側留白。
防呆防錯原因：
1. 當使用者選擇的天數大於現有資料長度時，自動取現有資料上限，避免切片 IndexError。
2. 計算 Y 軸極值時過濾空值與 NaN，防止繪圖引擎報錯或座標軸尺度歸零。
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

def build_taiex_chart(
    df_market: pd.DataFrame,
    df_events: pd.DataFrame,
    display_bars: int = 30,
    target_date_idx: int = None
) -> go.Figure:
    """
    修改目的：建立具備右邊界對齊、Y軸鎖定、自適應高低點的加權指數價量互動圖。
    防呆防錯原因：
    - 若 target_date_idx 未指定，預設以最新資料為右端基準。
    - 嚴格校驗切片起訖索引界限（0 到總長度減 1）。
    """
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=("加權指數 (^TWII) 日K線走勢", "成交量 與 政策事件標記"),
        row_heights=[0.7, 0.3]
    )

    total_bars = len(df_market)
    if total_bars == 0:
        return fig

    # 1. 計算 X 軸顯示起訖索引與右邊際防呆
    if target_date_idx is None or target_date_idx >= total_bars:
        # 預設錨定在最新一筆（最右側貼齊邊界，右側無空白）
        end_idx = total_bars - 1
        start_idx = max(0, end_idx - display_bars + 1)
    else:
        # 錨定在指定事件日期（以事件日為中心或合理視角）
        half = display_bars // 2
        start_idx = max(0, target_date_idx - half)
        end_idx = min(total_bars - 1, start_idx + display_bars - 1)
        # 若右側推到底，往左反推以維持 display_bars 寬度
        start_idx = max(0, end_idx - display_bars + 1)

    # 2. 計算顯示區間內 Y 軸之最大值與最小值（自適應縮放）
    visible_slice = df_market.iloc[start_idx : end_idx + 1]
    if not visible_slice.empty:
        y_min = float(visible_slice["Low"].min())
        y_max = float(visible_slice["High"].max())
        y_padding = (y_max - y_min) * 0.05 if y_max > y_min else 100
        price_y_range = [y_min - y_padding, y_max + y_padding]
    else:
        price_y_range = None

    # 3. 繪製主圖：K 線
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

    # 4. 繪製副圖：成交量柱狀圖
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

    # 5. 疊加成交量之政策事件標記
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

    # 6. 配置座標軸限制：鎖定 Y 軸，僅允許 X 軸平移
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=720,
        margin=dict(l=40, r=20, t=30, b=30),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    # 主圖 Y 軸設定：禁止拖曳平移 (fixedrange=True) 並動態指定視圖區間範圍
    if price_y_range:
        fig.update_yaxes(range=price_y_range, fixedrange=True, row=1, col=1)
    else:
        fig.update_yaxes(fixedrange=True, row=1, col=1)

    # 副圖成交量 Y 軸亦鎖定
    fig.update_yaxes(fixedrange=True, row=2, col=1)

    # X 軸範圍鎖定：對齊類別型別，設定初始顯示區間範圍
    start_date_str = df_market.iloc[start_idx]["Date"]
    end_date_str = df_market.iloc[end_idx]["Date"]
    
    fig.update_xaxes(
        type="category",
        range=[start_idx - 0.5, end_idx + 0.5],  # 精確邊界對齊，右邊不留白
        row=1, col=1
    )
    fig.update_xaxes(
        type="category",
        range=[start_idx - 0.5, end_idx + 0.5],
        row=2, col=1
    )
    
    return fig
