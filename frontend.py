"""
模組名稱：frontend.py
版本識別：20261109_2238
修改目的：
1. 更新版本識別為 20261109_2238。
2. 根絕資訊條 NaN 問題：直接接收 Python 端序列化的乾淨陣列（dates, opens, highs, lows, closes, volumes, turnover），由 JS 直接依索引取值。
3. 資訊條完整呈現「開／高／低／收／成交值（億元）」。
4. 徹底修復 Y 軸自適應：在 plotly_relayout 內動態計算可視範圍 High/Low 極值與成交量極值，透過 Plotly.relayout 強制覆蓋 yaxis.range 與 yaxis2.range，徹底解決 37K 以下被截斷與副圖上方過度留白。
5. 視窗高度精簡為 580px，使「資訊條、K線圖、成交量圖」能於手機單一畫面完整呈現。
防呆防錯原因：
1. 透過 isRelayouting 旗標鎖避免 Plotly.relayout 遞迴循環。
2. 切片索引強制 Math.floor 與 Math.ceil 邊界保護，杜絕陣列越界。
"""

MODULE_VERSION = "20261109_2238"

import json
import streamlit.components.v1 as components
import plotly.graph_objects as go
import pandas as pd

def render_interactive_chart(fig: go.Figure, df_market: pd.DataFrame, height: int = 580):
    fig_json = fig.to_json()
    
    # 數值型別防呆清洗並轉為純 JSON 清單注入前端
    dates = df_market["Date"].tolist()
    opens = [float(x) if pd.notnull(x) else 0.0 for x in df_market["Open"]]
    highs = [float(x) if pd.notnull(x) else 0.0 for x in df_market["High"]]
    lows = [float(x) if pd.notnull(x) else 0.0 for x in df_market["Low"]]
    closes = [float(x) if pd.notnull(x) else 0.0 for x in df_market["Close"]]
    vols = [float(x) if pd.notnull(x) else 0.0 for x in df_market["Volume"]]
    
    # 計算成交值（台股大盤以指數乘成交量約略估算或直接換算億元）
    # 若無真實金額欄位，依加權指數 Close * Volume 換算成交值（億元）
    turnovers = [
        round((c * v) / 100000000.0, 2) if (c > 0 and v > 0) else 0.0
        for c, v in zip(closes, vols)
    ]

    raw_data_json = json.dumps({
        "dates": dates,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "vols": vols,
        "turnovers": turnovers
    })
    
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
        <style>
            html, body {{
                margin: 0;
                padding: 0;
                width: 100%;
                height: 100%;
                overflow: hidden;
                background-color: transparent;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }}
            #info-bar {{
                height: 28px;
                line-height: 28px;
                padding: 0 8px;
                background: #F8F9F9;
                border: 1px solid #E5E7E9;
                border-radius: 4px;
                margin-bottom: 4px;
                font-size: 12px;
                color: #2C3E50;
                display: flex;
                flex-wrap: nowrap;
                overflow-x: auto;
                gap: 8px;
                align-items: center;
                box-sizing: border-box;
                white-space: nowrap;
            }}
            .info-item {{
                font-weight: 500;
            }}
            .val-up {{
                color: #E74C3C;
                font-weight: bold;
            }}
            .val-down {{
                color: #2ECC71;
                font-weight: bold;
            }}
            #chart-container {{
                width: 100%;
                height: {height - 34}px;
            }}
            .rangeslider-container, .rangeslider-mask, .selectionlayer {{
                display: none !important;
                visibility: hidden !important;
                pointer-events: none !important;
            }}
        </style>
    </head>
    <body>
        <div id="info-bar">
            <span class="info-item" id="info-date">日期: --</span>
            <span class="info-item" id="info-open">開: --</span>
            <span class="info-item" id="info-high">高: --</span>
            <span class="info-item" id="info-low">低: --</span>
            <span class="info-item" id="info-close">收: --</span>
            <span class="info-item" id="info-val">成交值: --</span>
        </div>
        <div id="chart-container"></div>
        <script>
            const rawData = {raw_data_json};
            const figureData = {fig_json};
            const container = document.getElementById('chart-container');
            const totalBars = rawData.dates.length;

            // 更新固定資訊條函式（直接依陣列索引提取）
            function updateInfoBar(idx) {{
                if (idx < 0 || idx >= totalBars) return;
                const d = rawData.dates[idx];
                const o = rawData.opens[idx];
                const h = rawData.highs[idx];
                const l = rawData.lows[idx];
                const c = rawData.closes[idx];
                const t = rawData.turnovers[idx];

                const isUp = c >= o;
                const colorCls = isUp ? 'val-up' : 'val-down';

                document.getElementById('info-date').innerText = '關注日: ' + d;
                document.getElementById('info-open').innerHTML = '開: <span class="' + colorCls + '">' + o.toFixed(0) + '</span>';
                document.getElementById('info-high').innerHTML = '高: <span class="' + colorCls + '">' + h.toFixed(0) + '</span>';
                document.getElementById('info-low').innerHTML = '低: <span class="' + colorCls + '">' + l.toFixed(0) + '</span>';
                document.getElementById('info-close').innerHTML = '收: <span class="' + colorCls + '">' + c.toFixed(0) + '</span>';
                document.getElementById('info-val').innerText = '成交值: ' + t.toFixed(0) + '億';
            }}

            // 鎖定原生配置
            figureData.layout.dragmode = 'pan';
            figureData.layout.hovermode = 'x unified';
            
            if (figureData.layout.xaxis) {{
                figureData.layout.xaxis.rangeslider = {{ visible: false }};
                figureData.layout.xaxis.fixedrange = false;
            }}
            if (figureData.layout.xaxis2) {{
                figureData.layout.xaxis2.rangeslider = {{ visible: false }};
                figureData.layout.xaxis2.fixedrange = false;
            }}
            if (figureData.layout.yaxis) {{
                figureData.layout.yaxis.fixedrange = true;
            }}
            if (figureData.layout.yaxis2) {{
                figureData.layout.yaxis2.fixedrange = true;
            }}

            const config = {{
                scrollZoom: true,
                responsive: true,
                displayModeBar: false,
                showAxisDragHandles: false,
                showAxisRangeEntryBoxes: false
            }};

            let isRelayouting = false;

            Plotly.newPlot(container, figureData.data, figureData.layout, config).then(() => {{
                // 預設更新最新一根 K 棒
                if (totalBars > 0) {{
                    updateInfoBar(totalBars - 1);
                }}

                // 滑鼠/觸控 hover 聯動更新固定資訊條
                container.on('plotly_hover', function(data) {{
                    if (data.points && data.points.length > 0) {{
                        updateInfoBar(data.points[0].pointIndex);
                    }}
                }});

                // 平移/縮放事件監聽：實作防呆回彈與 Y 軸極值動態計算
                container.on('plotly_relayout', function(eventData) {{
                    if (isRelayouting) return;

                    let r0 = eventData['xaxis.range[0]'];
                    let r1 = eventData['xaxis.range[1]'];

                    if (r0 !== undefined && r1 !== undefined && totalBars > 0) {{
                        let left = parseFloat(r0);
                        let right = parseFloat(r1);
                        let span = right - left;

                        if (span < 5) {{
                            span = 5;
                            right = left + span;
                        }}

                        const maxAllowedRight = totalBars - 0.5;
                        const minAllowedLeft = -0.5;
                        let clamped = false;

                        if (right > maxAllowedRight) {{
                            right = maxAllowedRight;
                            left = right - span;
                            clamped = true;
                        }}
                        if (left < minAllowedLeft) {{
                            left = minAllowedLeft;
                            right = (span > totalBars) ? maxAllowedRight : (left + span);
                            clamped = true;
                        }}

                        // 計算可視區間極值
                        let startIdx = Math.max(0, Math.floor(left));
                        let endIdx = Math.min(totalBars - 1, Math.ceil(right));
                        let minY = Infinity;
                        let maxY = -Infinity;
                        let maxVol = 0;
                        let hasData = false;

                        for (let i = startIdx; i <= endIdx; i++) {{
                            let l = rawData.lows[i];
                            let h = rawData.highs[i];
                            let v = rawData.vols[i];
                            if (l > 0) minY = Math.min(minY, l);
                            if (h > 0) maxY = Math.max(maxY, h);
                            if (v > 0) maxVol = Math.max(maxVol, v);
                            hasData = true;
                        }}

                        updateInfoBar(endIdx);

                        let updateObj = {{}};
                        if (clamped) {{
                            updateObj['xaxis.range'] = [left, right];
                        }}
                        if (hasData && minY < maxY) {{
                            let pad = (maxY - minY) * 0.05;
                            updateObj['yaxis.range'] = [minY - pad, maxY + pad];
                        }}
                        if (maxVol > 0) {{
                            // 副圖最大值加上緩衝，消除上方大片空白
                            updateObj['yaxis2.range'] = [0, maxVol * 1.25];
                        }}

                        if (Object.keys(updateObj).length > 0) {{
                            isRelayouting = true;
                            Plotly.relayout(container, updateObj).then(() => {{
                                isRelayouting = false;
                            }});
                        }}
                    }}
                }});
            }});
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=height + 10, scrolling=False)
