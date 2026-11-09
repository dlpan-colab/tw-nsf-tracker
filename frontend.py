"""
模組名稱：frontend.py
版本識別：20261109_1525
修改目的：
1. 更新版本識別為 20261109_1525。
2. 實作 JavaScript 平移邊界防呆回彈（Clamping）：
   - 監聽主圖 plotly_relayout 事件。
   - 計算右邊界上限 maxAllowedRight = totalBars - 0.5。
   - 當使用者向左拖曳（視野右移）導致 newRange[1] > maxAllowedRight 時，強制釘死右邊界並回推左邊界，絕不露出未來交易日空白。
3. 視窗內 Y 軸動態自適應（Auto-Scale Y）：
   - 依據當前可視的整數索引範圍切片，精確提取 High 與 Low 極值並加上 5% 緩衝區更新 yaxis.range。
4. 嚴格鎖定 dragmode='pan' 與 scrollZoom=true，杜絕遮罩並確保單指平移與滾輪縮放。
防呆防錯原因：
1. 類別型態（category）下，Plotly relayout 的數值直接對應整數浮點索引，回彈防呆能 100% 阻斷向右越界。
2. 加入 isRelayouting 旗標鎖，防止 Plotly.relayout 自身觸發事件循環導致堆疊溢位（Infinite Loop）。
"""

MODULE_VERSION = "20261109_1525"

import streamlit.components.v1 as components
import plotly.graph_objects as go

def render_interactive_chart(fig: go.Figure, height: int = 720):
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
            }}
            #chart-container {{
                width: 100%;
                height: {height}px;
            }}
            .rangeslider-container, .rangeslider-mask, .selectionlayer {{
                display: none !important;
                visibility: hidden !important;
                pointer-events: none !important;
            }}
        </style>
    </head>
    <body>
        <div id="chart-container"></div>
        <script>
            const figureData = {fig_json};
            const container = document.getElementById('chart-container');

            // 確保 Layout 基礎配置鎖定
            figureData.layout.dragmode = 'pan';
            figureData.layout.hovermode = false;
            
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

            let isRelayouting = false; // 防呆鎖：阻斷遞迴觸發

            Plotly.newPlot(container, figureData.data, figureData.layout, config).then(() => {{
                container.on('plotly_relayout', function(eventData) {{
                    if (isRelayouting) return;

                    let r0 = eventData['xaxis.range[0]'];
                    let r1 = eventData['xaxis.range[1]'];

                    if (r0 !== undefined && r1 !== undefined && figureData.data[0]) {{
                        const kTrace = figureData.data[0];
                        const totalBars = kTrace.x.length;
                        if (totalBars === 0) return;

                        let left = parseFloat(r0);
                        let right = parseFloat(r1);
                        let span = right - left;

                        // 最小/最大視野防呆
                        if (span < 5) {{
                            span = 5;
                            right = left + span;
                        }}

                        // 【關鍵機制】：右邊界回彈截斷防呆（Clamping）
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
                            if (span > totalBars) {{
                                right = maxAllowedRight;
                            }} else {{
                                right = left + span;
                            }}
                            clamped = true;
                        }}

                        // 【關鍵機制】：視窗內 Y 軸動態自適應（Auto-Scale Y）
                        let startIdx = Math.max(0, Math.floor(left));
                        let endIdx = Math.min(totalBars - 1, Math.ceil(right));
                        let minY = Infinity;
                        let maxY = -Infinity;
                        let hasData = false;

                        for (let i = startIdx; i <= endIdx; i++) {{
                            let low = kTrace.low[i];
                            let high = kTrace.high[i];
                            if (low !== null && low !== undefined && !isNaN(low)) minY = Math.min(minY, low);
                            if (high !== null && high !== undefined && !isNaN(high)) maxY = Math.max(maxY, high);
                            hasData = true;
                        }}

                        let updateObj = {{}};
                        if (clamped) {{
                            updateObj['xaxis.range[0]'] = left;
                            updateObj['xaxis.range[1]'] = right;
                        }}
                        if (hasData && minY < maxY) {{
                            let pad = (maxY - minY) * 0.05;
                            updateObj['yaxis.range[0]'] = minY - pad;
                            updateObj['yaxis.range[1]'] = maxY + pad;
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
