document.addEventListener('DOMContentLoaded', () => {
    const stockListEl = document.getElementById('stock-list');
    const searchInput = document.getElementById('search-input');
    const searchSuggestions = document.getElementById('search-suggestions');
    const chartContainer = document.getElementById('chart-container');
    const currentStockTitle = document.getElementById('current-stock-title');
    const updateListBtn = document.getElementById('update-list-btn');
    const screenerBtn = document.getElementById('screener-btn');
    const backtestBtn = document.getElementById('backtest-btn');
    const periodButtons = document.querySelectorAll('.period-selectors button');



    function showToast(message, type = 'info', duration = 3000) {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;

        container.appendChild(toast);

        // Trigger animation
        setTimeout(() => toast.classList.add('show'), 10);

        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 400); // wait for animation
        }, duration);
    }


    let syncPollInterval = null;

    function startSyncPolling() {
        const container = document.getElementById('sync-progress-container');
        const textEl = document.getElementById('sync-status-text');
        const pctEl = document.getElementById('sync-percentage');
        const fillEl = document.getElementById('sync-progress-fill');

        container.classList.remove('hidden');

        if (syncPollInterval) clearInterval(syncPollInterval);

        syncPollInterval = setInterval(async () => {
            try {
                const res = await fetch('/api/sync_progress');
                const data = await res.json();

                if (data.status === 'idle') {
                    // Usually means it hasn't started or already cleared
                    return;
                }

                textEl.textContent = data.message;

                if (data.total > 0) {
                    let pct = Math.floor((data.current / data.total) * 100);
                    pctEl.textContent = pct + '%';
                    fillEl.style.width = pct + '%';
                }

                if (data.status === 'completed') {
                    clearInterval(syncPollInterval);
                    showToast('历史数据同步全部完成！', 'success');
                    setTimeout(() => container.classList.add('hidden'), 2000);
                    fetchStockList();
                    updateListBtn.disabled = false;
                    updateListBtn.textContent = '一键同步历史数据';
                } else if (data.status === 'error') {
                    clearInterval(syncPollInterval);
                    showToast(data.message, 'error');
                    setTimeout(() => container.classList.add('hidden'), 4000);
                    updateListBtn.disabled = false;
                    updateListBtn.textContent = '一键同步历史数据';
                }

            } catch (e) {
                console.error("Error polling sync progress", e);
            }
        }, 1000);
    }

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

        if (backtestBtn) backtestBtn.disabled = false;

        updateWheel(); // Ensure wheel stays in sync with manual clicks

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
        // We also append percentage change to item[5] to be read by tooltip
        const klineData = data.map((item, index) => {
            let preClose = index === 0 ? (item.open) : data[index - 1].close;
            let pctChange = ((item.close - preClose) / preClose * 100).toFixed(2);
            return [item.open, item.close, item.low, item.high, pctChange];
        });

        const volumesUp = [];
        const volumesDown = [];
        data.forEach((item, index) => {
            if (item.close >= item.open) {
                volumesUp.push([index, item.volume, 1]);
                volumesDown.push([index, 0, -1]);
            } else {
                volumesUp.push([index, 0, 1]);
                volumesDown.push([index, item.volume, -1]);
            }
        });

        const ma20 = data.map(item => item.ma20);
        const ma205 = data.map(item => item.ma205);

        const ribbonData = [];
        for (let i = 1; i < data.length - 1; i++) {
            if (ma20[i] !== null && ma205[i] !== null && ma20[i+1] !== null && ma205[i+1] !== null && ma20[i-1] !== null && ma205[i-1] !== null) {
                let currentDiff = ma20[i] - ma205[i];
                let prevDiff = ma20[i-1] - ma205[i-1];
                let colorFlag = 0; // 0 = green, 1 = yellow, 2 = red

                if (ma20[i] > ma205[i]) {
                    if (currentDiff > prevDiff) {
                        colorFlag = 2; // RED
                    } else {
                        colorFlag = 1; // YELLOW
                    }
                } else {
                    colorFlag = 0; // GREEN
                }

                ribbonData.push([i, ma20[i], ma205[i], i+1, ma20[i+1], ma205[i+1], colorFlag]);
            }
        }

        function renderRibbonItem(params, api) {
            const x0 = api.coord([api.value(0), api.value(1)])[0];
            const y0_ma20 = api.coord([api.value(0), api.value(1)])[1];
            const y0_ma205 = api.coord([api.value(0), api.value(2)])[1];

            const x1 = api.coord([api.value(3), api.value(4)])[0];
            const y1_ma20 = api.coord([api.value(3), api.value(4)])[1];
            const y1_ma205 = api.coord([api.value(3), api.value(5)])[1];

            // Check if coordinates are valid numbers
            if (isNaN(x0) || isNaN(y0_ma20) || isNaN(x1)) {
                return;
            }

            let colorFlag = api.value(6);
            let color = 'rgba(0, 255, 0, 0.25)'; // default green
            if (colorFlag === 2) color = 'rgba(255, 0, 0, 0.25)';
            else if (colorFlag === 1) color = 'rgba(255, 255, 0, 0.25)';

            return {
                type: 'polygon',
                shape: {
                    points: [
                        [x0, y0_ma20],
                        [x1, y1_ma20],
                        [x1, y1_ma205],
                        [x0, y0_ma205]
                    ]
                },
                style: api.style({ fill: color, stroke: 'none' })
            };
        }

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
        const volMa20 = data.map(item => item.vol_ma20);

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


        // Optimize multi-colored MACD DIF (Fast Line) visual map
        const macdDif_pieces = [];
        if (data.length > 0) {
            let startIdx = 0;
            let currentColor = 'white';

            const getColor = (stVal) => {
                if (stVal === 1) return 'red';
                if (stVal === 2) return '#b45078';
                return 'white';
            };

            currentColor = getColor(data[1] ? data[1].macd_st_line : data[0].macd_st_line);

            for (let i = 1; i < data.length; i++) {
                let color = getColor(data[i].macd_st_line);
                if (color !== currentColor) {
                    macdDif_pieces.push({ gt: startIdx - 1, lte: i - 1, color: currentColor });
                    startIdx = i;
                    currentColor = color;
                }
            }
            macdDif_pieces.push({ gt: startIdx - 1, lte: data.length, color: currentColor });
        }

        // Handle multi-colored KDJ J Line based on ST value

        // Handle MACD status dots (Top right of MACD grid)
        // DRAWTEXT_FIX(ISLASTBAR AND ST, 0.98, 0.03, 0, "●"), colorred
        // ... (up to 5 dots)
        const macdDots = [];
        for (let i = 0; i < 5; i++) {
            let dotData = data[data.length - 1 - i];
            let stVal = dotData ? dotData.macd_st_dot : 0;
            let dotColor = stVal === 1 ? 'red' : 'green';

            macdDots.push({
                type: 'text',
                right: (2 + i * 2) + '%', // Top Right corner logic
                top: '72%', // MACD grid top
                style: {
                    text: '●',
                    fill: dotColor,
                    font: '14px sans-serif'
                }
            });
        }

        // Optimize multi-colored KDJ J Line visual map
        const kdjJ_pieces = [];
        if (data.length > 0) {
            let startIdx = 0;
            let currentColor = 'white';

            const getColor = (stVal) => {
                if (stVal === 1) return 'red';
                if (stVal === 2) return 'darkred';
                return 'white';
            };

            currentColor = getColor(data[0].kdj_st);

            for (let i = 0; i < data.length; i++) {
                let color = getColor(data[i].kdj_st);
                if (color !== currentColor) {
                    kdjJ_pieces.push({ gt: startIdx - 1, lte: i - 1, color: currentColor });
                    startIdx = i;
                    currentColor = color;
                }
            }
            kdjJ_pieces.push({ gt: startIdx - 1, lte: data.length, color: currentColor });
        }



        // Find J line buy signals based on user TDX logic:
        // KDJJ=(REF(e,2)<a OR e<a) AND REF(e,1)<30 AND e>REF(e,1) AND REF(e,1)<REF(e,2);
        // e = J line (kdj_j), a = K line (kdj_k)
        // Find J line buy signals based on user TDX logic (TT1):
        // TT1=(REF(J,2)<K OR J<K) AND J>REF(J,1) AND REF(J,1)<REF(J,2) AND REF(J,1)<30 AND A3;
        const j_buy_signals = [];
        for (let i = 2; i < data.length; i++) {
            let j_curr = data[i].kdj_j;
            let j_prev1 = data[i-1].kdj_j;
            let j_prev2 = data[i-2].kdj_j;
            let k_curr = data[i].kdj_k;

            // Daily KDJ Condition:
            // 1. J > K OR J > J_2
            // 2. Previous J (j_1) < 30
            // 3. Current J > Previous J
            let condition1 = (j_curr > k_curr) || (j_curr > j_prev2);
            let condition2 = j_prev1 < 30;
            let condition3 = j_curr > j_prev1;

            // A3 logic part
            let a3 = false;
            let close = data[i].close;
            let open = data[i].open;
            let m20 = data[i].ma20;
            let m20_prev = data[i-1].ma20;
            let m205 = data[i].ma205;
            let dm205 = m20 - m205;
            let dm205_prev = m20_prev - data[i-1].ma205;
            let macdh = data[i].macdh;
            let macdh_prev = data[i-1].macdh;

            if (close > open && m20 > m20_prev && m20 > m205 && dm205 > dm205_prev && macdh > macdh_prev) {
                a3 = true;
            }

            if (condition1 && condition2 && condition3 && a3) {
                j_buy_signals.push({
                    name: 'Buy',
                    coord: [dates[i], j_curr],
                    value: 'B',
                    itemStyle: { color: 'red' },
                    symbolSize: 15,
                    symbolOffset: [0, 10],
                    xAxis: dates[i],
                    yAxis: j_curr
                });
            }
        }

        const option = {
            backgroundColor: '#0d1117',
            animation: false,
            graphic: [
                {
                    type: 'text',
                    left: '2%',
                    top: '67.5%', // MACD grid top
                    style: {
                        text: 'MACD (10, 25, 7)',
                        fill: '#f5c242',
                        font: '12px sans-serif'
                    }
                },
                {
                    type: 'text',
                    left: '2%',
                    top: '83.5%', // KDJ grid top
                    style: {
                        text: 'KDJ (9, 3, 3)',
                        fill: '#f5c242',
                        font: '13px sans-serif'
                    }
                },
                ...macdDots
            ],
            tooltip: { animation: false, enterable: false,
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
                    if (yRatio < 0.48) {
                        topPos = 10;
                    } else if (yRatio >= 0.48 && yRatio < 0.67) {
                        topPos = size.viewSize[1] * 0.50;
                    } else if (yRatio >= 0.67 && yRatio < 0.83) {
                        topPos = size.viewSize[1] * 0.67;
                    } else {
                        topPos = size.viewSize[1] * 0.83;
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
                            // param.value contains the array [axisValue, open, close, lowest, highest, pctChange]
                            // which correctly maps our item[5] to param.value[5] instead of param.data[4]
                            klineData = param.value;
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
                    const yRatio = currentMouseY / height;

                    if (yRatio < 0.48) {
                        // K-line Grid
                        if (klineData) {
                            let pct = klineData[5];
                            let pctColor = pct >= 0 ? '#ff4d4f' : '#52c41a';
                            res += `
                                <div>涨幅: <span style="color:${pctColor};font-weight:bold;">${pct}%</span></div>
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
                    } else if (yRatio >= 0.48 && yRatio < 0.67) {
                        // Volume Grid
                        if (volData) {
                            res += `<div>成交量: ${volData[1]}</div>`;
                        }
                    } else if (yRatio >= 0.67 && yRatio < 0.83) {
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
                    seriesIndex: 8, // DIF
                    pieces: macdDif_pieces
                },
                {
                    show: false,
                    dimension: 0,
                    seriesIndex: 11, // J line
                    pieces: kdjJ_pieces
                }
            ],
            grid: [
                { left: '2%', right: '4%', top: '2%', height: '48%' }, // K-line (reduced to give more room below)
                { left: '2%', right: '4%', top: '53%', height: '14%' }, // Volume
                { left: '2%', right: '4%', top: '69%', height: '14%' }, // MACD
                { left: '2%', right: '4%', top: '85%', height: '14%' }  // KDJ
            ],
            xAxis: [
                { type: 'category', data: dates, scale: true, boundaryGap: true, axisLine: { onZero: false }, splitLine: { show: false }, min: 'dataMin', max: 'dataMax', axisPointer: { z: 100 } },
                { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisLabel: { show: false } },
                { type: 'category', gridIndex: 2, data: dates, boundaryGap: true, axisLabel: { show: false } },
                { type: 'category', gridIndex: 3, data: dates, boundaryGap: true, axisLabel: { show: false } }
            ],
            yAxis: [
                { scale: true, splitArea: { show: false }, splitLine: { show: true, lineStyle: { color: '#30363d', type: 'dashed' } }, position: 'right' },
                { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
                { scale: true, gridIndex: 2, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
                { scale: true, gridIndex: 3, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } }
            ],
            dataZoom: [
                { type: 'inside', xAxisIndex: [0, 1, 2, 3], start: 90, end: 100 },
                { show: true, xAxisIndex: [0, 1, 2, 3], type: 'slider', top: '98%', start: 90, end: 100 }
            ],
            series: [
                {
                    name: '日线',
                    type: 'candlestick',
                    large: true,
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
                { name: 'MA20_Ribbon', type: 'custom', renderItem: renderRibbonItem, data: ribbonData, z: 1, xAxisIndex: 0, yAxisIndex: 0 },
                { name: 'MA20', type: 'line', sampling: 'lttb', data: ma20, smooth: true, lineStyle: { opacity: 0.8, width: 1, color: '#f5c242' }, symbol: 'none', z: 3 },
                { name: 'MA205', type: 'line', sampling: 'lttb', data: ma205, smooth: true, lineStyle: { opacity: 0.8, width: 1, color: '#42a5f5' }, symbol: 'none', z: 3 },
                {
                    name: '成交量(涨)',
                    type: 'bar',
                    large: true,
                    stack: 'volume',
                    xAxisIndex: 1, yAxisIndex: 1,
                    data: volumesUp,
                    itemStyle: { color: upColor }
                },
                {
                    name: '成交量(跌)',
                    type: 'bar',
                    large: true,
                    stack: 'volume',
                    xAxisIndex: 1, yAxisIndex: 1,
                    data: volumesDown,
                    itemStyle: { color: downColor }
                },
                {
                    name: 'Vol_MA20',
                    type: 'line',
                    xAxisIndex: 1, yAxisIndex: 1,
                    symbol: 'none',
                    lineStyle: { color: '#ff00ff', width: 1 },
                    data: volMa20
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

        // Dynamically fix Y-axis scaling when filterMode is 'empty' to keep performance high
        // but avoid squashed candles.

        chartInstance.hideLoading();

    }


    // Screener logic
    if (screenerBtn) {
        screenerBtn.addEventListener('click', async () => {
            screenerBtn.disabled = true;
            screenerBtn.textContent = '选股中...';
            allStocks = []; // Clear the pool
            renderStockList(allStocks);
            stockListEl.innerHTML = '<li style="color: gray; padding: 10px;">运行选股策略中...</li>';

            try {
                const res = await fetch('/api/screener');
                const data = await res.json();
                if (data.error) {
                    showToast('选股出错: ' + data.error, 'error');
                    renderStockList(allStocks); // reset
                } else {
                    showToast('选股完成! 找到符合条件的股票数量: ' + data.stocks.length, 'success', 5000);
                    // Update sidebar with only matched stocks
                    allStocks = data.stocks;
                    renderStockList(allStocks);
                }
            } catch (err) {
                console.error(err);
                showToast('选股请求失败', 'error');
            } finally {
                screenerBtn.disabled = false;
                screenerBtn.textContent = '选股 (Screener)';
            }
        });
    }

    // Triggers

    updateListBtn.addEventListener('click', () => {
        document.getElementById('confirm-modal').classList.remove('hidden');
    });

    document.getElementById('modal-cancel-btn').addEventListener('click', () => {
        document.getElementById('confirm-modal').classList.add('hidden');
    });

    document.getElementById('modal-confirm-btn').addEventListener('click', async () => {
        document.getElementById('confirm-modal').classList.add('hidden');
        updateListBtn.disabled = true;
        updateListBtn.textContent = '同步中...';

        try {
            await fetch('/api/download', { method: 'POST' });
            // Start polling progress instead of waiting for immediate response
            startSyncPolling();
        } catch (e) {
            showToast('触发同步失败，请重试。', 'error');
            updateListBtn.disabled = false;
            updateListBtn.textContent = '一键同步历史数据';
        }
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


    // Sidebar & Wheel Logic
    const sidebar = document.getElementById('sidebar');
    const toggleSidebarBtn = document.getElementById('toggle-sidebar-btn');
    const stockWheel = document.getElementById('stock-wheel');
    const wheelPrev = document.getElementById('wheel-prev');
    const wheelCurr = document.getElementById('wheel-curr');
    const wheelNext = document.getElementById('wheel-next');
    const wheelUpBtn = document.getElementById('wheel-up-btn');
    const wheelDownBtn = document.getElementById('wheel-down-btn');

    let currentStockIndex = -1;

    function updateWheel() {
        if (allStocks.length === 0) {
            if(wheelPrev) wheelPrev.textContent = '';
            if(wheelCurr) wheelCurr.textContent = '暂无';
            if(wheelNext) wheelNext.textContent = '';
            return;
        }

        // If no stock is selected but pool has stocks, select the first one silently
        if (!currentStock && allStocks.length > 0) {
            currentStock = allStocks[0];
            currentStockIndex = 0;
            // optionally load it
            document.getElementById('current-stock-title').textContent = `${currentStock.name} (${currentStock.symbol})`;
            loadKLineData(currentStock.symbol);
        }

        currentStockIndex = allStocks.findIndex(s => s.symbol === currentStock.symbol);

        // If current stock was filtered out (e.g. by screener), default to the first one
        if (currentStockIndex === -1 && allStocks.length > 0) {
            currentStock = allStocks[0];
            currentStockIndex = 0;
            document.getElementById('current-stock-title').textContent = `${currentStock.name} (${currentStock.symbol})`;
            loadKLineData(currentStock.symbol);
        }

        if (currentStockIndex > 0) {
            if(wheelPrev) {
                wheelPrev.textContent = allStocks[currentStockIndex - 1].name;
                wheelPrev.title = allStocks[currentStockIndex - 1].symbol;
            }
        } else {
            if(wheelPrev) {
                wheelPrev.textContent = '';
                wheelPrev.title = '';
            }
        }

        if(wheelCurr) wheelCurr.textContent = currentStock.name;

        if (currentStockIndex !== -1 && currentStockIndex < allStocks.length - 1) {
            if(wheelNext) {
                wheelNext.textContent = allStocks[currentStockIndex + 1].name;
                wheelNext.title = allStocks[currentStockIndex + 1].symbol;
            }
        } else {
            if(wheelNext) {
                wheelNext.textContent = '';
                wheelNext.title = '';
            }
        }
    }

    if (toggleSidebarBtn) {
        toggleSidebarBtn.addEventListener('click', () => {
            sidebar.classList.toggle('collapsed');
            if (sidebar.classList.contains('collapsed')) {
                stockWheel.classList.remove('hidden');
                updateWheel();
            } else {
                stockWheel.classList.add('hidden');
            }

            // Performance Fix: Calling resize() on every frame of a CSS transition is extremely expensive.
            // Instead, we call it once when the transition starts and once when it ends.
            if (chartInstance) chartInstance.resize();
            setTimeout(() => {
                if (chartInstance) chartInstance.resize();
            }, 400); // 400ms matches the CSS transition duration
        });
    }

    function switchWheelStock(offset) {
        if (currentStockIndex === -1) return;
        const newIndex = currentStockIndex + offset;
        if (newIndex >= 0 && newIndex < allStocks.length) {
            const stock = allStocks[newIndex];
            document.getElementById('search-input').value = '';
            document.getElementById('search-suggestions').classList.add('hidden');

            // Find the list item in sidebar and highlight it properly
            const listItems = document.querySelectorAll('#stock-list li');
            let targetLi = null;
            listItems.forEach(li => {
                if (li.textContent.includes(stock.symbol)) {
                    targetLi = li;
                }
            });

            // Reuse selectStock for consistent state updates
            selectStock(stock, targetLi);

            updateWheel();
        }
    }

    // Modal elements
    const backtestModal = document.getElementById('backtest-modal');
    const closeBtModalBtn = document.getElementById('modal-close-bt-btn');

    closeBtModalBtn.addEventListener('click', () => {
        backtestModal.classList.add('hidden');
    });

    backtestBtn.addEventListener('click', async () => {
        if (!currentStock) return;
        const symbol = currentStock.symbol;

        backtestBtn.textContent = '回测中...';
        backtestBtn.disabled = true;

        try {
            const response = await fetch(`/api/backtest/${symbol}`);
            const result = await response.json();

            if (result.error) {
                showToast(`回测失败: ${result.error}`, 'error');
                return;
            }

            // Fill Modal Summary
            document.getElementById('backtest-symbol').textContent = `${currentStock.name} (${symbol})`;
            document.getElementById('bt-initial').textContent = result.summary.initial_capital.toFixed(2);
            document.getElementById('bt-final').textContent = result.summary.final_capital.toFixed(2);

            const profitEl = document.getElementById('bt-profit');
            profitEl.textContent = `${result.summary.total_profit_pct.toFixed(2)}%`;
            profitEl.className = 'value ' + (result.summary.total_profit_pct >= 0 ? 'up' : 'down');

            document.getElementById('bt-trades').textContent = result.summary.total_trades;
            document.getElementById('bt-winrate').textContent = `${result.summary.win_rate.toFixed(2)}%`;

            // Fill Table
            const tbody = document.querySelector('#backtest-table tbody');
            tbody.innerHTML = '';

            result.trades.forEach(t => {
                const tr = document.createElement('tr');

                const profitClass = t.profit_pct >= 0 ? 'up' : 'down';

                tr.innerHTML = `
                    <td>${t.buy_date}</td>
                    <td>${t.buy_price.toFixed(2)}</td>
                    <td>${t.sell_date}</td>
                    <td>${t.sell_reason}</td>
                    <td>${t.sell_price.toFixed(2)}</td>
                    <td class="${profitClass}">${t.profit_pct.toFixed(2)}%</td>
                    <td>${t.holding_days}</td>
                    <td>${t.capital_after.toFixed(2)}</td>
                `;
                tbody.appendChild(tr);
            });

            backtestModal.classList.remove('hidden');

            // Optionally, add markers to K-Line
            // ECharts MarkPoints for Buy/Sell
            if (result.trades.length > 0 && chartInstance) {
                const markPointData = [];
                result.trades.forEach(t => {
                    markPointData.push({
                        name: 'Buy',
                        coord: [t.buy_date, t.buy_price],
                        value: '买',
                        itemStyle: { color: '#ff4d4f' },
                        symbolOffset: [0, 20],
                        symbol: 'arrow'
                    });
                    markPointData.push({
                        name: 'Sell',
                        coord: [t.sell_date, t.sell_price],
                        value: '卖',
                        itemStyle: { color: '#52c41a' },
                        symbolOffset: [0, -20],
                        symbol: 'arrow',
                        symbolRotate: 180
                    });
                });

                const option = chartInstance.getOption();
                option.series[0].markPoint = {
                    data: markPointData,
                    label: {
                        show: true,
                        color: '#fff',
                        fontSize: 10,
                        formatter: function (param) {
                            return param.value;
                        }
                    }
                };
                chartInstance.setOption(option);
            }

        } catch (error) {
            console.error('Backtest error:', error);
            showToast('请求回测数据出错', 'error');
        } finally {
            backtestBtn.textContent = '模拟回测';
            backtestBtn.disabled = false;
        }
    });


    if (wheelUpBtn) {
        wheelUpBtn.addEventListener('click', () => switchWheelStock(-1));
    }
    if (wheelDownBtn) {
        wheelDownBtn.addEventListener('click', () => switchWheelStock(1));
    }

    // Add mouse wheel support for the 3D wheel container
    if (stockWheel) {
        stockWheel.addEventListener('wheel', (e) => {
            e.preventDefault();
            if (e.deltaY > 0) {
                switchWheelStock(1); // scroll down -> next stock
            } else {
                switchWheelStock(-1); // scroll up -> prev stock
            }
        });
    }

    // Startup
    initChart();
    fetchStockList();
});
