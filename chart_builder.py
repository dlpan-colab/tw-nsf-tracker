"""
模組名稱：chart_builder.py
版本識別：20261109_2155
修改目的：
1. 更新版本識別為 20261109_2155。
2. X 軸月份標籤最佳化：遍歷交易日清單，僅在每月首個交易日標註月份名稱（tickvals 與 ticktext），保持軸刻度簡潔。
3. 高度由 720px 縮減至 540px，搭配自適應間距，實現手機一屏容納。
4. 副圖成交量座標鎖定與自適應初始計算，預留合理比例消除空白。
5. 取消所有浮動標籤（hoverinfo="none"），行情數值由上方固定資訊條統一承載。
防呆防錯原因：
1. 建立月份切換標記時，比對相鄰日期的 YYYY-MM，確保每年每月第一個交易日精準命中。
2. 價量欄位全部使用 pd.to_numeric 清洗，避免空值造成序列化錯誤。
"""

MODULE_VERSION = "20261109_2155"

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
        subplot_titles=("加權指數 (^TWII) 日K線走勢", "成交量 與 政策事件標記 (▲/▼)"),
        row_heights=[0.72, 0.28]
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
        m_str = d_str[:7] # YYYY-MM
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

    # 鎖定 Y 軸（交由前端動態自適應）
    if price_y_range:
        fig.update_yaxes(range=price_y_range, fixedrange=True, row=1, col=1)
    else:
        fig.update_yaxes(fixedrange=True, row=1, col=1)

    if vol_y_range:
        fig.update_yaxes(range=vol_y_range, fixedrange=True, row=2, col=1)
    else:
        fig.update_yaxes(fixedrange=True, row=2, col=1)

    # 設定 X 軸 category 類型與刻度
    x_bounds = [start_idx - 0.5, end_idx + 0.5]
    
    # 主圖 X 軸隱藏刻度文字
    fig.update_xaxes(
        type="category",
        range=x_bounds,
        fixedrange=False,
        showticklabels=False,
        row=1, col=1
    )
    # 副圖 X 軸僅呈現每月首個交易日之月份
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
