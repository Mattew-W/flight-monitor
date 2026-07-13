/* ═══════════════════════════════════════════════════════════
   Flight Monitor - Enhanced Frontend Application
   ═══════════════════════════════════════════════════════════ */

// ── State ────────────────────────────────────────────────────
let priceChart = null;
let currentMonitorRunning = false;
let platformsData = {};
let popularRoutesData = [];

// ── Init ─────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadCities();
    loadPlatforms();
    loadPopularRoutes();
    setupNavigation();
    setupForms();
    refreshAll();
    checkMonitorStatus();
    setInterval(() => {
        if (currentMonitorRunning) refreshDashboard();
    }, 60000);
});

// ── Navigation ───────────────────────────────────────────────
function setupNavigation() {
    document.querySelectorAll(".nav-item").forEach(item => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            const page = item.dataset.page;
            document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
            document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
            item.classList.add("active");
            document.getElementById("page-" + page).classList.add("active");
            if (page === "dashboard") refreshDashboard();
            if (page === "search") loadQueries();
            if (page === "trends") loadTrendSelect();
            if (page === "alerts") { loadAlerts(); loadAlertHistory(); loadAlertQuerySelect(); }
            if (page === "platforms") renderPlatforms();
        });
    });
}

// ── API Helpers ──────────────────────────────────────────────
async function api(url, method = "GET", body = null) {
    const opts = { method, headers: {} };
    if (body) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
    }
    const resp = await fetch(url, opts);
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    return resp.json();
}

// ── Toast ────────────────────────────────────────────────────
function toast(msg, type = "") {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.className = "toast show " + type;
    setTimeout(() => el.classList.remove("show"), 3000);
}

// ── Cities ───────────────────────────────────────────────────
async function loadCities() {
    try {
        const [cities, groups] = await Promise.all([
            api("/api/cities"),
            api("/api/city-groups"),
        ]);
        const dep = document.getElementById("departure");
        const dest = document.getElementById("destination");

        // Build optgroup-based selects
        for (const [region, cityList] of Object.entries(groups)) {
            const depGroup = document.createElement("optgroup");
            depGroup.label = region;
            const destGroup = document.createElement("optgroup");
            destGroup.label = region;
            cityList.forEach(cityName => {
                depGroup.appendChild(new Option(cityName, cityName));
                destGroup.appendChild(new Option(cityName, cityName));
            });
            dep.appendChild(depGroup);
            dest.appendChild(destGroup);
        }
    } catch (e) { console.error("Failed to load cities:", e); }
}

// ── Platforms ────────────────────────────────────────────────
async function loadPlatforms() {
    try {
        const platforms = await api("/api/platforms");
        platforms.forEach(p => {
            platformsData[p.key] = p;
        });
    } catch (e) { console.error("Failed to load platforms:", e); }
}

function getPlatformInfo(key) {
    return platformsData[key] || { name: key, icon: "🎫", color: "#64748b" };
}

// ── Popular Routes ───────────────────────────────────────────
async function loadPopularRoutes() {
    try {
        popularRoutesData = await api("/api/popular-routes");
        renderPopularRoutes();
    } catch (e) { console.error("Failed to load popular routes:", e); }
}

function renderPopularRoutes() {
    const html = popularRoutesData.map(r => `
        <div class="popular-route-card" onclick="quickSelectRoute('${r.departure}', '${r.destination}')" title="${r.label}">
            <div class="popular-route-icon">✈️</div>
            <div class="popular-route-info">
                <div class="popular-route-route">${r.departure} → ${r.destination}</div>
                <div class="popular-route-label">${r.label}</div>
            </div>
        </div>
    `).join("");
    const dash = document.getElementById("popularRoutes");
    const search = document.getElementById("popularRoutesSearch");
    if (dash) dash.innerHTML = html;
    if (search) search.innerHTML = html;
}

function quickSelectRoute(dep, dest) {
    // Navigate to search page first
    document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
    document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
    document.querySelector('.nav-item[data-page="search"]').classList.add("active");
    document.getElementById("page-search").classList.add("active");

    document.getElementById("departure").value = dep;
    document.getElementById("destination").value = dest;
    document.getElementById("page-search").querySelector(".search-form").scrollIntoView({ behavior: "smooth" });
    toast(`已选择 ${dep} → ${dest}`, "");
}

// ── Swap Cities ──────────────────────────────────────────────
function swapCities() {
    const dep = document.getElementById("departure");
    const dest = document.getElementById("destination");
    const tmp = dep.value;
    dep.value = dest.value;
    dest.value = tmp;
}

// ── Forms ────────────────────────────────────────────────────
function setupForms() {
    const future = new Date();
    future.setDate(future.getDate() + 30);
    document.getElementById("departureDate").value = future.toISOString().split("T")[0];

    document.getElementById("searchForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const dep = document.getElementById("departure").value;
        const dest = document.getElementById("destination").value;
        if (dep === dest) { toast("出发城市和目的城市不能相同", "warning"); return; }
        const data = {
            departure: dep,
            destination: dest,
            departure_date: document.getElementById("departureDate").value,
            cabin_class: document.getElementById("cabinClass").value,
            trip_type: "oneway",
            is_monitoring: false,
            label: document.getElementById("label").value || `${dep}→${dest}`,
        };
        try {
            const result = await api("/api/queries", "POST", data);
            toast("正在搜索多平台航班价格...", "");
            await searchNow(result.id);
            loadQueries();
        } catch (e) { toast("创建失败: " + e.message, "error"); }
    });

    document.getElementById("alertForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = {
            query_id: parseInt(document.getElementById("alertQuerySelect").value),
            target_price: parseFloat(document.getElementById("alertTargetPrice").value),
            is_active: true,
            notify_email: true,
            notify_wechat: false,
        };
        if (!data.query_id) { toast("请选择航线", "warning"); return; }
        try {
            await api("/api/alerts", "POST", data);
            toast("价格提醒已添加！", "success");
            document.getElementById("alertTargetPrice").value = "";
            loadAlerts();
        } catch (e) { toast("添加失败: " + e.message, "error"); }
    });
}

// ── Refresh All ──────────────────────────────────────────────
function refreshAll() {
    refreshDashboard();
    loadQueries();
}

// ── Dashboard ────────────────────────────────────────────────
async function refreshDashboard() {
    try {
        const data = await api("/api/dashboard");
        document.getElementById("statQueries").textContent = data.total_queries;
        document.getElementById("statMonitoring").textContent = data.monitoring_queries;
        document.getElementById("statAlerts").textContent = data.active_alerts;
        document.getElementById("statPlatforms").textContent = data.platform_count || 0;

        const routeList = document.getElementById("routePriceList");
        if (data.route_prices.length === 0) {
            routeList.innerHTML = `
                <div class="empty-state">
                    <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#cbd5e1" stroke-width="1.5"><path d="M17.8 19.2L16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/></svg>
                    <p>暂无监控数据，请先添加监控任务</p>
                </div>`;
            document.getElementById("statLowestPrice").textContent = "--";
        } else {
            routeList.innerHTML = data.route_prices.map(p => {
                const platInfo = getPlatformInfo(p.source);
                return `
                <div class="route-price-item">
                    <div class="route-info">
                        <div>
                            <div class="route-label">${p.departure} <span class="route-arrow">→</span> ${p.destination}
                                <span class="route-platform-badge">${platInfo.icon} ${platInfo.name}</span>
                            </div>
                            <div class="route-date">${p.departure_date} ${p.label && p.label !== `${p.departure}→${p.destination}` ? "· " + p.label : ""}</div>
                        </div>
                    </div>
                    <div class="route-price">
                        <div class="route-price-value">¥${Math.round(p.price)}</div>
                        <div class="route-price-airline">${p.airline || ""}</div>
                    </div>
                </div>`;
            }).join("");
            const minAll = Math.min(...data.route_prices.map(p => p.price));
            document.getElementById("statLowestPrice").textContent = Math.round(minAll);
        }

        const alertEl = document.getElementById("recentAlerts");
        if (data.recent_alerts.length === 0) {
            alertEl.innerHTML = `
                <div class="empty-state">
                    <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#cbd5e1" stroke-width="1.5"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg>
                    <p>暂无提醒记录</p>
                </div>`;
        } else {
            alertEl.innerHTML = data.recent_alerts.map(a => `
                <div class="alert-item">
                    <div class="alert-title">✈️ ${a.departure || ""} → ${a.destination || ""} 降至 ¥${Math.round(a.price)}</div>
                    <div class="alert-detail">目标价: ¥${Math.round(a.target_price)} | ${a.airline || ""} ${a.flight_no || ""}</div>
                    <div class="alert-time">${formatTime(a.triggered_at)}</div>
                </div>
            `).join("");
        }
    } catch (e) { console.error("Dashboard error:", e); }
}

// ── Queries ──────────────────────────────────────────────────
async function loadQueries() {
    try {
        const queries = await api("/api/queries");
        const list = document.getElementById("queryList");
        if (queries.length === 0) {
            list.innerHTML = `<div class="empty-state"><p>暂无监控任务，请在上方添加</p></div>`;
        } else {
            list.innerHTML = queries.map(q => `
                <div class="query-item">
                    <div class="query-info">
                        <div>
                            <div class="query-route">${q.departure} → ${q.destination}</div>
                            <div class="query-meta">
                                <span>📅 ${q.departure_date}</span>
                                <span>💺 ${cabinLabel(q.cabin_class)}</span>
                                <span>📊 ${q.stats.total_records}条记录</span>
                                ${q.platform_count > 0 ? `<span class="query-platform-count">🔗 ${q.platform_count}个平台</span>` : ""}
                                ${q.label && q.label !== `${q.departure}→${q.destination}` ? `<span>🏷️ ${q.label}</span>` : ""}
                            </div>
                        </div>
                    </div>
                    <div class="query-actions">
                        ${q.current_min_price > 0 ? `<div class="query-price-badge">最低 ¥${Math.round(q.current_min_price)}</div>` : ""}
                        <div class="toggle ${q.is_monitoring ? "active" : ""}" onclick="toggleMonitoring(${q.id}, ${!q.is_monitoring})" title="${q.is_monitoring ? '停止监控' : '开始监控'}"></div>
                        <button class="btn btn-sm btn-ghost" onclick="searchNow(${q.id})">🔍 搜索</button>
                        <button class="btn btn-sm btn-ghost" onclick="showPricePrediction(${q.id})">📈 预测</button>
                        <button class="btn-icon danger" onclick="deleteQuery(${q.id})" title="删除">
                            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                        </button>
                    </div>
                </div>
            `).join("");
        }
        updateSelects(queries);
    } catch (e) { console.error("Load queries error:", e); }
}

function updateSelects(queries) {
    const trendSel = document.getElementById("trendQuerySelect");
    const alertSel = document.getElementById("alertQuerySelect");
    const trendVal = trendSel.value;
    const alertVal = alertSel.value;
    trendSel.innerHTML = '<option value="">选择监控任务</option>';
    alertSel.innerHTML = '<option value="">选择监控任务</option>';
    queries.forEach(q => {
        const label = `${q.departure}→${q.destination} (${q.departure_date})${q.label && q.label !== `${q.departure}→${q.destination}` ? " " + q.label : ""}`;
        trendSel.add(new Option(label, q.id));
        alertSel.add(new Option(label, q.id));
    });
    trendSel.value = trendVal;
    alertSel.value = alertVal;
}

async function toggleMonitoring(queryId, enable) {
    try {
        await api(`/api/queries/${queryId}/monitoring`, "PUT", { is_monitoring: enable });
        toast(enable ? "已开启监控" : "已停止监控", "success");
        loadQueries();
    } catch (e) { toast("操作失败", "error"); }
}

async function deleteQuery(queryId) {
    if (!confirm("确定要删除这个监控任务吗？相关历史数据也会被删除。")) return;
    try {
        await api(`/api/queries/${queryId}`, "DELETE");
        toast("已删除", "success");
        loadQueries();
        refreshDashboard();
    } catch (e) { toast("删除失败", "error"); }
}

async function searchNow(queryId) {
    const modal = document.getElementById("searchResultsModal");
    const content = document.getElementById("searchResults");
    if (modal && content) {
        modal.style.display = "flex";
        content.innerHTML = `
            <div class="search-progress">
                <div class="spinner"></div>
                <h3>正在搜索多平台航班价格</h3>
                <div class="progress-steps">
                    <div class="step active" id="step-1">
                        <span class="step-icon">1</span>
                        <span class="step-text">正在启动携程浏览器抓取真实数据...</span>
                    </div>
                    <div class="step" id="step-2">
                        <span class="step-icon">2</span>
                        <span class="step-text">抓取航班日历数据（约 15-20 秒）</span>
                    </div>
                    <div class="step" id="step-3">
                        <span class="step-icon">3</span>
                        <span class="step-text">生成 27 个平台比价数据</span>
                    </div>
                    <div class="step" id="step-4">
                        <span class="step-icon">4</span>
                        <span class="step-text">完成，正在渲染结果...</span>
                    </div>
                </div>
                <div class="progress-hint">⏱ 预计耗时 20-30 秒（包含真实数据抓取）</div>
            </div>
        `;
        // Animate progress steps while waiting
        const timers = [
            setTimeout(() => {
                const s2 = document.getElementById("step-2");
                if (s2) s2.classList.add("active");
            }, 3000),
            setTimeout(() => {
                const s3 = document.getElementById("step-3");
                if (s3) s3.classList.add("active");
            }, 18000),
        ];
        try {
            const result = await api(`/api/queries/${queryId}/search`, "POST");
            clearTimeout(timers[0]);
            clearTimeout(timers[1]);
            const s4 = document.getElementById("step-4");
            if (s4) s4.classList.add("active");
            showSearchResults(result, queryId);
            loadQueries();
            refreshDashboard();
        } catch (e) {
            clearTimeout(timers[0]);
            clearTimeout(timers[1]);
            content.innerHTML = `<div class="empty-state"><p>搜索失败: ${e.message}</p></div>`;
            toast("搜索失败: " + e.message, "error");
        }
    } else {
        // Fallback for places without searchResults modal
        toast("正在搜索多平台航班价格...", "");
        try {
            const result = await api(`/api/queries/${queryId}/search`, "POST");
            showSearchResults(result, queryId);
            loadQueries();
            refreshDashboard();
        } catch (e) { toast("搜索失败: " + e.message, "error"); }
    }
}

// ── Price Prediction ─────────────────────────────────────────
async function showPricePrediction(queryId) {
    const modal = document.getElementById("predictionModal");
    if (modal) modal.style.display = "flex";
    
    const infoEl = document.getElementById("predictionInfo");
    infoEl.innerHTML = '<div class="loading">正在分析历史价格数据...</div>';
    
    try {
        const data = await api(`/api/queries/${queryId}/predict`, "GET");
        if (data.error) {
            infoEl.innerHTML = `<div class="empty-state"><p>${data.error}</p></div>`;
            return;
        }
        renderPredictionChart(data);
    } catch (e) {
        infoEl.innerHTML = `<div class="empty-state"><p>预测加载失败: ${e.message}</p></div>`;
    }
}

function renderPredictionChart(data) {
    // Safely destroy previous chart instance
    if (window.predictionChart && typeof window.predictionChart.destroy === "function") {
        window.predictionChart.destroy();
    }
    window.predictionChart = null;
    
    // Use chart_data from backend (preferred) or fall back to chart
    const chartData = data.chart_data || data.chart || {};
    const labels = chartData.labels || [];
    const datasets = chartData.datasets || [];
    
    // Build datasets from old format if chart_data not available
    let finalDatasets = datasets;
    if (datasets.length === 0) {
        const histPrices = chartData.historical_prices || [];
        const forecastPrices = chartData.forecast_prices || [];
        const lowerBound = chartData.lower_bound || [];
        const upperBound = chartData.upper_bound || [];
        finalDatasets = [
            {
                label: "历史价格",
                data: histPrices,
                borderColor: "#2563eb",
                backgroundColor: "rgba(37,99,235,.1)",
                fill: false,
                tension: 0.3,
                pointRadius: 3,
                pointHoverRadius: 6,
                borderWidth: 2,
            },
            {
                label: "预测价格",
                data: forecastPrices,
                borderColor: "#f59e0b",
                backgroundColor: "transparent",
                fill: false,
                tension: 0.3,
                pointRadius: 0,
                pointHoverRadius: 4,
                borderWidth: 2,
                borderDash: [5, 5],
            },
            {
                label: "95%置信上限",
                data: upperBound,
                borderColor: "rgba(239,68,68,.3)",
                backgroundColor: "rgba(239,68,68,.05)",
                fill: "+1",
                tension: 0.3,
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 1,
                borderDash: [2, 4],
            },
            {
                label: "95%置信下限",
                data: lowerBound,
                borderColor: "rgba(22,163,74,.3)",
                backgroundColor: "rgba(22,163,74,.05)",
                fill: false,
                tension: 0.3,
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 1,
                borderDash: [2, 4],
            },
        ];
    }
    
    const infoEl = document.getElementById("predictionInfo");
    infoEl.innerHTML = `
        <div class="prediction-summary">
            <div class="prediction-stat">
                <div class="prediction-stat-label">当前价格</div>
                <div class="prediction-stat-value">¥${Math.round(data.current_price || 0)}</div>
            </div>
            <div class="prediction-stat">
                <div class="prediction-stat-label">历史最低</div>
                <div class="prediction-stat-value">¥${Math.round(data.historical_min || 0)}</div>
            </div>
            <div class="prediction-stat highlight">
                <div class="prediction-stat-label">预测最低</div>
                <div class="prediction-stat-value">¥${Math.round(data.predicted_min || 0)}</div>
                <div class="prediction-stat-sub">${data.predicted_min_date || ''}</div>
            </div>
            <div class="prediction-stat">
                <div class="prediction-stat-label">距起飞</div>
                <div class="prediction-stat-value">${data.days_until_departure || 0} 天</div>
            </div>
        </div>
        <div class="prediction-model">📊 模型：${data.model || '未知'} · 置信区间：${data.confidence_interval || 'N/A'} · 数据点：${data.data_points || 0}</div>
        <div class="prediction-source">数据来源：携程旅行网公开最低价日历接口 (m.ctrip.com/restapi/soa2/19691/getLowestPriceCalendar)</div>
    `;
    
    const ctx = document.getElementById("predictionChart").getContext("2d");
    window.predictionChart = new Chart(ctx, {
        type: "line",
        data: {
            labels,
            datasets: finalDatasets,
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { position: "bottom", labels: { usePointStyle: true, padding: 20 } },
                tooltip: {
                    backgroundColor: "rgba(30,41,59,.95)",
                    padding: 12,
                    callbacks: { label: (ctx) => `${ctx.dataset.label}: ¥${Math.round(ctx.parsed.y || 0)}` },
                },
            },
            scales: {
                x: { grid: { color: "#f1f5f9" }, ticks: { color: "#94a3b8", font: { size: 11 }, maxTicksLimit: 12 } },
                y: { 
                    grid: { color: "#f1f5f9" }, 
                    ticks: { color: "#94a3b8", font: { size: 11 }, callback: (v) => "¥" + v },
                },
            },
        },
    });
}

// ── Search Results (Multi-Platform Comparison) ───────────────
function showSearchResults(result, queryId) {
    const modal = document.getElementById("searchResultsModal");
    const content = document.getElementById("searchResults");

    if (!result || !result.flights || result.flights.length === 0) {
        content.innerHTML = `<div class="empty-state"><p>未找到航班数据</p></div>`;
        modal.style.display = "flex";
        return;
    }

    // Build platform tags
    const platformTags = (result.platforms || []).map(p => {
        const info = getPlatformInfo(p);
        return `<span class="platform-tag" style="background:${info.color}15;color:${info.color};">${info.icon} ${info.name}</span>`;
    }).join("");

    content.innerHTML = `
        <div class="search-summary">
            <span class="search-summary-count">共 ${result.count} 个航班</span>
            <span class="search-summary-price">最低价 ¥${Math.round(result.min_price)}</span>
            <div class="search-summary-platforms">${platformTags}</div>
            <button class="btn btn-sm btn-primary" onclick="showPricePrediction(${queryId})" style="margin-left:auto;">
                📈 价格预测
            </button>
        </div>
        <div id="flightResultsList">
            ${result.flights.map(f => renderFlightCard(f)).join("")}
        </div>
    `;
    modal.style.display = "flex";
}

function renderFlightCard(f) {
    const platPrices = f.platform_prices || [];
    const cheapestPlat = platPrices.length > 0 ? platPrices[0] : null;

    return `
        <div class="flight-result-card">
            <div class="flight-result-main">
                <div class="flight-airline-info">
                    <div class="flight-airline-logo">✈️</div>
                    <div>
                        <div class="flight-airline-name">${f.airline}</div>
                        <div class="flight-airline-no">${f.flight_no} · ${f.aircraft}</div>
                    </div>
                </div>
                <div class="flight-time-info">
                    <div class="flight-time-block">
                        <div class="flight-time">${f.departure_time || "时间待确认"}</div>
                        <div class="flight-airport">${f.departure_airport}</div>
                    </div>
                    <div class="flight-duration-block">
                        <div class="flight-duration">${f.duration || "—"}</div>
                        <div class="flight-duration-line"></div>
                        <div class="flight-duration">
                            <span class="stops-badge ${f.stops === 0 ? 'direct' : 'transfer'}">${f.stops === 0 ? '直飞' : f.stops + '中转'}</span>
                        </div>
                    </div>
                    <div class="flight-time-block">
                        <div class="flight-time">${f.arrival_time || "—"}</div>
                        <div class="flight-airport">${f.arrival_airport}</div>
                    </div>
                </div>
                <div class="flight-price-block">
                    <div class="flight-price-main">¥${Math.round(f.price)}</div>
                    <div class="flight-price-label">${cheapestPlat ? cheapestPlat.platform_name : ''}</div>
                </div>
            </div>
            ${platPrices.length > 1 ? `
            <div class="platform-prices">
                ${platPrices.map((pp, idx) => `
                    <a href="${pp.purchase_url}" target="_blank" rel="noopener" class="platform-price-item ${idx === 0 ? 'cheapest' : ''}">
                        <div class="platform-price-left">
                            <span class="platform-price-icon">${pp.platform_icon}</span>
                            <span class="platform-price-name">${pp.platform_name}</span>
                            ${idx === 0 ? '<span class="platform-cheapest-tag">最低</span>' : ''}
                        </div>
                        <span class="platform-price-value ${idx === 0 ? 'cheapest' : ''}">¥${Math.round(pp.price)}</span>
                    </a>
                `).join("")}
            </div>
            ` : platPrices.length === 1 ? `
            <div class="platform-prices">
                <a href="${platPrices[0].purchase_url}" target="_blank" rel="noopener" class="platform-price-item cheapest">
                    <div class="platform-price-left">
                        <span class="platform-price-icon">${platPrices[0].platform_icon}</span>
                        <span class="platform-price-name">${platPrices[0].platform_name}</span>
                        <span class="platform-cheapest-tag">最低</span>
                    </div>
                    <span class="platform-price-value cheapest">¥${Math.round(platPrices[0].price)} → 去购买</span>
                </a>
            </div>
            ` : f.purchase_url ? `
            <div class="platform-prices">
                <a href="${f.purchase_url}" target="_blank" rel="noopener" class="platform-price-item cheapest">
                    <div class="platform-price-left">
                        <span class="platform-price-icon">🎫</span>
                        <span class="platform-price-name">${getPlatformInfo(f.source).name}</span>
                    </div>
                    <span class="platform-price-value cheapest">¥${Math.round(f.price)} → 去购买</span>
                </a>
            </div>
            ` : ''}
        </div>
    `;
}

function closeModal(id) {
    document.getElementById(id).style.display = "none";
}

// ── Export Data ──────────────────────────────────────────────
function exportAllData() {
    window.open("/api/export", "_blank");
    toast("正在导出数据...", "");
}

// ── Trends ───────────────────────────────────────────────────
async function loadTrendSelect() {
    const sel = document.getElementById("trendQuerySelect");
    if (sel.value) loadTrendChart();
}

async function loadTrendChart() {
    const queryId = document.getElementById("trendQuerySelect").value;
    if (!queryId) return;
    try {
        const [history, stats, prices] = await Promise.all([
            api(`/api/queries/${queryId}/history?limit=200`),
            api(`/api/queries/${queryId}/stats`),
            api(`/api/queries/${queryId}/prices`),
        ]);
        renderChart(history);
        renderTrendStats(stats);
        renderTrendFlights(prices);
    } catch (e) { toast("加载趋势数据失败", "error"); }
}

function renderChart(history) {
    const ctx = document.getElementById("priceChart").getContext("2d");
    if (priceChart && typeof priceChart.destroy === "function") priceChart.destroy();

    const labels = history.map(h => formatTime(h.recorded_at, true));
    const minData = history.map(h => h.min_price);
    const avgData = history.map(h => h.avg_price);
    const maxData = history.map(h => h.max_price);

    priceChart = new Chart(ctx, {
        type: "line",
        data: {
            labels,
            datasets: [
                { label: "最低价", data: minData, borderColor: "#2563eb", backgroundColor: "rgba(37,99,235,.1)", fill: true, tension: 0.3, pointRadius: 3, pointHoverRadius: 6, borderWidth: 2 },
                { label: "平均价", data: avgData, borderColor: "#f59e0b", backgroundColor: "transparent", tension: 0.3, pointRadius: 2, borderWidth: 2, borderDash: [5, 5] },
                { label: "最高价", data: maxData, borderColor: "#ef4444", backgroundColor: "transparent", tension: 0.3, pointRadius: 2, borderWidth: 1.5, borderDash: [2, 4] },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "rgba(30,41,59,.95)",
                    padding: 12, titleFont: { size: 13 }, bodyFont: { size: 13 },
                    callbacks: { label: (ctx) => `${ctx.dataset.label}: ¥${Math.round(ctx.parsed.y)}` },
                },
            },
            scales: {
                x: { grid: { color: "#f1f5f9" }, ticks: { color: "#94a3b8", font: { size: 11 }, maxTicksLimit: 10 } },
                y: { grid: { color: "#f1f5f9" }, ticks: { color: "#94a3b8", font: { size: 11 }, callback: (v) => "¥" + v } },
            },
        },
    });
}

function renderTrendStats(stats) {
    document.getElementById("trendStatsCard").style.display = "block";
    const minP = isFinite(stats.min_price) ? Math.round(stats.min_price) : '--';
    const avgP = isFinite(stats.avg_price) ? Math.round(stats.avg_price) : '--';
    const maxP = isFinite(stats.max_price) ? Math.round(stats.max_price) : '--';
    const totalP = isFinite(stats.total_records) ? stats.total_records : 0;
    document.getElementById("trendStats").innerHTML = `
        <div class="stat-card">
            <div class="stat-icon" style="background:linear-gradient(135deg,#dcfce7,#bbf7d0);color:#16a34a;">
                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            </div>
            <div class="stat-info"><div class="stat-value">¥${minP}</div><div class="stat-label">历史最低</div></div>
        </div>
        <div class="stat-card">
            <div class="stat-icon" style="background:linear-gradient(135deg,#fef3c7,#fde68a);color:#d97706;">
                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></svg>
            </div>
            <div class="stat-info"><div class="stat-value">¥${avgP}</div><div class="stat-label">平均价格</div></div>
        </div>
        <div class="stat-card">
            <div class="stat-icon" style="background:linear-gradient(135deg,#fef2f2,#fee2e2);color:#dc2626;">
                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
            </div>
            <div class="stat-info"><div class="stat-value">¥${maxP}</div><div class="stat-label">历史最高</div></div>
        </div>
        <div class="stat-card">
            <div class="stat-icon" style="background:linear-gradient(135deg,#dbeafe,#bfdbfe);color:#2563eb;">
                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/></svg>
            </div>
            <div class="stat-info"><div class="stat-value">${totalP}</div><div class="stat-label">价格记录数</div></div>
        </div>
    `;
}

function renderTrendFlights(prices) {
    const card = document.getElementById("trendFlightsCard");
    const content = document.getElementById("trendFlights");
    if (prices.length === 0) {
        card.style.display = "none";
        return;
    }
    card.style.display = "block";

    // Group by flight to show platform comparison
    const grouped = {};
    prices.forEach(p => {
        const key = `${p.airline}_${p.flight_no}_${p.departure_time}`;
        if (!grouped[key] || p.price < grouped[key].price) {
            grouped[key] = p;
        }
    });
    const flights = Object.values(grouped).sort((a, b) => a.price - b.price);

    content.innerHTML = `
        <table class="flight-table">
            <thead>
                <tr><th>航空公司</th><th>航班号</th><th>出发</th><th>到达</th><th>航程</th><th>经停</th><th>价格</th><th>来源</th><th>购买</th></tr>
            </thead>
            <tbody>
                ${flights.map(f => {
                    const info = getPlatformInfo(f.source);
                    return `
                    <tr>
                        <td><span class="airline-badge">${f.airline}</span></td>
                        <td>${f.flight_no}</td>
                        <td>${f.departure_time}<br><small style="color:var(--text-muted);">${f.departure_airport}</small></td>
                        <td>${f.arrival_time}<br><small style="color:var(--text-muted);">${f.arrival_airport}</small></td>
                        <td>${f.duration}</td>
                        <td><span class="stops-badge ${f.stops === 0 ? 'direct' : 'transfer'}">${f.stops === 0 ? '直飞' : f.stops + '中转'}</span></td>
                        <td class="price-cell">¥${Math.round(f.price)}</td>
                        <td><span class="platform-tag" style="background:${info.color}15;color:${info.color};">${info.icon} ${info.name}</span></td>
                        <td>${f.purchase_url ? `<a href="${f.purchase_url}" target="_blank" rel="noopener" class="btn btn-sm btn-primary">去购买</a>` : ''}</td>
                    </tr>`;
                }).join("")}
            </tbody>
        </table>
    `;
}

async function refreshTrendFlights() {
    const queryId = document.getElementById("trendQuerySelect").value;
    if (!queryId) return;
    toast("正在搜索最新价格...", "");
    try {
        await api(`/api/queries/${queryId}/search`, "POST");
        toast("价格已更新！", "success");
        loadTrendChart();
    } catch (e) { toast("刷新失败", "error"); }
}

// ── Alerts ───────────────────────────────────────────────────
async function loadAlerts() {
    try {
        const alerts = await api("/api/alerts");
        const list = document.getElementById("alertList");
        if (alerts.length === 0) {
            list.innerHTML = `<div class="empty-state"><p>暂无价格提醒</p></div>`;
            return;
        }
        list.innerHTML = alerts.map(a => `
            <div class="alert-config-item">
                <div class="alert-config-info">
                    <div class="alert-config-route">${a.query_route} ${a.query_label && a.query_label !== a.query_route ? "· " + a.query_label : ""}</div>
                    <div class="alert-config-detail">
                        目标价 ¥${Math.round(a.target_price)}
                        ${a.last_triggered ? " · 上次触发: " + formatTime(a.last_triggered) : ""}
                    </div>
                </div>
                <div class="alert-config-actions">
                    <span class="badge ${a.is_active ? 'badge-active' : 'badge-inactive'}">${a.is_active ? '活跃' : '已暂停'}</span>
                    <div class="toggle ${a.is_active ? "active" : ""}" onclick="toggleAlert(${a.id}, ${!a.is_active})"></div>
                    <button class="btn-icon danger" onclick="deleteAlert(${a.id})">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                    </button>
                </div>
            </div>
        `).join("");
    } catch (e) { console.error("Load alerts error:", e); }
}

async function loadAlertHistory() {
    try {
        const history = await api("/api/alerts/history");
        const list = document.getElementById("alertHistoryList");
        if (history.length === 0) {
            list.innerHTML = `<div class="empty-state"><p>暂无提醒记录</p></div>`;
            return;
        }
        list.innerHTML = history.map(h => `
            <div class="alert-item">
                <div class="alert-title">✈️ ${h.departure || ""} → ${h.destination || ""} 降价至 ¥${Math.round(h.price)}</div>
                <div class="alert-detail">
                    目标价: ¥${Math.round(h.target_price)}
                    | ${h.airline || ""} ${h.flight_no || ""}
                    | 日期: ${h.departure_date || ""}
                </div>
                <div class="alert-time">${formatTime(h.triggered_at)}</div>
            </div>
        `).join("");
    } catch (e) { console.error("Load alert history error:", e); }
}

async function loadAlertQuerySelect() {
    await loadQueries();
}

async function toggleAlert(alertId, enable) {
    try {
        await api(`/api/alerts/${alertId}`, "PUT", { is_active: enable });
        loadAlerts();
    } catch (e) { toast("操作失败", "error"); }
}

async function deleteAlert(alertId) {
    if (!confirm("确定要删除这个价格提醒吗？")) return;
    try {
        await api(`/api/alerts/${alertId}`, "DELETE");
        toast("已删除", "success");
        loadAlerts();
    } catch (e) { toast("删除失败", "error"); }
}

// ── Platforms Page ───────────────────────────────────────────
function renderPlatforms() {
    const domesticOtaKeys = ["ctrip", "qunar", "fliggy", "tongcheng"];
    const intlOtaKeys = ["tripcom", "skyscanner", "googleflights", "kayak", "expedia"];
    const domesticAirlineKeys = ["airchina", "csair", "ceair", "hainan", "spring", "juneyao"];
    const intlAirlineKeys = ["jal", "ana", "koreanair", "singapore", "emirates", "qatar", "lufthansa", "cathaypacific"];

    function buildPlatformCard(key) {
        const info = getPlatformInfo(key);
        return `
            <a href="#" onclick="return false" class="platform-card">
                <div class="platform-card-icon" style="background:${info.color}15;">${info.icon}</div>
                <div class="platform-card-info">
                    <div class="platform-card-name">${info.name}</div>
                    <div class="platform-card-type">点击搜索时自动比价</div>
                </div>
                <div class="platform-card-arrow">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
            </a>
        `;
    }

    const otaEl = document.getElementById("otaPlatforms");
    otaEl.innerHTML = `
        <div class="platform-section-title">国内 OTA 平台</div>
        ${domesticOtaKeys.map(buildPlatformCard).join("")}
        <div class="platform-section-title">国际 OTA 平台</div>
        ${intlOtaKeys.map(buildPlatformCard).join("")}
    `;

    const airlineEl = document.getElementById("airlinePlatforms");
    airlineEl.innerHTML = `
        <div class="platform-section-title">国内航空公司官网</div>
        ${domesticAirlineKeys.map(buildPlatformCard).join("")}
        <div class="platform-section-title">国际航空公司官网</div>
        ${intlAirlineKeys.map(buildPlatformCard).join("")}
    `;
}

// ── Monitor Control ──────────────────────────────────────────
async function checkMonitorStatus() {
    try {
        const status = await api("/api/monitor/status");
        updateMonitorUI(status.running);
    } catch (e) { console.error("Monitor status error:", e); }
}

function updateMonitorUI(running) {
    currentMonitorRunning = running;
    const dot = document.querySelector(".status-dot");
    const text = document.querySelector("#monitorStatus span");
    const btn = document.getElementById("toggleMonitorBtn");
    if (running) {
        dot.classList.remove("stopped");
        dot.classList.add("running");
        text.textContent = "监控运行中";
        btn.classList.add("running");
        btn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg><span>停止监控</span>';
    } else {
        dot.classList.remove("running");
        dot.classList.add("stopped");
        text.textContent = "监控未运行";
        btn.classList.remove("running");
        btn.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg><span>启动监控</span>';
    }
}

async function toggleMonitor() {
    try {
        if (currentMonitorRunning) {
            await api("/api/monitor/stop", "POST");
            toast("监控已停止", "warning");
        } else {
            const queries = await api("/api/queries");
            const monitoring = queries.filter(q => q.is_monitoring);
            if (monitoring.length === 0) {
                toast("请先添加并开启监控任务", "warning");
                return;
            }
            await api("/api/monitor/start", "POST");
            toast("监控已启动！", "success");
        }
        checkMonitorStatus();
    } catch (e) { toast("操作失败", "error"); }
}

// ── Helpers ──────────────────────────────────────────────────
function cabinLabel(cabin) {
    return { economy: "经济舱", business: "商务舱", first: "头等舱" }[cabin] || cabin;
}

function formatTime(iso, short = false) {
    if (!iso) return "";
    try {
        const d = new Date(iso);
        if (short) {
            return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
        }
        return `${d.getFullYear()}-${(d.getMonth() + 1).toString().padStart(2, "0")}-${d.getDate().toString().padStart(2, "0")} ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
    } catch { return iso; }
}
