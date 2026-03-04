document.addEventListener('DOMContentLoaded', () => {
    const stockListEl = document.getElementById('stock-list');
    const searchInput = document.getElementById('search-input');
    const searchSuggestions = document.getElementById('search-suggestions');
    const chartContainer = document.getElementById('chart-container');
    const currentStockTitle = document.getElementById('current-stock-title');
    const updateListBtn = document.getElementById('update-list-btn');
    const periodButtons = document.querySelectorAll('.period-selectors button');

    let chartInstance = null;
    let allStocks = [];
    let currentStock = null;
    let currentPeriod = 'daily';

    let currentMouseY = 0;

    // Initialize ECharts
    function initChart() {
        if (chartInstance) {
            chartInstance.dispose();
        }
        chartInstance = echarts.init(chartContainer, 'dark');

        // Track mouse Y position for context-aware tooltips
        chartInstance.getZr().on('mousemove', function (params) {
            currentMouseY = params.offsetY;
        });

        // Window resize handler
        window.addEventListener('resize', () => {
            chartInstance.resize();
        });
    }

    // Fetch stock list
    async function fetchStockList() {
        try {
            stockListEl.innerHTML = '<li>加载中...</li>';
            const response = await fetch('/api/stocks');
            const data = await response.json();

            if (data.stocks && data.stocks.length > 0) {
                allStocks = data.stocks;
                renderStockList(allStocks);
            } else {
                stockListEl.innerHTML = '<li>未找到股票数据，请点击“一键同步历史数据”</li>';
            }
        } catch (error) {
            console.error('Error fetching stock list:', error);
            stockListEl.innerHTML = '<li>加载失败</li>';
        }
    }

    // Render stock list in sidebar
    function renderStockList(stocks) {
        stockListEl.innerHTML = '';

        // Render max 100 items for performance initially
        const displayStocks = stocks.slice(0, 100);

        displayStocks.forEach(stock => {
            const li = document.createElement('li');
            li.innerHTML = `<span>${stock.symbol}</span><span>${stock.name}</span>`;
            li.addEventListener('click', () => selectStock(stock, li));
            stockListEl.appendChild(li);
        });
    }

    // Handle search
    searchInput.addEventListener('input', (e) => {
        const term = e.target.value.trim();
        if (!term) {
            searchSuggestions.classList.add('hidden');
            searchSuggestions.innerHTML = '';
            // Reset main list to initial display
            renderStockList(allStocks);
            return;
        }

        let filtered = [];
        if (typeof PinyinMatch !== 'undefined' && PinyinMatch.match) {
            filtered = allStocks.filter(s =>
                PinyinMatch.match(s.name, term) || s.symbol.includes(term)
            );
        } else {
            // Fallback if pinyin-match failed to load
            filtered = allStocks.filter(s =>
                s.symbol.toLowerCase().includes(term.toLowerCase()) ||
                s.name.toLowerCase().includes(term.toLowerCase())
            );
        }

        // Render main list with filtered results
        renderStockList(filtered);

        // Show suggestions dropdown
        const displaySuggestions = filtered.slice(0, 10);
        searchSuggestions.innerHTML = '';
        if (displaySuggestions.length > 0) {
            displaySuggestions.forEach(stock => {
                const li = document.createElement('li');
                li.innerHTML = `<span>${stock.symbol}</span> - <span>${stock.name}</span>`;
                li.addEventListener('click', () => {
                    searchInput.value = '';
                    searchSuggestions.classList.add('hidden');
                    // Find it in the main list and select it
                    selectStock(stock, null); // passing null for liElement as we might not have it rendered in sidebar yet
                    renderStockList(allStocks); // reset list
                });
                searchSuggestions.appendChild(li);
            });
            searchSuggestions.classList.remove('hidden');
        } else {
            searchSuggestions.classList.add('hidden');
        }
    });

    // Hide suggestions on outside click
    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !searchSuggestions.contains(e.target)) {
            searchSuggestions.classList.add('hidden');
        }
    });

    // Handle Enter key for search
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            if (!searchSuggestions.classList.contains('hidden')) {
                const firstSuggestion = searchSuggestions.querySelector('li');
                if (firstSuggestion) {
                    firstSuggestion.click();
                }
            }
        }
    });

    // Select stock
    async function selectStock(stock, liElement) {
        // Highlight active
        document.querySelectorAll('#stock-list li').forEach(el => el.classList.remove('active'));
        if (liElement) liElement.classList.add('active');

        currentStock = stock;
        currentStockTitle.textContent = `${stock.name} (${stock.symbol})`;

        await loadKLineData(stock.symbol);
    }

    // Load and render K-line data
    async function loadKLineData(symbol) {
        if (!chartInstance) initChart();
        chartInstance.showLoading({text: '加载中...', color: '#ffd700', textColor: '#ffd700', maskColor: 'rgba(0, 0, 0, 0.8)'});

        try {
            let response = await fetch(`/api/kline/${symbol}?period=${currentPeriod}`);
            let result = await response.json();

            if (result.data && result.data.length > 0) {
                renderChart(result.data, result.last_close);
            } else {
                // Auto download if data is missing
                chartInstance.showLoading({text: '本地无数据，自动下载中...', color: '#ffd700', textColor: '#ffd700', maskColor: 'rgba(0, 0, 0, 0.8)'});

                await fetch(`/api/download?symbol=${symbol}`, { method: 'POST' });

                // Poll until data is available (simple wait for demo)
                setTimeout(async () => {
                    response = await fetch(`/api/kline/${symbol}?period=${currentPeriod}`);
                    result = await response.json();

                    if (result.data && result.data.length > 0) {
                        renderChart(result.data, result.last_close);
                    } else {
                        chartInstance.hideLoading();
                        chartInstance.clear();
                        alert('下载数据失败或该股票无历史数据。');
                    }
                }, 5000);
            }
        } catch (error) {
            console.error('Error loading K-line data:', error);
            chartInstance.hideLoading();
            alert('加载数据失败');
        }
    }

    // Render ECharts
    function renderChart(data, lastClose) {
        const dates = data.map(item => item.date);

        // ECharts requires data in format [open, close, lowest, highest]
        // But our data is [open, high, low, close]
        // In ECharts candlestick, it's [open, close, lowest, highest] by default for item[1], item[2], item[3], item[4]
        const klineData = data.map(item => [item.open, item.close, item.low, item.high]);

        const volumes = data.map((item, index) => [index, item.volume, item.open > item.close ? -1 : 1]); // -1 down, 1 up

        const ma20 = data.map(item => item.ma20);
        const ma205 = data.map(item => item.ma205);

        const markAreas = [];
        data.forEach((item, index) => {
            if (item.ztfb3 && index > 0) {
                let startIdx = Math.max(0, index - 2);
                let endIdx = index;
                markAreas.push([
                    { xAxis: dates[startIdx], yAxis: item.ztfb_maxh },
                    { xAxis: dates[endIdx], yAxis: item.ztfb_maxl }
                ]);
            }
        });

        const macd = data.map(item => item.macd);
        const macds = data.map(item => item.macds);
        const macdh = data.map(item => item.macdh);

        const kdj_k = data.map(item => item.kdj_k);
        const kdj_d = data.map(item => item.kdj_d);
        const kdj_j = data.map(item => item.kdj_j);

        const upColor = '#f6465d';
        const upBorderColor = '#f6465d';
        const downColor = '#0ecb81';
        const downBorderColor = '#0ecb81';

        // Get latest bar stats for overlay
        const latest = data[data.length - 1] || {};
        let changeText = (latest.change_pct !== undefined && latest.change_pct !== null) ? latest.change_pct.toFixed(2) + '%' : '0.00%';
        let shadowText = (latest.upper_shadow_pct !== undefined && latest.upper_shadow_pct !== null) ? latest.upper_shadow_pct.toFixed(2) + '%' : '0.00%';
        let changeColor = (latest.change_pct > 0) ? '#f6465d' : '#0ecb81';

        // Custom KDJ dot logic for the KDJ grid (top right of KDJ section)
        // We need dots for the latest bar and 4 previous bars: 5 dots in total.
        const stCircles = [];
        for (let i = 0; i < 5; i++) {
            let stVal = data[data.length - 1 - i]?.kdj_st;
            let dotColor = '#808080'; // gray default
            if (stVal === 1) dotColor = 'red';
            else if (stVal === 0) dotColor = 'green';

            stCircles.push({
                type: 'circle',
                right: (8 + i * 2) + '%',
                top: '88%',
                shape: { r: 5 },
                style: { fill: dotColor }
            });
        }

        // Add '连续红：' text before the dots if ST sequence exists
        const latestTJ = latest.kdj_tj;
        let continuousRedText = [];
        if (latest.kdj_st !== undefined && latest.kdj_st !== null && latest.kdj_st !== -1) {
            continuousRedText = [
                {
                    type: 'text',
                    right: '20%',
                    top: '88%',
                    style: {
                        text: `连续红：${latestTJ}`,
                        fill: (latestTJ > 0) ? 'red' : 'white',
                        font: '14px sans-serif'
                    }
                }
            ];
        }


        // Handle multi-colored MACD DIF (Fast Line) based on slope (current > previous)
        const macdDif_pieces = [];
        for (let i = 1; i < data.length; i++) {
            let color = '#d7a1ff'; // default pink/purple
            let currDif = data[i].macd;
            let prevDif = data[i-1].macd;
            if (currDif > prevDif) {
                color = 'red'; // slope up
            } else {
                color = '#0ecb81'; // slope down (green)
            }
            macdDif_pieces.push({
                gt: i - 1,
                lte: i,
                color: color
            });
        }
        // Catch the last segment to make it extend
        if (data.length > 0) {
            let i = data.length - 1;
            let color = (i > 0 && data[i].macd > data[i-1].macd) ? 'red' : '#0ecb81';
            macdDif_pieces.push({
                gt: i,
                lte: i + 1,
                color: color
            });
        }

        // Handle multi-colored KDJ J Line based on ST value
        const kdjJ_pieces = [];
        for (let i = 0; i < data.length - 1; i++) {
            let color = '#d7a1ff'; // Default J color (purple)
            if (data[i].kdj_st === 1) {
                color = 'red';
            } else if (data[i].kdj_st === 0) {
                color = '#b45078'; // RGB(180,80,120)
            }
            kdjJ_pieces.push({
                gt: i - 1,
                lte: i,
                color: color
            });
        }
        // catch the last one
        if (data.length > 0) {
            let i = data.length - 1;
            let color = '#d7a1ff';
            if (data[i].kdj_st === 1) {
                color = 'red';
            } else if (data[i].kdj_st === 0) {
                color = '#b45078';
            }
            kdjJ_pieces.push({
                gt: i - 1,
                lte: i,
                color: color
            });
        }


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
        }

        const option = {
            backgroundColor: '#0d1117',
            animation: false,
            graphic: [
                {
                    type: 'text',
                    left: '2%',
                    top: '74%', // MACD grid top
                    style: {
                        text: 'MACD (10, 25, 7)',
                        fill: '#f5c242',
                        font: '12px sans-serif'
                    }
                },
                {
                    type: 'text',
                    left: '2%',
                    top: '88%', // KDJ grid top
                    style: {
                        text: 'KDJ (9, 3, 3)',
                        fill: '#f5c242',
                        font: '12px sans-serif'
                    }
                },
                {
                    type: 'text',
                    left: '12%',
                    top: '2%',
                    style: {
                        text: `涨幅: ${changeText}`,
                        fill: changeColor,
                        font: '14px sans-serif',
                        fontWeight: 'bold'
                    }
                },
                {
                    type: 'text',
                    left: '20%',
                    top: '2%',
                    style: {
                        text: `上影线: ${shadowText}`,
                        fill: '#fff',
                        font: '14px sans-serif'
                    }
                },
                ...continuousRedText,
                ...stCircles
            ],
            tooltip: {
                trigger: 'axis',
                axisPointer: {
                    type: 'cross',
                    lineStyle: {
                        color: 'rgba(255, 215, 0, 0.5)',
                        width: 1,
                        type: 'solid'
                    }
                },
                backgroundColor: 'rgba(22, 27, 34, 0.8)',
                borderWidth: 1,
                borderColor: '#30363d',
                padding: 10,
                textStyle: { color: '#ffd700' },
                position: function (pos, params, el, elRect, size) {
                    const yRatio = pos[1] / size.viewSize[1];
                    let topPos = 10;
                    if (yRatio < 0.55) {
                        topPos = 10;
                    } else if (yRatio >= 0.55 && yRatio < 0.72) {
                        topPos = size.viewSize[1] * 0.60;
                    } else if (yRatio >= 0.72 && yRatio < 0.86) {
                        topPos = size.viewSize[1] * 0.74;
                    } else {
                        topPos = size.viewSize[1] * 0.88;
                    }
                    const obj = { top: topPos };
                    obj[['left', 'right'][+(pos[0] < size.viewSize[0] / 2)]] = 30;
                    return obj;
                },
                formatter: function (params) {
                    let klineData = null;
                    let volData = null;
                    let macdData = [];
                    let kdjData = [];
                    let maData = [];
                    let date = '';

                    params.forEach(param => {
                        date = param.axisValue;
                        if (param.seriesName === '日线' || param.seriesName === '周线' || param.seriesName === '月线') {
                            klineData = param.data;
                        } else if (param.seriesName === '成交量') {
                            volData = param.data;
                        } else if (['MACD', 'DIF', 'DEA'].includes(param.seriesName)) {
                            macdData.push(param);
                        } else if (['K', 'D', 'J'].includes(param.seriesName)) {
                            kdjData.push(param);
                        } else if (['MA20', 'MA205'].includes(param.seriesName)) {
                            maData.push(param);
                        }
                    });

                    let res = `<div style="font-weight:bold;margin-bottom:5px;">${date}</div>`;

                    // Determine which grid the mouse is currently hovering over
                    const height = chartInstance.getHeight();

                    // Map heights roughly according to grid settings:
                    // K-line: 0% - ~60%
                    // Volume: ~63% - ~73%
                    // MACD: ~75% - ~85%
                    // KDJ: ~88% - ~98%
                    const yRatio = currentMouseY / height;

                    if (yRatio < 0.55) {
                        // K-line Grid
                        if (klineData) {
                            res += `
                                <div>开盘: ${klineData[1].toFixed(2)}</div>
                                <div>收盘: ${klineData[2].toFixed(2)}</div>
                                <div>最低: ${klineData[3].toFixed(2)}</div>
                                <div>最高: ${klineData[4].toFixed(2)}</div>
                            `;
                            maData.forEach(m => {
                                if (m.data !== undefined && m.data !== null) {
                                    res += `<div><span style="display:inline-block;margin-right:4px;border-radius:10px;width:10px;height:10px;background-color:${m.color};"></span>${m.seriesName}: ${m.data.toFixed(3)}</div>`;
                                }
                            });
                        }
                    } else if (yRatio >= 0.55 && yRatio < 0.72) {
                        // Volume Grid
                        if (volData) {
                            res += `<div>成交量: ${volData[1]}</div>`;
                        }
                    } else if (yRatio >= 0.72 && yRatio < 0.86) {
                        // MACD Grid
                        if (macdData.length > 0) {
                            res += `<div style="margin-top:5px;padding-top:5px;">MACD (10,25,7)</div>`;
                            macdData.forEach(m => {
                                if (m.data !== undefined && m.data !== null) {
                                    res += `<div>${m.seriesName}: ${m.data.toFixed(3)}</div>`;
                                }
                            });
                        }
                    } else {
                        // KDJ Grid
                        if (kdjData.length > 0) {
                            res += `<div style="margin-top:5px;padding-top:5px;">KDJ (9,3,3)</div>`;
                            kdjData.forEach(k => {
                                if (k.data !== undefined && k.data !== null) {
                                    res += `<div>${k.seriesName}: ${k.data.toFixed(3)}</div>`;
                                }
                            });
                        }
                    }

                    return res;
                }
            },
            axisPointer: { link: [{ xAxisIndex: 'all' }], label: { backgroundColor: '#777' } },
                    visualMap: [
                {
                    show: false,
                    dimension: 0,
                    seriesIndex: 3, // Volume
                    pieces: [{ value: 1, color: upColor }, { value: -1, color: downColor }]
                },
                {
                    show: false,
                    dimension: 0,
                    seriesIndex: 5, // DIF
                    pieces: macdDif_pieces
                },
                {
                    show: false,
                    dimension: 0,
                    seriesIndex: 8, // J line is series index 8 now (since we removed D)
                    pieces: kdjJ_pieces
                }
            ],
            grid: [
                { left: '2%', right: '4%', height: '52%' }, // K-line
                { left: '2%', right: '4%', top: '60%', height: '12%' }, // Volume
                { left: '2%', right: '4%', top: '74%', height: '12%' }, // MACD
                { left: '2%', right: '4%', top: '88%', height: '12%' }  // KDJ
            ],
            xAxis: [
                { type: 'category', data: dates, scale: true, boundaryGap: false, axisLine: { onZero: false }, splitLine: { show: false }, min: 'dataMin', max: 'dataMax', axisPointer: { z: 100 } },
                { type: 'category', gridIndex: 1, data: dates, axisLabel: { show: false } },
                { type: 'category', gridIndex: 2, data: dates, axisLabel: { show: false } },
                { type: 'category', gridIndex: 3, data: dates, axisLabel: { show: false } }
            ],
            yAxis: [
                { scale: true, splitArea: { show: false }, splitLine: { show: true, lineStyle: { color: '#30363d', type: 'dashed' } }, position: 'right' },
                { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
                { scale: true, gridIndex: 2, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
                { scale: true, gridIndex: 3, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } }
            ],
            dataZoom: [
                { type: 'inside', xAxisIndex: [0, 1, 2, 3], start: 80, end: 100 },
                { show: true, xAxisIndex: [0, 1, 2, 3], type: 'slider', top: '98%', start: 80, end: 100 }
            ],
            series: [
                {
                    name: '日线',
                    type: 'candlestick',
                    data: klineData,
                    itemStyle: {
                        color: upColor, color0: downColor,
                        borderColor: upBorderColor, borderColor0: downBorderColor
                    },
                    markLine: {
                        data: [
                            {
                                yAxis: lastClose,
                                lineStyle: { type: 'dashed', color: 'yellow' },
                                label: { position: 'end', formatter: ' ' + lastClose.toFixed(2) }
                            }
                        ]
                    },
                    markArea: {
                        itemStyle: { color: 'rgba(128, 128, 128, 0.3)' }, // colorgray roughly
                        data: markAreas
                    }
                },
                { name: 'MA20', type: 'line', data: ma20, smooth: true, lineStyle: { opacity: 0.5, width: 1, color: '#f5c242' }, symbol: 'none' },
                { name: 'MA205', type: 'line', data: ma205, smooth: true, lineStyle: { opacity: 0.5, width: 1, color: '#42a5f5' }, symbol: 'none' },
                {
                    name: '成交量',
                    type: 'bar',
                    xAxisIndex: 1, yAxisIndex: 1,
                    data: volumes
                },
                {
                    name: 'MACD', type: 'bar', xAxisIndex: 2, yAxisIndex: 2,
                    data: macdh,
                    itemStyle: {
                        color: (params) => {
                            if (params.dataIndex === 0) return params.data >= 0 ? upColor : downColor;
                            const prev = macdh[params.dataIndex - 1];
                            return params.data > prev ? upColor : downColor;
                        }
                    }
                },
                { name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macd, lineStyle: { width: 1 }, symbol: 'none' },
                { name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macds, lineStyle: { width: 1 }, symbol: 'none' },

                {
                    name: 'K', type: 'line', xAxisIndex: 3, yAxisIndex: 3, data: kdj_k, lineStyle: { width: 1 }, symbol: 'none',
                    markLine: {
                        symbol: 'none',
                        silent: true,
                        label: { position: 'start', formatter: '{c}', color: 'gray' },
                        data: [
                            { yAxis: 0, lineStyle: { type: 'dashed', color: 'gray' } },
                            { yAxis: 30, lineStyle: { type: 'dashed', color: '#ffb74d' } },
                            { yAxis: 50, lineStyle: { type: 'dashed', color: '#64b5f6' } },
                            { yAxis: 80, lineStyle: { type: 'dashed', color: '#81c784' } }
                        ]
                    }
                },
                // User requested: "KDJ只有J和K线" -> hiding D line
                // { name: 'D', type: 'line', xAxisIndex: 3, yAxisIndex: 3, data: kdj_d, lineStyle: { width: 1 }, symbol: 'none' },
                {
                    name: 'J', type: 'line', xAxisIndex: 3, yAxisIndex: 3, data: kdj_j, lineStyle: { width: 1 }, symbol: 'none',
                    markPoint: {
                        symbol: 'arrow',
                        data: j_buy_signals,
                        label: { show: false }
                    }
                }
            ]
        };

        chartInstance.setOption(option);
        chartInstance.hideLoading();
    }

    // Triggers
    updateListBtn.addEventListener('click', async () => {
        if (!confirm('这将从网络下载所有A股的数据。此操作可能需要数小时并在后台运行。是否继续？')) {
            return;
        }
        updateListBtn.disabled = true;
        updateListBtn.textContent = '同步中...';
        await fetch('/api/download', { method: 'POST' });
        alert('后台全量更新任务已启动。您可以继续浏览已有数据或稍后刷新页面查看新数据。由于数据量庞大，完成需要一定时间。');
        updateListBtn.disabled = false;
        updateListBtn.textContent = '一键同步历史数据';
    });

    // Handle period switching
    periodButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            periodButtons.forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');

            currentPeriod = e.target.getAttribute('data-period');
            if (currentStock) {
                loadKLineData(currentStock.symbol);
            }
        });
    });

    // Startup
    initChart();
    fetchStockList();
});
