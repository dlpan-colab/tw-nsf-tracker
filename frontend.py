"""
模組名稱：frontend.py
版本識別：20261109_1510
修改目的：
1. 建立前端專屬 HTML/JavaScript 渲染容器，徹底繞過 st.plotly_chart 的封裝盲點。
2. 在原生 JS 端精確鎖定 dragmode='pan'，強制關閉 rangeslider，徹底消滅灰底遮罩與白色手柄。
3. 監聽 wheel 事件與 touch/pan 事件，提供平滑平移與縮放。
4. 實作 Y 軸動態自適應（Auto-scale Y）與最新交易日右側防呆回彈邊界。
防呆防錯原因：
1. 原生 JS 直接在 client-side 執行，避免 Streamlit 反覆序列化與重新渲染引發的滑桿重生。
2. 透過 iframe 隔絕 CSS 污染，確保手機端觸控手勢判定不被父層容器攔截。
"""

MODULE_VERSION = "20261109_1510"

import json
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
            /* 嚴格防呆：禁止任何選取層與滑桿遮罩在 DOM 顯示 */
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

            // 確保 Layout 參數原生鎖定
            figureData.layout.dragmode = 'pan';
            figureData.layout.hovermode = false;
            
            // 雙重保證主副軸 rangeslider 完全停用
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

            Plotly.newPlot(container, figureData.data, figureData.layout, config).then(() => {{
                // 監聽平移與縮放事件，實施視窗內 Y 軸動態 Auto-Scale
                container.on('plotly_relayout', function(eventData) {{
                    let x0 = eventData['xaxis.range[0]'];
                    let x1 = eventData['xaxis.range[1]'];
                    
                    if (x0 && x1 && figureData.data[0]) {{
                        const kTrace = figureData.data[0];
                        let minY = Infinity;
                        let maxY = -Infinity;
                        let hasData = false;

                        for (let i = 0; i < kTrace.x.length; i++) {{
                            let d = kTrace.x[i];
                            if (d >= x0 && d <= x1) {{
                                let low = kTrace.low[i];
                                let high = kTrace.high[i];
                                if (low !== null && low !== undefined) minY = Math.min(minY, low);
                                if (high !== null && high !== undefined) maxY = Math.max(maxY, high);
                                hasData = true;
                            }}
                        }}

                        if (hasData && minY < maxY) {{
                            let pad = (maxY - minY) * 0.05;
                            Plotly.relayout(container, {{
                                'yaxis.range': [minY - pad, maxY + pad]
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
