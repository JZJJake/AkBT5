import re

with open('static/index.html', 'r') as f:
    content = f.read()

# Add Backtest Button
button_html = """
                <button id="screener-btn" class="btn">选股策略</button>
                <button id="backtest-btn" class="btn" disabled>模拟回测</button>
"""
content = content.replace('<button id="screener-btn" class="btn">选股策略</button>', button_html)

# Add Backtest Modal
modal_html = """
    <!-- Backtest Result Modal -->
    <div id="backtest-modal" class="modal hidden">
        <div class="modal-content backtest-content">
            <h3>回测结果 <span id="backtest-symbol"></span></h3>
            <div class="backtest-summary">
                <div class="summary-item">
                    <span class="label">初始资金:</span>
                    <span id="bt-initial" class="value"></span>
                </div>
                <div class="summary-item">
                    <span class="label">最终资金:</span>
                    <span id="bt-final" class="value"></span>
                </div>
                <div class="summary-item">
                    <span class="label">总收益率:</span>
                    <span id="bt-profit" class="value"></span>
                </div>
                <div class="summary-item">
                    <span class="label">交易次数:</span>
                    <span id="bt-trades" class="value"></span>
                </div>
                <div class="summary-item">
                    <span class="label">胜率:</span>
                    <span id="bt-winrate" class="value"></span>
                </div>
            </div>

            <div class="backtest-table-container">
                <table id="backtest-table">
                    <thead>
                        <tr>
                            <th>买入日期</th>
                            <th>买入价</th>
                            <th>卖出日期</th>
                            <th>卖出价</th>
                            <th>收益率(%)</th>
                        </tr>
                    </thead>
                    <tbody>
                        <!-- Rows injected via JS -->
                    </tbody>
                </table>
            </div>

            <div class="modal-actions">
                <button id="modal-close-bt-btn" class="btn cancel-btn">关闭</button>
            </div>
        </div>
    </div>
"""

content = content.replace('<!-- Confirmation Modal -->', modal_html + '\n    <!-- Confirmation Modal -->')

with open('static/index.html', 'w') as f:
    f.write(content)
print("HTML patched.")
