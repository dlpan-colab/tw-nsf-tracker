"""
模組名稱：chart_builder.py
版本識別：20261109_2238
修改目的：
1. 更新版本識別為 20261109_2235。
2. 增設均線系統：計算半年線（120MA）、年線（240MA）、五年線（1200MA）、十年線（2400MA），疊加於 K 線主圖。
3. 均線設定 hoverinfo="none"，避免游標懸浮產生干擾。
4. 維持 X 軸月度首日刻度標籤與 Y 軸極值動態計算。
防呆防錯原因：
1. 對於歷史資料長度不足計算五年線或十年線的部分，dropna 自然跳過，不引發繪圖例外。
"""

MODULE_VERSION = "20261109_2238"

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
        vertical_spacing=0.04,
        subplot_titles=("加權指數 (^TWII) 日K線走勢 與 長期均線", "成交量 與 政策事件標記 (▲/▼)"),
        row_heights=[0.72, 0.28]
    )

    total_bars = len(df_market)
    if total_bars == 0:
        return fig

    # 數值型別防呆轉換
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df_market.columns:
            df_market[col] = pd.to_numeric(df_market[col], errors="coerce")

    # 計算各長週期均線
    df_market["MA120"] = df_market["Close"].rolling(window=120).mean()
    df_market["MA240"] = df_market["Close"].rolling(window=240).mean()
    df_market["MA1200"] = df_market["Close"].rolling(window=1200).mean()
    df_market["MA2400"] = df_market["Close"].rolling(window=2400).mean()

    # 1. 計算切片整數索引界限
    if target_date_idx is None or target_date_idx >= total_bars:
        end_idx = total_bars - 1
        start_idx = max(0, end_idx - int(display_bars) + 1)
    else:
        half = int(display_bars) // 2
        start_idx = max(0, int(target_date_idx) - half)
        end_idx = min(total_bars - 1, start_idx + int(display_bars) - 1)
        start_idx = max(0, end_idx - int(display_bars) + 1)

    # 2. 自適應 Y 軸初始極值計算
    visible_slice = df_market.iloc[start_idx : end_idx + 1]
    if not visible_slice.empty:
        valid_low = visible_slice["Low"].dropna()
        valid_high = visible_slice["High"].dropna()
        valid_vol = visible_slice["Volume"].dropna()
        if not valid_low.empty and not valid_high.empty:
            y_min = float(valid_low.min())
            y_max = float(valid_high.max())
            y_pad = (y_max - y_min) * 0.05 if y_max > y_min else 100.0
            price_y_range = [y_min - y_pad, y_max + y_pad]
        else:
            price_y_range = None
            
        max_v = float(valid_vol.max()) if not valid_vol.empty else 0
        vol_y_range = [0, max_v * 1.25] if max_v > 0 else None
    else:
        price_y_range = None
        vol_y_range = None

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
            decreasing_line_color="#2ECC71",
            hoverinfo="none",
            hovertemplate=None
        ),
        row=1, col=1
    )

    # 3-1. 疊加均線系統
    ma_configs = [
        ("MA120", "半年線(120MA)", "#E67E22", 1.2),
        ("MA240", "年線(240MA)", "#3498DB", 1.4),
        ("MA1200", "五年線(1200MA)", "#9B59B6", 1.6),
        ("MA2400", "十年線(2400MA)", "#1ABC9C", 1.8),
    ]
    for col_name, ma_label, color, line_w in ma_configs:
        if col_name in df_market.columns and not df_market[col_name].dropna().empty:
            fig.add_trace(
                go.Scatter(
                    x=df_market["Date"],
                    y=df_market[col_name],
                    mode="lines",
                    line=dict(color=color, width=line_w),
                    name=ma_label,
                    hoverinfo="none",
                    hovertemplate=None
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
            opacity=0.65,
            hoverinfo="none",
            hovertemplate=None
        ),
        row=2, col=1
    )

    # 5. 疊加政策標記
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
                            size=14,
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

    # 6. 計算月份首日刻度（僅在每月首個交易日標註月份）
    month_tick_vals = []
    month_tick_texts = []
    prev_month = ""
    for idx, d_str in enumerate(df_market["Date"]):
        m_str = d_str[:7]
        if m_str != prev_month:
            month_tick_vals.append(d_str)
            month_tick_texts.append(m_str[5:7] + "月")
            prev_month = m_str

    # 7. 全域佈局
    fig.update_layout(
        dragmode="pan",
        hovermode="x unified",
        height=540,
        margin=dict(l=35, r=15, t=25, b=25),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    if price_y_range:
        fig.update_yaxes(range=price_y_range, fixedrange=True, row=1, col=1)
    else:
        fig.update_yaxes(fixedrange=True, row=1, col=1)

    if vol_y_range:
        fig.update_yaxes(range=vol_y_range, fixedrange=True, row=2, col=1)
    else:
        fig.update_yaxes(fixedrange=True, row=2, col=1)

    x_bounds = [start_idx - 0.5, end_idx + 0.5]
    
    fig.update_xaxes(
        type="category",
        range=x_bounds,
        fixedrange=False,
        showticklabels=False,
        row=1, col=1
    )
    fig.update_xaxes(
        type="category",
        range=x_bounds,
        fixedrange=False,
        tickmode="array",
        tickvals=month_tick_vals,
        ticktext=month_tick_texts,
        row=2, col=1
    )
    
    return fig
