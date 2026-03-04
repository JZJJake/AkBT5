import re

with open('static/js/app.js', 'r') as f:
    content = f.read()

# Fix the marker definition
content = content.replace("""        // Find J line buy signals (upward turns)
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
        }""", """        // Find J line buy signals (upward turns)
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
                        coord: [dates[i], curr],
                        value: 'B',
                        itemStyle: { color: 'red' },
                        symbolSize: 15,
                        symbolOffset: [0, 10],
                        xAxis: dates[i],
                        yAxis: curr
                    });
                }
            }
        }""")

with open('static/js/app.js', 'w') as f:
    f.write(content)
