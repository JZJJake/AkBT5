import re

with open('static/js/app.js', 'r') as f:
    content = f.read()

# Generate markPoint data for J line upward turns
js_markpoint_logic = """
        // Find J line buy signals (upward turns)
        const j_buy_signals = [];
        for (let i = 2; i < data.length; i++) {
            let prev2 = data[i-2].kdj_j;
            let prev1 = data[i-1].kdj_j;
            let curr = data[i].kdj_j;

            // J line forms a bottom (V-shape) AND the J value is starting to trend upward or ST triggers
            if (prev1 < prev2 && curr > prev1) {
                // To filter noise, you typically want this to happen at low levels or when ST condition (kinetic energy) starts
                // Let's add a buy signal marker at the 'curr' index
                if (data[i].kdj_st === 1 || curr < 30) {
                    j_buy_signals.push({
                        name: 'Buy',
                        coord: [i, curr],
                        value: 'B',
                        itemStyle: { color: 'red' },
                        symbolSize: 15,
                        symbolOffset: [0, 10]
                    });
                }
            }
        }
"""

# Insert logic before visualMap array
content = content.replace("const option = {", js_markpoint_logic + "\n        const option = {")

# Replace J line definition
old_j_line = "{ name: 'J', type: 'line', xAxisIndex: 3, yAxisIndex: 3, data: kdj_j, lineStyle: { width: 1 } }"
new_j_line = """{
                    name: 'J', type: 'line', xAxisIndex: 3, yAxisIndex: 3, data: kdj_j, lineStyle: { width: 1 },
                    markPoint: {
                        symbol: 'arrow',
                        data: j_buy_signals,
                        label: { show: false }
                    }
                }"""

content = content.replace(old_j_line, new_j_line)

with open('static/js/app.js', 'w') as f:
    f.write(content)
