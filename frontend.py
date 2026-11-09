"""
模組名稱：frontend.py
版本識別：20261109_1535
修改目的：
1. 更新版本識別為 20261109_1535。
2. 新增固定資訊條區域（Info Bar）：
   - 在圖表正上方固定渲染行情指標列，動態呈現關注交易日之「日期、開盤、最高、最低、收盤、漲跌、成交量」。
   - 預設呈現當前可視區間最新一日，滑鼠/觸控滑過時即時更新。
3. 徹底修正 Y 軸自動等比縮放（Auto-Scale Y）：
   - 修正 Plotly.relayout 語法為 'yaxis.range': [minY, maxY]，解決 37K 以下 K 線被截斷的問題。
   - 同步修正成交量 Y 軸自適應 'yaxis2.range': [0, maxVol * 1.2]。
4. 維持平移邊界防呆回彈（Clamping），右端緊貼最新交易日。
防呆防錯原因：
1. Plotly.relayout 針對多子圖 Y 軸必須使用陣列鍵名 'yaxis.range'，傳入單一邊界屬性會被忽略導致 Y 軸凍結。
2. 數值計算加入 isNaN 與 null 防呆過濾，防止區間極值計算失誤。
"""

MODULE_VERSION = "20261109_1535"

import streamlit.components.v1 as components
import plotly.graph_objects as go

def render_interactive_chart(fig: go.Figure, height: int = 740):
    fig_json = fig.to_json()
    
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
            /* 【修改目的】：新增固定資訊條區域 */
            #info-bar {{
                height: 32px;
                line-height: 32px;
                padding: 0 12px;
                background: #F8F9F9;
                border: 1px solid #E5E7E9;
                border-radius: 4px;
                margin-bottom: 6px;
                font-size: 13px;
                color: #2C3E50;
                display: flex;
                flex-wrap: wrap;
                gap: 12px;
                align-items: center;
                box-sizing: border-box;
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
                height: {height - 40}px;
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
            <span class="info-item" id="info-date">關注日期: --</span>
            <span class="info-item" id="info-open">開: --</span>
            <span class="info-item" id="info-high">高: --</span>
            <span class="info-item" id="info-low">低: --</span>
            <span class="info-item" id="info-close">收: --</span>
            <span class="info-item" id="info-vol">量: --</span>
        </div>
        <div id="chart-container"></div>
        <script>
            const figureData = {fig_json};
            const container = document.getElementById('chart-container');
            const kTrace = figureData.data[0];
            const volTrace = figureData.data[1];
            const totalBars = kTrace ? kTrace.x.length : 0;

            // 更新固定資訊條函式
            function updateInfoBar(idx) {{
                if (!kTrace || idx < 0 || idx >= totalBars) return;
                const d = kTrace.x[idx];
                const o = kTrace.open[idx];
                const h = kTrace.high[idx];
                const l = kTrace.low[idx];
                const c = kTrace.close[idx];
                const v = volTrace && volTrace.y[idx] ? volTrace.y[idx] : 0;

                const isUp = c >= o;
                const colorCls = isUp ? 'val-up' : 'val-down';

                document.getElementById('info-date').innerText = '關注日期: ' + d;
                document.getElementById('info-open').innerHTML = '開: <span class="' + colorCls + '">' + Number(o).toFixed(0) + '</span>';
                document.getElementById('info-high').innerHTML = '高: <span class="' + colorCls + '">' + Number(h).toFixed(0) + '</span>';
                document.getElementById('info-low').innerHTML = '低: <span class="' + colorCls + '">' + Number(l).toFixed(0) + '</span>';
                document.getElementById('info-close').innerHTML = '收: <span class="' + colorCls + '">' + Number(c).toFixed(0) + '</span>';
                document.getElementById('info-vol').innerText = '量: ' + (v / 100000000).toFixed(2) + '億';
            }}

            // 確保 Layout 參數原生鎖定
            figureData.layout.dragmode = 'pan';
            figureData.layout.hovermode = 'x unified'; // 保留十字游標以聯動固定資訊條
            
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

            let isRelayouting = false; // 防呆鎖：避免遞迴調用

            Plotly.newPlot(container, figureData.data, figureData.layout, config).then(() => {{
                // 初始化固定資訊條顯示最新一根 K 棒
                if (totalBars > 0) {{
                    updateInfoBar(totalBars - 1);
                }}

                // 監聽滑鼠/觸控 hover 聯動更新固定資訊條
                container.on('plotly_hover', function(data) {{
                    if (data.points && data.points.length > 0) {{
                        updateInfoBar(data.points[0].pointIndex);
                    }}
                }});

                // 監聽平移與縮放，執行防呆回彈與 Y 軸自動等比縮放
                container.on('plotly_relayout', function(eventData) {{
                    if (isRelayouting) return;

                    let r0 = eventData['xaxis.range[0]'];
                    let r1 = eventData['xaxis.range[1]'];

                    if (r0 !== undefined && r1 !== undefined && kTrace) {{
                        let left = parseFloat(r0);
                        let right = parseFloat(r1);
                        let span = right - left;

                        if (span < 5) {{
                            span = 5;
                            right = left + span;
                        }}

                        // 右邊界防呆截斷（Clamping）
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

                        // 【修改目的】：精準計算當前視窗內 K 線 High/Low 極值與成交量極值
                        let startIdx = Math.max(0, Math.floor(left));
                        let endIdx = Math.min(totalBars - 1, Math.ceil(right));
                        let minY = Infinity;
                        let maxY = -Infinity;
                        let maxVol = 0;
                        let hasData = false;

                        for (let i = startIdx; i <= endIdx; i++) {{
                            let l = kTrace.low[i];
                            let h = kTrace.high[i];
                            if (l !== null && l !== undefined && !isNaN(l)) minY = Math.min(minY, l);
                            if (h !== null && h !== undefined && !isNaN(h)) maxY = Math.max(maxY, h);
                            if (volTrace && volTrace.y[i]) {{
                                maxVol = Math.max(maxVol, volTrace.y[i]);
                            }}
                            hasData = true;
                        }}

                        // 當前可視視野變動時，更新資訊條為視野最右側這一天
                        updateInfoBar(endIdx);

                        let updateObj = {{}};
                        if (clamped) {{
                            updateObj['xaxis.range'] = [left, right];
                        }}
                        // 【關鍵修復】：採用標準陣列語法設定 yaxis.range，根治 37K 以下被遮蔽問題
                        if (hasData && minY < maxY) {{
                            let pad = (maxY - minY) * 0.05;
                            updateObj['yaxis.range'] = [minY - pad, maxY + pad];
                        }}
                        if (maxVol > 0) {{
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
    components.html(html_code, height=height + 15, scrolling=False)
