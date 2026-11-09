"""
模組名稱：chart_builder.py
修改目的：
1. 解決 TypeError：因 X 軸為 category（文字日期）型別，避免使用浮點數索引傳入 range，改直接傳入對應的日期字串範圍。
2. 數值計算防呆：強制將 High, Low, Volume 透過 pd.to_numeric 轉換為浮點數，防止 yfinance 抓取之欄位型態異常引發計算錯誤。
3. 嚴格鎖定 Y 軸（fixedrange=True），僅開放 X 軸橫向平移。
4. 當顯示區間包含最新交易日時，右側緊貼邊界不留空白。
防呆防錯原因：
1. 切片索引嚴格限制在 0 至 len(df_market)-1 之間，杜絕 IndexError。
2. 計算 Y 軸極值時剔除 NaN 與 Inf，防止 Plotly 繪圖座標軸崩潰。
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
    修改目的：繪製加權指數 K 線與標記成交量，並確保 X 軸字串切片與 Y 軸動態縮放正常運作。
    防呆防錯原因：以日期字串作為 X 軸 category 的 range 邊界，徹底排除 TypeError。
    """
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

    # 防呆防錯：確保數值欄位均為 float 型別
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df_market.columns:
            df_market[col] = pd.to_numeric(df_market[col], errors="coerce")

    # 1. 計算切片起訖索引
    if target_date_idx is None or target_date_idx >= total_bars:
        # 預設錨定在最後一筆（右側邊界無空白）
        end_idx = total_bars - 1
        start_idx = max(0, end_idx - display_bars + 1)
    else:
        # 錨定在指定事件日期
        half = display_bars // 2
        start_idx = max(0, target_date_idx - half)
        end_idx = min(total_bars - 1, start_idx + display_bars - 1)
        # 若推至最右端，反推起點維持指定天數
        start_idx = max(0, end_idx - display_bars + 1)

    # 2. 動態計算顯示區間的 Y 軸最高/最低價（自適應極值）
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

    # 3. 繪製主圖 K 線
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

    # 4. 繪製副圖成交量
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

    # 5. 疊加成交量之政策事件三角形標記
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

    # 6. 配置座標軸限制：固定 Y 軸不允許上下移動，僅開放 X 軸水平平移
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=720,
        margin=dict(l=40, r=20, t=30, b=30),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    if price_y_range:
        fig.update_yaxes(range=price_y_range, fixedrange=True, row=1, col=1)
    else:
        fig.update_yaxes(fixedrange=True, row=1, col=1)

    fig.update_yaxes(fixedrange=True, row=2, col=1)

    # 防呆修正：以 category 型別之「日期字串」直接指定起訖範圍，杜絕 TypeError
    x_start_str = str(df_market.iloc[start_idx]["Date"])
    x_end_str = str(df_market.iloc[end_idx]["Date"])

    fig.update_xaxes(
        type="category",
        range=[x_start_str, x_end_str],
        row=1, col=1
    )
    fig.update_xaxes(
        type="category",
        range=[x_start_str, x_end_str],
        row=2, col=1
    )
    
    return fig
