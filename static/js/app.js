document.addEventListener('DOMContentLoaded', () => {
    const stockListEl = document.getElementById('stock-list');
    const searchInput = document.getElementById('search-input');
    const chartContainer = document.getElementById('chart-container');
    const currentStockTitle = document.getElementById('current-stock-title');
    const updateListBtn = document.getElementById('update-list-btn');
    const periodButtons = document.querySelectorAll('.period-selectors button');

    let chartInstance = null;
    let allStocks = [];
    let currentStock = null;
    let currentPeriod = 'daily';

    // Initialize ECharts
    function initChart() {
        if (chartInstance) {
            chartInstance.dispose();
        }
        chartInstance = echarts.init(chartContainer, 'dark');

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
        const term = e.target.value.toLowerCase();
        const filtered = allStocks.filter(s =>
            s.symbol.toLowerCase().includes(term) ||
            s.name.toLowerCase().includes(term)
        );
        renderStockList(filtered);
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
                renderChart(result.data);
            } else {
                // Auto download if data is missing
                chartInstance.showLoading({text: '本地无数据，自动下载中...', color: '#ffd700', textColor: '#ffd700', maskColor: 'rgba(0, 0, 0, 0.8)'});

                await fetch(`/api/download?symbol=${symbol}`, { method: 'POST' });

                // Poll until data is available (simple wait for demo)
                setTimeout(async () => {
                    response = await fetch(`/api/kline/${symbol}?period=${currentPeriod}`);
                    result = await response.json();

                    if (result.data && result.data.length > 0) {
                        renderChart(result.data);
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
    function renderChart(data) {
        const dates = data.map(item => item.date);

        // ECharts requires data in format [open, close, lowest, highest]
        // But our data is [open, high, low, close]
        // In ECharts candlestick, it's [open, close, lowest, highest] by default for item[1], item[2], item[3], item[4]
        const klineData = data.map(item => [item.open, item.close, item.low, item.high]);

        const volumes = data.map((item, index) => [index, item.volume, item.open > item.close ? -1 : 1]); // -1 down, 1 up

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

        const option = {
            backgroundColor: '#0d1117',
            animation: false,
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'cross' },
                borderWidth: 1,
                borderColor: '#ccc',
                padding: 10,
                textStyle: { color: '#000' }
            },
            axisPointer: { link: [{ xAxisIndex: 'all' }], label: { backgroundColor: '#777' } },
            visualMap: {
                show: false,
                seriesIndex: 1, // volume series
                dimension: 2,
                pieces: [{ value: 1, color: upColor }, { value: -1, color: downColor }]
            },
            grid: [
                { left: '10%', right: '8%', height: '50%' }, // K-line
                { left: '10%', right: '8%', top: '63%', height: '10%' }, // Volume
                { left: '10%', right: '8%', top: '75%', height: '10%' }, // MACD
                { left: '10%', right: '8%', top: '88%', height: '10%' }  // KDJ
            ],
            xAxis: [
                { type: 'category', data: dates, scale: true, boundaryGap: false, axisLine: { onZero: false }, splitLine: { show: false }, min: 'dataMin', max: 'dataMax', axisPointer: { z: 100 } },
                { type: 'category', gridIndex: 1, data: dates, axisLabel: { show: false } },
                { type: 'category', gridIndex: 2, data: dates, axisLabel: { show: false } },
                { type: 'category', gridIndex: 3, data: dates, axisLabel: { show: false } }
            ],
            yAxis: [
                { scale: true, splitArea: { show: true } },
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
                    }
                },
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
                        color: (params) => params.data >= 0 ? upColor : downColor
                    }
                },
                { name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macd, lineStyle: { width: 1 } },
                { name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: macds, lineStyle: { width: 1 } },

                { name: 'K', type: 'line', xAxisIndex: 3, yAxisIndex: 3, data: kdj_k, lineStyle: { width: 1 } },
                { name: 'D', type: 'line', xAxisIndex: 3, yAxisIndex: 3, data: kdj_d, lineStyle: { width: 1 } },
                { name: 'J', type: 'line', xAxisIndex: 3, yAxisIndex: 3, data: kdj_j, lineStyle: { width: 1 } }
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
