/* ═══════════════════════════════════════════════════════════
   Flight Monitor - Enhanced Frontend Application v2.1
   ═══════════════════════════════════════════════════════════ */

// ── State ────────────────────────────────────────────────────
let priceChart = null;
let currentMonitorRunning = false;
let platformsData = {};
let popularRoutesData = [];
let dashboardDataCache = null;  // cached for freshness tracking
let lastDashboardUpdate = null;
let searchFilters = { stops: "all", time: "all", priceMin: null, priceMax: null };
let currentSearchResults = null;  // cached for filtering

// ── Performance: Request Cache ────────────────────────────────
const _apiCache = new Map();
const _apiCacheTTL = 30000; // 30 seconds cache for semi-static data
function cachedApi(url, ttl = _apiCacheTTL) {
    const now = Date.now();
    if (_apiCache.has(url)) {
        const { data, ts } = _apiCache.get(url);
        if (now - ts < ttl) return Promise.resolve(data);
    }
    return api(url).then(data => {
        _apiCache.set(url, { data, ts: now });
        return data;
    });
}
function invalidateApiCache(url) {
    if (url) _apiCache.delete(url);
    else _apiCache.clear();
}

// ── Security helpers ──────────────────────────────────────────
function escapeHTML(str) {
    if (str == null) return "";
    return String(str)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function safeURL(url) {
    if (!url) return "#";
    try {
        const u = new URL(url, window.location.origin);
        if (u.protocol === "http:" || u.protocol === "https:") return u.href;
    } catch (_) {}
    return "#";
}

// ── Theme Management ─────────────────────────────────────────
function initTheme() {
    const saved = localStorage.getItem("theme");
    if (saved) {
        document.documentElement.setAttribute("data-theme", saved);
    }
    updateThemeUI(saved || "auto");
}

function toggleTheme() {
    const current = localStorage.getItem("theme") || "auto";
    let next;
    if (current === "auto") next = "dark";
    else if (current === "dark") next = "light";
    else next = "auto";
    
    if (next === "auto") {
        localStorage.removeItem("theme");
        document.documentElement.removeAttribute("data-theme");
    } else {
        localStorage.setItem("theme", next);
        document.documentElement.setAttribute("data-theme", next);
    }
    updateThemeUI(next);
    toast(next === "dark" ? "已切换暗色模式" : next === "light" ? "已切换亮色模式" : "已跟随系统", "info");
}

function updateThemeUI(mode) {
    const icon = document.getElementById("themeIcon");
    const label = document.getElementById("themeLabel");
    if (!icon || !label) return;
    if (mode === "dark") {
        icon.innerHTML = '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';
        label.textContent = "亮色";
    } else if (mode === "light") {
        icon.innerHTML = '<path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>';
        label.textContent = "暗色";
    } else {
        icon.innerHTML = '<rect x="2" y="2" width="20" height="20" rx="5"/><path d="M12 8v8"/><path d="M8 12h8"/>';
        label.textContent = "跟随";
    }
}

// ── Mobile Menu ──────────────────────────────────────────────
function toggleMobileMenu() {
    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("sidebarOverlay");
    const isOpen = sidebar.classList.contains("open");
    if (isOpen) {
        sidebar.classList.remove("open");
        overlay.classList.remove("show");
        document.body.style.overflow = "";
    } else {
        sidebar.classList.add("open");
        overlay.classList.add("show");
        document.body.style.overflow = "hidden";
    }
}

// ── Skeleton Loading ─────────────────────────────────────────
function showSkeleton(containerId, count = 3) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = Array(count).fill('<div class="skeleton skeleton-card"></div>').join("");
}

// ── Init ─────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    setupNavigation();
    setupForms();
    setupKeyboardNav();
    setupFilterBar();
    
    // Parallel load all independent data sources
    const essential = Promise.all([
        loadCities(),
        loadPlatforms(),
        loadPopularRoutes(),
        checkMonitorStatus(),
    ]);
    
    // Defer non-critical dashboard data to after first paint
    essential.then(() => {
        // Use requestIdleCallback or setTimeout to avoid blocking first paint
        if (window.requestIdleCallback) {
            requestIdleCallback(() => refreshAll(), { timeout: 2000 });
        } else {
            setTimeout(refreshAll, 0);
        }
    });
    
    // Background refresh when monitor is running
    setInterval(() => {
        if (currentMonitorRunning) { refreshDashboard(); loadDashboardQueries(); }
    }, 60000);
    // Update freshness indicator every 30s
    setInterval(updateFreshnessIndicator, 30000);
});

// ── Keyboard Navigation ──────────────────────────────────────
function setupKeyboardNav() {
    document.querySelectorAll(".nav-item").forEach(item => {
        item.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                item.click();
            }
        });
    });
    // Close modal on Escape
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            document.querySelectorAll(".modal").forEach(m => m.style.display = "none");
            // Also close mobile menu
            document.getElementById("sidebar").classList.remove("open");
            document.getElementById("sidebarOverlay").classList.remove("show");
        }
    });
    
    // Click outside modal to close
    document.querySelectorAll(".modal").forEach(modal => {
        modal.addEventListener("click", (e) => {
            if (e.target === modal) modal.style.display = "none";
        });
    });
}

// ── Navigation ───────────────────────────────────────────────
function setupNavigation() {
    document.querySelectorAll(".nav-item").forEach(item => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            const page = item.dataset.page;
            
            // Update ARIA attributes
            document.querySelectorAll(".nav-item").forEach(n => {
                n.classList.remove("active");
                n.setAttribute("aria-selected", "false");
            });
            document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
            
            item.classList.add("active");
            item.setAttribute("aria-selected", "true");
            document.getElementById("page-" + page).classList.add("active");
            
            // Close mobile menu
            document.getElementById("sidebar").classList.remove("open");
            document.getElementById("sidebarOverlay").classList.remove("show");
            document.body.style.overflow = "";
            
            // Smooth scroll to top
            window.scrollTo({ top: 0, behavior: "smooth" });
            
            // Lazy load page data
            if (page === "dashboard") { refreshDashboard(); loadDashboardQueries(); }
            if (page === "search") loadQueries();
            if (page === "trends") loadTrendSelect();
            if (page === "alerts") { loadAlerts(); loadAlertHistory(); }
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

// ── Toast Stack ──────────────────────────────────────────────
let toastIdCounter = 0;
function toast(msg, type = "", duration = 3500) {
    const container = document.getElementById("toastContainer");
    if (!container) return;
    const id = "toast-" + (++toastIdCounter);
    const icons = { success: "✓", error: "✕", warning: "!", info: "i", "" : "•" };
    const item = document.createElement("div");
    item.className = "toast-item " + (type || "info");
    item.id = id;
    item.innerHTML = `<span class="toast-icon">${icons[type] || icons[""]}</span>
        <span class="toast-msg">${escapeHTML(msg)}</span>
        <span class="toast-close" onclick="document.getElementById('${id}').remove()">×</span>`;
    container.appendChild(item);
    // Animate in
    requestAnimationFrame(() => {
        requestAnimationFrame(() => { item.classList.add("show"); });
    });
    // Auto-remove
    setTimeout(() => {
        const el = document.getElementById(id);
        if (el) {
            el.classList.remove("show");
            setTimeout(() => el.remove(), 350);
        }
    }, duration);
    // Click to dismiss
    item.addEventListener("click", (e) => {
        if (e.target.classList.contains("toast-close")) return;
        item.classList.remove("show");
        setTimeout(() => item.remove(), 350);
    });
}

// ── Cities ───────────────────────────────────────────────────
async function loadCities() {
    try {
        const [cities, groups] = await Promise.all([
            cachedApi("/api/cities", 300000),   // cache 5 min
            cachedApi("/api/city-groups", 300000),
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
        const platforms = await cachedApi("/api/platforms", 300000); // cache 5 min
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
        popularRoutesData = await cachedApi("/api/popular-routes", 300000); // cache 5 min
        renderPopularRoutes();
    } catch (e) { console.error("Failed to load popular routes:", e); }
}

function renderPopularRoutes() {
    const dash = document.getElementById("popularRoutes");
    const search = document.getElementById("popularRoutesSearch");
    function buildCard(r) {
        const card = document.createElement("div");
        card.className = "popular-route-card";
        card.title = r.label || "";
        card.addEventListener("click", () => quickSelectRoute(r.departure, r.destination));
        card.innerHTML = `<div class="popular-route-icon">✈️</div>`;
        const info = document.createElement("div");
        info.className = "popular-route-info";
        const route = document.createElement("div");
        route.className = "popular-route-route";
        route.textContent = `${r.departure} → ${r.destination}`;
        const label = document.createElement("div");
        label.className = "popular-route-label";
        label.textContent = r.label || "";
        info.appendChild(route);
        info.appendChild(label);
        card.appendChild(info);
        return card;
    }
    if (dash) { dash.innerHTML = ""; popularRoutesData.forEach(r => dash.appendChild(buildCard(r))); }
    if (search) { search.innerHTML = ""; popularRoutesData.forEach(r => search.appendChild(buildCard(r))); }
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

let quickChart = null;
let quickFlightData = null;  // cached flight lookup result

// ── Batch Selection State ────────────────────────────────────
let selectedQueryIds = new Set();
let selectedAlertIds = new Set();

async function lookupFlight(flightNo) {
    if (!flightNo || flightNo.length < 4) return null;
    try {
        const res = await api("/api/flight/" + flightNo.toUpperCase());
        return res;
    } catch (e) { return null; }
}

async function fetchLivePrice() {
    if (!quickFlightData || !quickFlightData.found) { toast("请先输入正确的航班号", "warning"); return; }
    const date = document.getElementById("qpDate").value;
    const cabin = document.getElementById("qpCabin").value;
    if (!date) { toast("请选择日期", "warning"); return; }
    toast("正在通过 Bing 搜索实时价格...", "");
    try {
        const dep = quickFlightData.dep_city;
        const arr = quickFlightData.arr_city;
        // Try Bing search first
        const r = await api("/api/flight/bing?dep=" + encodeURIComponent(dep) + "&arr=" + encodeURIComponent(arr) + "&date=" + date + "&cabin=" + cabin);
        if (r.found && r.min_price) {
            document.getElementById("qpPrice").value = Math.round(r.min_price);
            toast("Bing 实时价格已填入: ¥" + Math.round(r.min_price) + " (共" + r.count + "条结果)", "success");
        } else {
            // Fallback to Ctrip calendar API
            toast("Bing 未找到，尝试携程接口...", "");
            const depCode = quickFlightData.dep_airport || dep;
            const arrCode = quickFlightData.arr_airport || arr;
            const r2 = await api("/api/flight/live?dep=" + depCode + "&arr=" + arrCode + "&date=" + date + "&cabin=" + cabin);
            if (r2.found && r2.price) {
                document.getElementById("qpPrice").value = Math.round(r2.price);
                toast("携程价格已填入: ¥" + Math.round(r2.price), "success");
            } else {
                toast("未拉到实时价格，请手动填写 | " + (r.error || ""), "warning");
            }
        }
    } catch (e) { toast("拉价失败: " + e.message, "error"); }
}

async function onFlightNoInput() {
    const fn = document.getElementById("qpFlightNo").value.trim().toUpperCase();
    const infoEl = document.getElementById("qpFlightInfo");
    const infoText = document.getElementById("qpFlightInfoText");
    const depGroup = document.getElementById("qpDepGroup");
    const arrGroup = document.getElementById("qpArrGroup");
    if (fn.length < 4) {
        infoEl.style.display = "none";
        depGroup.style.display = "none";
        arrGroup.style.display = "none";
        quickFlightData = null;
        return;
    }
    // Debounce lookup
    setTimeout(async () => {
        const currentFn = document.getElementById("qpFlightNo").value.trim().toUpperCase();
        if (currentFn !== fn) return; // input changed
        quickFlightData = await lookupFlight(fn);
        if (quickFlightData && quickFlightData.found) {
            const f = quickFlightData;
            infoText.textContent = `${f.airline} ${f.flight_no} | ${f.dep_city}(${f.departure_time}) -> ${f.arr_city}(${f.arrival_time}) | ${f.aircraft} | ${Math.floor(f.duration_min / 60)}h${f.duration_min % 60}m`;
            infoEl.style.display = "flex";
            depGroup.style.display = "none";
            arrGroup.style.display = "none";
            document.getElementById("qpDeparture").value = f.dep_city || "";
            document.getElementById("qpDestination").value = f.arr_city || "";
            autoFetchBingPrice();
        } else {
            // Not in local DB — try Bing route lookup
            infoText.textContent = "正在Bing搜索航班航线信息...";
            infoEl.style.display = "flex";
            depGroup.style.display = "none";
            arrGroup.style.display = "none";
            const bingResult = await api("/api/flight/bing_route?flight_no=" + encodeURIComponent(fn));
            if (bingResult && bingResult.found) {
                // Bing found the route!
                const cachedTag = bingResult._cached ? " (来自缓存)" : " (Bing实时搜索)";
                infoText.textContent = `${bingResult.airline || fn} ${fn} | ${bingResult.dep_city} -> ${bingResult.arr_city}${cachedTag}`;
                document.getElementById("qpDeparture").value = bingResult.dep_city || "";
                document.getElementById("qpDestination").value = bingResult.arr_city || "";
                depGroup.style.display = "none";
                arrGroup.style.display = "none";
                quickFlightData = {
                    found: true,
                    airline: bingResult.airline || fn,
                    flight_no: fn,
                    dep_city: bingResult.dep_city,
                    arr_city: bingResult.arr_city,
                    departure_time: "",
                    arrival_time: "",
                    aircraft: "",
                    duration_min: 150,
                };
                autoFetchBingPrice();
            } else {
                // Neither local DB nor Bing found it
                infoText.textContent = "航班号未找到，请手动输入出发地和目的地";
                depGroup.style.display = "";
                arrGroup.style.display = "";
                document.getElementById("qpDeparture").placeholder = "出发地";
                document.getElementById("qpDestination").placeholder = "目的地";
                document.getElementById("qpPrice").placeholder = "请手动填写价格";
            }
        }
    }, 400);
}

async function autoFetchBingPrice() {
    if (!quickFlightData || !quickFlightData.found) return;
    const date = document.getElementById("qpDate").value;
    if (!date) return;
    const dep = quickFlightData.dep_city;
    const arr = quickFlightData.arr_city;
    const cabin = document.getElementById("qpCabin").value;
    const priceInput = document.getElementById("qpPrice");
    // Show loading indicator
    priceInput.placeholder = "Bing搜索中...";
    try {
        const r = await api("/api/flight/bing?dep=" + encodeURIComponent(dep) + "&arr=" + encodeURIComponent(arr) + "&date=" + date + "&cabin=" + cabin);
        if (r.found && r.min_price) {
            priceInput.value = Math.round(r.min_price);
            priceInput.placeholder = "如 450";
            toast("✅ Bing 自动填入: ¥" + Math.round(r.min_price) + " (" + r.count + "条结果)", "success");
        } else {
            // Fallback to Ctrip
            const depCode = quickFlightData.dep_airport || dep;
            const arrCode = quickFlightData.arr_airport || arr;
            const r2 = await api("/api/flight/live?dep=" + depCode + "&arr=" + arrCode + "&date=" + date + "&cabin=" + cabin);
            if (r2.found && r2.price) {
                priceInput.value = Math.round(r2.price);
                priceInput.placeholder = "如 450";
                toast("✅ 携程自动填入: ¥" + Math.round(r2.price), "success");
            } else {
                priceInput.placeholder = "未搜到价格，请手动填写";
            }
        }
    } catch (e) {
        priceInput.placeholder = "搜索失败，请手动填写";
    }
}

async function doQuickPredict(e) {
    e.preventDefault();
    const fn = document.getElementById("qpFlightNo").value.trim().toUpperCase();
    const depDate = document.getElementById("qpDate").value;
    const price = parseFloat(document.getElementById("qpPrice").value);
    if (!fn || !depDate || !price) { toast("请填写完整信息", "warning"); return; }

    // Get departure/destination: DB auto-fill or manual input
    let departure, destination, flightInfo;
    if (quickFlightData && quickFlightData.found) {
        departure = quickFlightData.dep_city;
        destination = quickFlightData.arr_city;
        flightInfo = quickFlightData;
    } else {
        departure = document.getElementById("qpDeparture").value.trim();
        destination = document.getElementById("qpDestination").value.trim();
        if (!departure || !destination) {
            toast("航班号未找到，请手动输入出发地和目的地", "warning"); return;
        }
        flightInfo = {
            found: true,
            airline: fn,
            flight_no: fn,
            dep_city: departure,
            arr_city: destination,
            departure_time: "--",
            arrival_time: "--",
            aircraft: "--",
            duration_min: 150,
        };
    }

    toast("正在生成预测...", "");
    try {
        const data = {
            departure: departure,
            destination: destination,
            departure_date: depDate,
            price: price,
            cabin: document.getElementById("qpCabin").value,
        };
        const result = await api("/api/predict/manual", "POST", data);
        // Attach flight info
        result.flight_info = flightInfo;
        document.getElementById("quickResultCard").style.display = "block";
        renderQuickResult(result);
    } catch (e) { toast("预测失败: " + e.message, "error"); }
}

function renderQuickResult(data) {
    const info = document.getElementById("quickResultInfo");
    const buyClass = (data.best_buy_window || "").includes("立即") || (data.best_buy_window || "").includes("尽快") ? "buy-now"
        : (data.best_buy_window || "").includes("最佳") || (data.best_buy_window || "").includes("促销") ? "wait"
        : (data.best_buy_window || "").includes("观望") ? "watch" : "none";
    // Flight info line
    let flightLine = "";
    if (data.flight_info) {
        const f = data.flight_info;
        flightLine = `<div style="margin-bottom:12px;font-size:13px;color:var(--text-secondary);">
            ${escapeHTML(f.airline)} ${escapeHTML(f.flight_no)} | ${escapeHTML(f.dep_city)}(${escapeHTML(f.departure_time)}) → ${escapeHTML(f.arr_city)}(${escapeHTML(f.arrival_time)}) | ${escapeHTML(f.aircraft)}
        </div>`;
    }
    info.innerHTML = `
        ${flightLine}
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;flex-wrap:wrap;">
            <span class="prediction-stat-badge ml">${data.route_profile_label || ''}</span>
            <span class="prediction-stat-badge mock">手动输入</span>
        </div>
        <div class="prediction-summary">
            <div class="prediction-stat"><div class="prediction-stat-label">当前价格</div><div class="prediction-stat-value">¥${Math.round(data.current_price)}</div></div>
            <div class="prediction-stat"><div class="prediction-stat-label">历史最低</div><div class="prediction-stat-value">¥${Math.round(data.historical_min)}</div></div>
            <div class="prediction-stat highlight"><div class="prediction-stat-label">预测最低</div><div class="prediction-stat-value">¥${Math.round(data.predicted_min)}</div><div class="prediction-stat-sub">${data.predicted_min_date || ''}</div></div>
            <div class="prediction-stat"><div class="prediction-stat-label">距起飞</div><div class="prediction-stat-value">${data.days_until_departure} 天</div></div>
        </div>
        ${data.best_buy_window ? `<div class="buy-window ${buyClass}">${buyClass === 'buy-now' ? '🔴' : buyClass === 'wait' ? '🟢' : '🔵'} ${data.best_buy_window}</div>` : '<div class="buy-window none">📊 价格稳定，暂无明确信号</div>'}
        <div class="prediction-model">📊 ${data.model || '手动预测'} · 基于真实市场价格模式</div>
    `;
    // Chart
    const ctx = document.getElementById("quickPredictChart").getContext("2d");
    if (quickChart) quickChart.destroy();
    const cd = data.chart;
    const chartDatasets = [
        { label: "历史(模拟)", data: cd.historical_prices, borderColor: "#3b82f6", fill: false, tension: 0.3, pointRadius: 1, borderWidth: 2 },
        { label: "预测", data: cd.forecast_prices, borderColor: "#ef4444", borderDash: [6, 4], fill: false, tension: 0.3, pointRadius: 0, borderWidth: 2 },
        { label: "置信上限", data: cd.upper_bound, borderColor: "rgba(239,68,68,.25)", fill: "+1", tension: 0.3, pointRadius: 0, borderWidth: 1 },
        { label: "置信下限", data: cd.lower_bound, borderColor: "rgba(239,68,68,.25)", fill: false, tension: 0.3, pointRadius: 0, borderWidth: 1 },
    ];

    // Add best-buy star marker if predicted min is below current price
    if (data.predicted_min_date && data.predicted_min > 0
        && data.predicted_min < (data.current_price || Infinity)) {
        const minIdx = cd.labels.indexOf(data.predicted_min_date);
        if (minIdx >= 0) {
            const markerData = new Array(cd.labels.length).fill(null);
            markerData[minIdx] = data.predicted_min;
            chartDatasets.push({
                label: "最佳买点 ⭐",
                data: markerData,
                borderColor: "#10b981",
                backgroundColor: "#10b981",
                pointRadius: 8,
                pointHoverRadius: 12,
                pointStyle: "star",
                showLine: false,
                order: 0,
            });
        }
    }

    quickChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: cd.labels,
            datasets: chartDatasets,
        },
        options: { responsive: true, maintainAspectRatio: false, interaction: { intersect: false, mode: "index" },
            plugins: { legend: { labels: { usePointStyle: true, boxWidth: 8 } } },
            scales: { y: { ticks: { callback: v => "¥" + v } } },
        },
    });
    document.getElementById("quickResultCard").scrollIntoView({ behavior: "smooth" });
}

// ── Forms ────────────────────────────────────────────────────
function setupForms() {
    const future = new Date();
    future.setDate(future.getDate() + 30);
    document.getElementById("departureDate").value = future.toISOString().split("T")[0];
    document.getElementById("qpDate").value = future.toISOString().split("T")[0];

    // Quick predict form
    document.getElementById("quickPredictForm").addEventListener("submit", doQuickPredict);
    document.getElementById("qpFlightNo").addEventListener("input", onFlightNoInput);

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
            _queriesCache = null;
            loadQueriesShared(true);
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
    // Load queries once and share between dashboard and search page
    loadQueriesShared();
}

// ── Shared Queries Loader (avoids duplicate /api/queries calls) ──
let _queriesCache = null;
let _queriesCacheTs = 0;
const _queriesCacheTTL = 15000; // 15s for query data (more dynamic)

async function loadQueriesShared(force = false) {
    const now = Date.now();
    if (!force && _queriesCache && now - _queriesCacheTs < _queriesCacheTTL) {
        // Use cached data
        renderDashboardQueries(_queriesCache.user);
        renderSearchQueries(_queriesCache.user, _queriesCache.seed);
        return _queriesCache;
    }
    try {
        const [userQueries, seedQueries] = await Promise.all([
            api("/api/queries?scope=user"),
            api("/api/queries?scope=seed"),
        ]);
        _queriesCache = { user: userQueries, seed: seedQueries };
        _queriesCacheTs = now;
        renderDashboardQueries(userQueries);
        renderSearchQueries(userQueries, seedQueries);
        return _queriesCache;
    } catch (e) {
        console.error("Load queries error:", e);
        return null;
    }
}

// ── Dashboard ────────────────────────────────────────────────
async function refreshDashboard() {
    // Show skeleton on first load
    const routeList = document.getElementById("routePriceList");
    if (!routeList.dataset.loaded) {
        routeList.innerHTML = '<div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div>';
    }
    try {
        const data = await cachedApi("/api/dashboard", 15000); // 15s cache
        routeList.dataset.loaded = "1";
        dashboardDataCache = data;
        lastDashboardUpdate = Date.now();
        document.getElementById("statQueries").textContent = data.total_queries;
        document.getElementById("statMonitoring").textContent = data.monitoring_queries;
        document.getElementById("statAlerts").textContent = data.active_alerts;
        document.getElementById("statPlatforms").textContent = data.platform_count || 0;
        // Update quick stats bar
        const qsMonitoring = document.getElementById("qsMonitoring");
        const qsAlerts = document.getElementById("qsAlerts");
        const qsPlatforms = document.getElementById("qsPlatforms");
        const qsLowest = document.getElementById("qsLowest");
        if (qsMonitoring) qsMonitoring.textContent = data.monitoring_queries;
        if (qsAlerts) qsAlerts.textContent = data.active_alerts;
        if (qsPlatforms) qsPlatforms.textContent = data.platform_count || 0;
        if (qsLowest) {
            const minP = data.route_prices && data.route_prices.length > 0
                ? Math.round(Math.min(...data.route_prices.map(p => p.price))) : null;
            qsLowest.textContent = minP ? "¥" + minP : "--";
        }
        updateFreshnessIndicator();

        const routeList = document.getElementById("routePriceList");
        if (data.route_prices.length === 0) {
            routeList.innerHTML = `
                <div class="empty-state">
                    <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#cbd5e1" stroke-width="1.5"><path d="M17.8 19.2L16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/></svg>
                    <p>暂无监控数据，请先添加监控任务</p>
                </div>`;
            document.getElementById("statLowestPrice").textContent = "--";
        } else {
            routeList.innerHTML = data.route_prices.map((p, idx) => {
                const platInfo = getPlatformInfo(p.source);
                const labelSafe = p.label && p.label !== `${p.departure}→${p.destination}` ? escapeHTML(p.label) : "";
                return `
                <div class="route-price-item route-price-item-enhanced" id="routeCard${idx}">
                    <div class="route-info">
                        <div>
                            <div class="route-label">${escapeHTML(p.departure)} <span class="route-arrow">→</span> ${escapeHTML(p.destination)}
                                <span class="route-platform-badge">${platInfo.icon} ${escapeHTML(platInfo.name)}</span>
                            </div>
                            <div class="route-date">${escapeHTML(p.departure_date)} ${labelSafe ? "· " + labelSafe : ""}</div>
                            <div class="route-sparkline" id="sparkline${idx}" style="margin-top:6px;">
                                <span style="font-size:11px;color:var(--text-muted);cursor:pointer;" onclick="fetchRouteSparkline(${idx}, '${escapeHTML(p.departure)}', '${escapeHTML(p.destination)}', '${escapeHTML(p.departure_date)}')">📈 查看趋势</span>
                            </div>
                        </div>
                    </div>
                    <div class="route-price">
                        <div class="route-price-value">¥${Math.round(p.price)}</div>
                        <div class="route-price-airline">${escapeHTML(p.airline || "")}</div>
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
                    <div class="alert-title">✈️ ${escapeHTML(a.departure || "")} → ${escapeHTML(a.destination || "")} 降至 ¥${Math.round(a.price)}</div>
                    <div class="alert-detail">目标价: ¥${Math.round(a.target_price)} | ${escapeHTML(a.airline || "")} ${escapeHTML(a.flight_no || "")}</div>
                    <div class="alert-time">${formatTime(a.triggered_at)}</div>
                </div>
            `).join("");
        }
    } catch (e) { console.error("Dashboard error:", e); }
}

// ── Dashboard Query List (with action buttons) ────────────────
function renderDashboardQueries(userQueries) {
    const list = document.getElementById("dashboardQueryList");
    if (!list) return;
    list.dataset.loaded = "1";
    if (userQueries.length === 0) {
        list.innerHTML = `<div class="empty-state"><p>暂无任务，请切换到「搜索比价」页面添加</p></div>`;
    } else {
        list.innerHTML = userQueries.map(queryItemTpl).join("");
    }
    updateQueryBatchBar();
}

// Legacy alias — kept for compatibility with navigation clicks
async function loadDashboardQueries() {
    const list = document.getElementById("dashboardQueryList");
    if (list && !list.dataset.loaded) {
        list.innerHTML = '<div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div>';
    }
    const data = await loadQueriesShared();
    if (!data) return;
    renderDashboardQueries(data.user);
}

// ── Queries ──────────────────────────────────────────────────
function isSeedQuery(q) {
    // Seed data labels contain patterns like "京沪线(near)", "跨大西洋(far)", etc.
    return /\(near\)|\(far\)/.test(q.label || "");
}

const queryItemTpl = q => `
    <div class="query-item${selectedQueryIds.has(q.id) ? ' selected' : ''}" id="queryItem${q.id}">
        <input type="checkbox" class="query-item-checkbox" 
            ${selectedQueryIds.has(q.id) ? 'checked' : ''} 
            onchange="toggleQuerySelection(${q.id})" 
            aria-label="选择 ${escapeHTML(q.departure)} → ${escapeHTML(q.destination)}">
        <div class="query-info">
            <div>
                <div class="query-route">${escapeHTML(q.departure)} → ${escapeHTML(q.destination)}</div>
                <div class="query-meta">
                    <span>📅 ${escapeHTML(q.departure_date)}</span>
                    <span>💺 ${cabinLabel(q.cabin_class)}</span>
                    <span>📊 ${q.stats.total_records}条记录</span>
                    ${q.platform_count > 0 ? `<span class="query-platform-count">🔗 ${q.platform_count}个平台</span>` : ""}
                    ${q.label && q.label !== `${q.departure}→${q.destination}` ? `<span>🏷️ ${escapeHTML(q.label)}</span>` : ""}
                </div>
            </div>
        </div>
        <div class="query-actions">
            ${q.current_min_price > 0 ? `<div class="query-price-badge">最低 ¥${Math.round(q.current_min_price)}</div>` : ""}
            <div class="toggle ${q.is_monitoring ? "active" : ""}" onclick="toggleMonitoring(${q.id}, ${!q.is_monitoring})" title="${q.is_monitoring ? '停止监控' : '开始监控'}"></div>
            <button class="btn btn-sm btn-primary" onclick="searchNow(${q.id})">🔍 立即搜索</button>
            <button class="btn btn-sm btn-ghost" onclick="showPricePrediction(${q.id})">📈 预测</button>
            <button class="btn-icon danger" onclick="deleteQuery(${q.id})" title="删除">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
            </button>
        </div>
    </div>`;

function renderSearchQueries(userQueries, seedQueries) {
    const list = document.getElementById("queryList");
    if (list) list.dataset.loaded = "1";
    if (userQueries.length === 0) {
        if (list) list.innerHTML = `<div class="empty-state"><p>暂无任务，请在上方添加</p></div>`;
    } else {
        if (list) list.innerHTML = userQueries.map(queryItemTpl).join("");
    }
    updateSelects(userQueries, seedQueries || []);
    updateQueryBatchBar();
}

async function loadQueries() {
    const list = document.getElementById("queryList");
    if (list && !list.dataset.loaded) {
        list.innerHTML = '<div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div>';
    }
    const data = await loadQueriesShared();
    if (!data) return;
    renderSearchQueries(data.user, data.seed);
}

function updateSelects(userQueries, seedQueries) {
    const trendSel = document.getElementById("trendQuerySelect");
    const alertSel = document.getElementById("alertQuerySelect");
    const trendVal = trendSel.value;
    const alertVal = alertSel.value;
    trendSel.innerHTML = '<option value="">选择监控任务</option>';
    alertSel.innerHTML = '<option value="">选择监控任务</option>';

    // User queries first
    userQueries.forEach(q => {
        const label = `${q.departure}→${q.destination} (${q.departure_date})${q.label && q.label !== `${q.departure}→${q.destination}` ? " " + q.label : ""}`;
        trendSel.add(new Option(label, q.id));
        alertSel.add(new Option(label, q.id));
    });

    // Seed queries grouped under separator
    if (seedQueries && seedQueries.length > 0) {
        const sep1 = document.createElement("option");
        sep1.disabled = true; sep1.textContent = "── 基准数据 ──";
        trendSel.add(sep1);
        const sep2 = document.createElement("option");
        sep2.disabled = true; sep2.textContent = "── 基准数据 ──";
        alertSel.add(sep2);

        seedQueries.forEach(q => {
            const label = `${q.departure}→${q.destination} (${q.departure_date}) [基准]`;
            trendSel.add(new Option(label, q.id));
            alertSel.add(new Option(label, q.id));
        });
    }

    trendSel.value = trendVal;
    alertSel.value = alertVal;
}

async function toggleMonitoring(queryId, enable) {
    try {
        await api(`/api/queries/${queryId}/monitoring`, "PUT", { is_monitoring: enable });
        toast(enable ? "已开启监控" : "已停止监控", "success");
        _queriesCache = null; // invalidate cache
        loadQueriesShared(true);
    } catch (e) { toast("操作失败", "error"); }
}

async function deleteQuery(queryId) {
    if (!confirm("确定要删除这个监控任务吗？相关历史数据也会被删除。")) return;
    try {
        await api(`/api/queries/${queryId}`, "DELETE");
        toast("已删除", "success");
        _queriesCache = null; // invalidate cache
        loadQueriesShared(true);
        refreshDashboard();
    } catch (e) { toast("删除失败", "error"); }
}

// ── Batch Query Operations ──────────────────────────────────
function toggleQuerySelection(queryId) {
    if (selectedQueryIds.has(queryId)) {
        selectedQueryIds.delete(queryId);
    } else {
        selectedQueryIds.add(queryId);
    }
    updateQueryBatchBar();
    // Update item visual state
    const item = document.getElementById("queryItem" + queryId);
    if (item) item.classList.toggle("selected", selectedQueryIds.has(queryId));
}

function toggleSelectAllQueries(checked) {
    const checkboxes = document.querySelectorAll(".query-item-checkbox");
    checkboxes.forEach(cb => {
        cb.checked = checked;
        const id = parseInt(cb.closest(".query-item").id.replace("queryItem", ""), 10);
        if (checked) selectedQueryIds.add(id);
        else selectedQueryIds.delete(id);
    });
    // Update visual state
    document.querySelectorAll(".query-item").forEach(el => {
        el.classList.toggle("selected", checked);
    });
    updateQueryBatchBar();
}

function updateQueryBatchBar() {
    const bar = document.getElementById("queryBatchBar");
    const count = selectedQueryIds.size;
    const total = document.querySelectorAll(".query-item").length;
    const countEl = document.getElementById("queryBatchCount");
    const delBtn = document.getElementById("queryBatchDelete");
    const clearBtn = document.getElementById("queryBatchClear");
    const allCb = document.getElementById("queryBatchAll");
    
    if (total > 0) {
        bar.classList.add("show");
        countEl.textContent = `已选 ${count}`;
        delBtn.disabled = count === 0;
        clearBtn.disabled = false;
        allCb.checked = count === total && total > 0;
        allCb.indeterminate = count > 0 && count < total;
    } else {
        bar.classList.remove("show");
        countEl.textContent = "已选 0";
        delBtn.disabled = true;
        clearBtn.disabled = true;
    }
}

async function batchDeleteQueries() {
    const ids = [...selectedQueryIds];
    if (ids.length === 0) return;
    if (!confirm(`确定要删除选中的 ${ids.length} 个监控任务吗？相关历史数据也会被删除。`)) return;
    
    let success = 0, fail = 0;
    for (const id of ids) {
        try {
            await api(`/api/queries/${id}`, "DELETE");
            success++;
        } catch (e) { fail++; }
    }
    if (success > 0) toast(`已删除 ${success} 个任务${fail > 0 ? `，${fail} 个失败` : ""}`, fail > 0 ? "warning" : "success");
    selectedQueryIds.clear();
    _queriesCache = null;
    loadQueriesShared(true);
    refreshDashboard();
}

async function clearAllQueries() {
    const items = document.querySelectorAll(".query-item");
    if (items.length === 0) return;
    if (!confirm(`确定要清空所有 ${items.length} 个监控任务吗？此操作不可恢复！`)) return;
    
    let success = 0, fail = 0;
    for (const el of items) {
        const id = parseInt(el.id.replace("queryItem", ""), 10);
        try {
            await api(`/api/queries/${id}`, "DELETE");
            success++;
        } catch (e) { fail++; }
    }
    if (success > 0) toast(`已清空 ${success} 个任务${fail > 0 ? `，${fail} 个失败` : ""}`, fail > 0 ? "warning" : "success");
    selectedQueryIds.clear();
    _queriesCache = null;
    loadQueriesShared(true);
    refreshDashboard();
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
                        <span class="step-text">正在通过 Bing 搜索引擎获取实时价格...</span>
                    </div>
                    <div class="step" id="step-2">
                        <span class="step-icon">2</span>
                        <span class="step-text">抓取携程/飞猪/去哪儿等平台数据</span>
                    </div>
                    <div class="step" id="step-3">
                        <span class="step-icon">3</span>
                        <span class="step-text">生成多平台比价数据</span>
                    </div>
                    <div class="step" id="step-4">
                        <span class="step-icon">4</span>
                        <span class="step-text">完成，正在渲染结果...</span>
                    </div>
                </div>
                <div class="progress-hint">⏱ 预计耗时 15-25 秒（Bing 搜索 + 多平台数据）</div>
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
            _queriesCache = null;
            loadQueriesShared(true);
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
            _queriesCache = null;
            loadQueriesShared(true);
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
    const profileBadge = data.route_profile_label 
        ? `<span class="prediction-stat-badge ml">${data.route_profile_label}</span>`
        : "";

    // Data quality badge
    const realPts = data.data_points_real || 0;
    const totalPts = data.data_points_total || data.data_points || 0;
    const dataBadge = totalPts > 0
        ? (realPts >= 7 
            ? '<span class="prediction-stat-badge real">真实数据</span>'
            : '<span class="prediction-stat-badge mock">模拟数据</span>')
        : "";

    // ML model badge
    const isML = (data.model || '').includes('Ensemble') || (data.model || '').includes('sklearn');
    const modelBadge = isML
        ? '<span class="prediction-stat-badge ml">GBR+RFR+Ridge 集成</span>'
        : '<span class="prediction-stat-badge mock">LR+WMA 统计</span>';

    // Buy window with correct styling
    let buyClass = 'none', buyIcon = '📊';
    const bw = data.best_buy_window || '';

    // urgency signals → red
    const urgentWords = ['立即', '尽快', '即将', '马上', '尽快锁定', '仅', '天建', '上涨', '高位'];
    // positive wait signals → green
    const waitWords   = ['最佳入手', '促销', '降至', '降价', '预计降'];
    // neutral watch signals → blue
    const watchWords  = ['观望', '稳定', '入手', '接近', '随时'];

    if (bw && urgentWords.some(w => bw.includes(w))) {
        buyClass = 'buy-now'; buyIcon = '🔴';
    } else if (bw && waitWords.some(w => bw.includes(w))) {
        buyClass = 'wait'; buyIcon = '🟢';
    } else if (bw && watchWords.some(w => bw.includes(w))) {
        buyClass = 'watch'; buyIcon = '🔵';
    }

    const buyWindow = bw
        ? `<div class="buy-window ${buyClass}">${buyIcon} ${bw}</div>`
        : `<div class="buy-window none">📊 价格稳定，暂无明确买卖信号</div>`;

    const recommendHtml = data.recommendation
        ? `<div class="recommend-box">${data.recommendation}</div>`
        : "";

    // ML evaluation cards
    let evalHtml = '';
    const ev = data.evaluation || {};
    const metrics = ev.metrics || {};
    const weights = ev.weights || {};
    if (Object.keys(metrics).length > 0) {
        evalHtml = '<div class="eval-grid">';
        for (const [name, m] of Object.entries(metrics)) {
            const w = weights[name] ? Math.round(weights[name] * 100) : 0;
            evalHtml += `<div class="eval-card">
                <div class="eval-name">${name}</div>
                <div class="eval-meta">RMSE ${m.RMSE || '-'} MAE ${m.MAE || '-'}</div>
                <div class="eval-weight">权重 ${w}%</div>
            </div>`;
        }
        evalHtml += '</div>';
    }

    const dataPointsInfo = realPts > 0
        ? `${realPts} 真实 + ${totalPts - realPts} 历史`
        : `${totalPts} 模拟`;

    infoEl.innerHTML = `
        <div style="display:flex;align-items:center;margin-bottom:14px;gap:8px;flex-wrap:wrap;">
            ${profileBadge}
            ${dataBadge}
            ${modelBadge}
            <span style="font-size:12px;color:var(--text-secondary);">${escapeHTML(data.route_description || '')}</span>
        </div>
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
                <div class="prediction-stat-sub">${escapeHTML(data.predicted_min_date || '')}</div>
            </div>
            <div class="prediction-stat">
                <div class="prediction-stat-label">距起飞</div>
                <div class="prediction-stat-value">${data.days_until_departure || 0} 天</div>
            </div>
        </div>
        ${buyWindow}
        ${recommendHtml}
        ${evalHtml}
        <div class="prediction-model">📊 ${escapeHTML(data.model || '未知')} · 置信${escapeHTML(data.confidence_interval || 'N/A')} · ${dataPointsInfo} 个数据点</div>
    `;
    
    const ctx = document.getElementById("predictionChart").getContext("2d");
    
    // Add best-buy star marker if predicted min is below current price
    if (data.predicted_min_date && data.predicted_min > 0
        && data.predicted_min < (data.current_price || Infinity)) {
        const minIdx = labels.indexOf(data.predicted_min_date);
        if (minIdx >= 0) {
            const markerData = new Array(labels.length).fill(null);
            markerData[minIdx] = data.predicted_min;
            finalDatasets.push({
                label: "最佳买入点",
                data: markerData,
                borderColor: "#10b981",
                backgroundColor: "#10b981",
                pointRadius: 8,
                pointHoverRadius: 12,
                pointStyle: "star",
                showLine: false,
                order: 0,
            });
        }
    }
    
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
        content.innerHTML = `<div class="empty-state-enhanced"><div class="empty-icon">🔍</div><h4>未找到航班数据</h4><p>试试其他日期或搜索条件</p></div>`;
        modal.style.display = "flex";
        // Hide filter bar when no results
        document.getElementById("filterBar").style.display = "none";
        return;
    }

    // Cache for filtering
    currentSearchResults = result;
    // Reset filters
    resetFilters();

    // Build platform tags
    const platformTags = (result.platforms || []).map(p => {
        const info = getPlatformInfo(p);
        return `<span class="platform-tag" style="background:${info.color}15;color:${info.color};">${info.icon} ${info.name}</span>`;
    }).join("");

    // Find cheapest flight for best deal badge
    const cheapestPrice = Math.min(...result.flights.map(f => f.price));

    content.innerHTML = `
        <div class="search-summary">
            <span class="search-summary-count">共 ${result.count} 个航班</span>
            <span class="search-summary-price">最低价 ¥${Math.round(result.min_price)}</span>
            <div class="search-summary-platforms">${platformTags}</div>
            <button class="btn btn-sm btn-secondary" onclick="bingSearchFlight(${queryId})" style="margin-left:auto;">
                🔍 Bing 搜索
            </button>
            <button class="btn btn-sm btn-primary" onclick="showPricePrediction(${queryId})">
                📈 价格预测
            </button>
        </div>
        <div id="flightResultsList">
            ${result.flights.map(f => renderFlightCard(f, f.price <= cheapestPrice)).join("")}
        </div>
    `;
    modal.style.display = "flex";
    // Show filter bar when we have results
    document.getElementById("filterBar").style.display = "flex";
}

// ── Bing Search for flights ──────────────────────────────────
async function bingSearchFlight(queryId) {
    // Get query details from the search results
    const queryItem = document.querySelector(`#queryList .query-item .query-actions button[onclick*="searchNow(${queryId})"]`);
    let dep = "", arr = "", date = "";
    if (queryItem) {
        const itemEl = queryItem.closest(".query-item");
        const routeEl = itemEl.querySelector(".query-route");
        const metaEl = itemEl.querySelector(".query-meta");
        if (routeEl) {
            const parts = routeEl.textContent.split("→");
            dep = parts[0]?.trim() || "";
            arr = parts[1]?.trim() || "";
        }
        if (metaEl) {
            const dateMatch = metaEl.textContent.match(/(\d{4}-\d{2}-\d{2})/);
            if (dateMatch) date = dateMatch[1];
        }
    }

    toast("正在通过 Bing 搜索实时价格...", "");
    try {
        const url = "/api/flight/bing?dep=" + encodeURIComponent(dep) + "&arr=" + encodeURIComponent(arr) + "&date=" + date;
        const r = await api(url);
        if (r.found && r.flights && r.flights.length > 0) {
            // Merge Bing results into the existing list
            const listEl = document.getElementById("flightResultsList");
            const existingCount = listEl.querySelectorAll(".flight-result-card").length;
            r.flights.forEach((f, idx) => {
                const card = document.createElement("div");
                card.className = "flight-result-card";
                card.style.borderLeft = "3px solid #00809d";
                card.innerHTML = `
                    <div class="flight-result-main">
                        <div class="flight-airline-info">
                            <div class="flight-airline-logo">🔍</div>
                            <div>
                                <div class="flight-airline-name">${escapeHTML(f.airline || "Bing 搜索结果")}</div>
                                <div class="flight-airline-no">${escapeHTML(f.flight_no || "")} · Bing 索引</div>
                            </div>
                        </div>
                        <div class="flight-time-info">
                            <div class="flight-time-block">
                                <div class="flight-time">--</div>
                                <div class="flight-airport">${escapeHTML(f.departure_airport || dep)}</div>
                            </div>
                            <div class="flight-duration-block">
                                <div class="flight-duration">--</div>
                                <div class="flight-duration-line"></div>
                                <div><span class="stops-badge transfer">Bing</span></div>
                            </div>
                            <div class="flight-time-block">
                                <div class="flight-time">--</div>
                                <div class="flight-airport">${escapeHTML(f.arrival_airport || arr)}</div>
                            </div>
                        </div>
                        <div class="flight-price-block">
                            <div class="flight-price-main">¥${Math.round(f.price)}</div>
                            <div class="flight-price-label">Bing 搜索</div>
                        </div>
                    </div>
                    <div class="platform-prices">
                        <a href="${safeURL(f.purchase_url)}" target="_blank" rel="noopener" class="platform-price-item cheapest">
                            <div class="platform-price-left">
                                <span class="platform-price-icon">🔍</span>
                                <span class="platform-price-name">Bing 搜索</span>
                                <span class="platform-cheapest-tag">实时</span>
                            </div>
                            <span class="platform-price-value cheapest">¥${Math.round(f.price)} → 去搜索</span>
                        </a>
                    </div>
                `;
                listEl.appendChild(card);
            });
            // Update summary count
            const countEl = document.querySelector(".search-summary-count");
            if (countEl) countEl.textContent = `共 ${existingCount + r.flights.length} 个航班 (含 ${r.flights.length} 条 Bing 结果)`;
            // Re-apply filters to include new results
            currentSearchResults = result;
            applyFilters();
            toast(`Bing 搜索完成，新增 ${r.flights.length} 条结果`, "success");
        } else {
            toast("Bing 未找到更多价格", "warning");
        }
    } catch (e) { toast("Bing 搜索失败: " + e.message, "error"); }
}

function renderFlightCard(f, isBestDeal = false) {
    const platPrices = f.platform_prices || [];
    const cheapestPlat = platPrices.length > 0 ? platPrices[0] : null;

    const card = document.createElement("div");
    card.className = "flight-result-card";
    if (isBestDeal) {
        const badge = document.createElement("span");
        badge.className = "best-deal-badge";
        badge.textContent = "最佳 ⭐";
        card.appendChild(badge);
    }

    // Main row
    const main = document.createElement("div");
    main.className = "flight-result-main";

    // Airline info
    const airlineInfo = document.createElement("div");
    airlineInfo.className = "flight-airline-info";
    airlineInfo.innerHTML = `<div class="flight-airline-logo">✈️</div>`;
    const airlineDiv = document.createElement("div");
    const airlineName = document.createElement("div");
    airlineName.className = "flight-airline-name";
    airlineName.textContent = f.airline;
    const airlineNo = document.createElement("div");
    airlineNo.className = "flight-airline-no";
    airlineNo.textContent = `${f.flight_no} · ${f.aircraft}`;
    airlineDiv.appendChild(airlineName);
    airlineDiv.appendChild(airlineNo);
    airlineInfo.appendChild(airlineDiv);
    main.appendChild(airlineInfo);

    // Time info
    const timeInfo = document.createElement("div");
    timeInfo.className = "flight-time-info";
    const depBlock = document.createElement("div");
    depBlock.className = "flight-time-block";
    const depTime = document.createElement("div");
    depTime.className = "flight-time";
    depTime.textContent = f.departure_time || "时间待确认";
    const depAirport = document.createElement("div");
    depAirport.className = "flight-airport";
    depAirport.textContent = f.departure_airport;
    depBlock.appendChild(depTime);
    depBlock.appendChild(depAirport);
    timeInfo.appendChild(depBlock);

    const durBlock = document.createElement("div");
    durBlock.className = "flight-duration-block";
    const dur = document.createElement("div");
    dur.className = "flight-duration";
    dur.textContent = f.duration || "—";
    const durLine = document.createElement("div");
    durLine.className = "flight-duration-line";
    const stopsDiv = document.createElement("div");
    stopsDiv.className = "flight-duration";
    const stopsBadge = document.createElement("span");
    stopsBadge.className = `stops-badge ${f.stops === 0 ? 'direct' : 'transfer'}`;
    stopsBadge.textContent = f.stops === 0 ? '直飞' : f.stops + '中转';
    stopsDiv.appendChild(stopsBadge);
    durBlock.appendChild(dur);
    durBlock.appendChild(durLine);
    durBlock.appendChild(stopsDiv);
    timeInfo.appendChild(durBlock);

    const arrBlock = document.createElement("div");
    arrBlock.className = "flight-time-block";
    const arrTime = document.createElement("div");
    arrTime.className = "flight-time";
    arrTime.textContent = f.arrival_time || "—";
    const arrAirport = document.createElement("div");
    arrAirport.className = "flight-airport";
    arrAirport.textContent = f.arrival_airport;
    arrBlock.appendChild(arrTime);
    arrBlock.appendChild(arrAirport);
    timeInfo.appendChild(arrBlock);
    main.appendChild(timeInfo);

    // Price block
    const priceBlock = document.createElement("div");
    priceBlock.className = "flight-price-block";
    const priceMain = document.createElement("div");
    priceMain.className = "flight-price-main";
    priceMain.textContent = `¥${Math.round(f.price)}`;
    const priceLabel = document.createElement("div");
    priceLabel.className = "flight-price-label";
    priceLabel.textContent = cheapestPlat ? cheapestPlat.platform_name : '';
    priceBlock.appendChild(priceMain);
    priceBlock.appendChild(priceLabel);
    main.appendChild(priceBlock);
    card.appendChild(main);

    // Platform prices
    const allPlats = platPrices.length > 0 ? platPrices : (f.purchase_url ? [{...f, platform_icon: "🎫", platform_name: getPlatformInfo(f.source).name}] : []);
    if (allPlats.length > 0) {
        const maxPrice = Math.max(...allPlats.map(p => p.price));
        const platContainer = document.createElement("div");
        platContainer.className = "platform-prices";
        allPlats.forEach((pp, idx) => {
            const link = document.createElement("a");
            link.href = safeURL(pp.purchase_url);
            link.target = "_blank";
            link.rel = "noopener";
            link.className = `platform-price-item ${idx === 0 ? 'cheapest' : ''}`;
            const left = document.createElement("div");
            left.className = "platform-price-left";
            const icon = document.createElement("span");
            icon.className = "platform-price-icon";
            icon.textContent = pp.platform_icon;
            const name = document.createElement("span");
            name.className = "platform-price-name";
            name.textContent = pp.platform_name;
            left.appendChild(icon);
            left.appendChild(name);
            if (idx === 0 && platPrices.length > 0) {
                const tag = document.createElement("span");
                tag.className = "platform-cheapest-tag";
                tag.textContent = "最低";
                left.appendChild(tag);
                // Show savings compared to most expensive
                if (maxPrice > pp.price) {
                    const save = document.createElement("span");
                    save.className = "platform-cheapest-tag";
                    save.style.background = "var(--success)";
                    save.textContent = "省¥" + Math.round(maxPrice - pp.price);
                    left.appendChild(save);
                }
            }
            const value = document.createElement("span");
            value.className = `platform-price-value ${idx === 0 ? 'cheapest' : ''}`;
            value.textContent = `¥${Math.round(pp.price)}${idx === 0 && platPrices.length === allPlats.length ? ' → 去购买' : ''}`;
            link.appendChild(left);
            link.appendChild(value);
            platContainer.appendChild(link);
        });
        card.appendChild(platContainer);
    }

    return card.outerHTML;
}

function closeModal(id) {
    const modal = document.getElementById(id);
    modal.style.display = "none";
    // Destroy chart instances when closing to free memory
    if (id === "predictionModal" && window.predictionChart) {
        window.predictionChart.destroy();
        window.predictionChart = null;
    }
    if (id === "searchResultsModal") {
        const quickChartEl = document.getElementById("quickPredictChart");
        if (quickChartEl && quickChart) {
            quickChart.destroy();
            quickChart = null;
        }
        // Hide filter bar and clear cache
        document.getElementById("filterBar").style.display = "none";
        currentSearchResults = null;
    }
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
                        <td>${escapeHTML(f.duration)}</td>
                        <td><span class="stops-badge ${f.stops === 0 ? 'direct' : 'transfer'}">${f.stops === 0 ? '直飞' : f.stops + '中转'}</span></td>
                        <td class="price-cell">¥${Math.round(f.price)}</td>
                        <td><span class="platform-tag" style="background:${info.color}15;color:${info.color};">${info.icon} ${escapeHTML(info.name)}</span></td>
                        <td>${f.purchase_url ? `<a href="${safeURL(f.purchase_url)}" target="_blank" rel="noopener" class="btn btn-sm btn-primary">去购买</a>` : ''}</td>
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
            updateAlertBatchBar();
            return;
        }
        list.innerHTML = alerts.map(a => `
            <div class="alert-config-item${selectedAlertIds.has(a.id) ? ' selected' : ''}" id="alertItem${a.id}">
                <input type="checkbox" class="alert-item-checkbox"
                    ${selectedAlertIds.has(a.id) ? 'checked' : ''}
                    onchange="toggleAlertSelection(${a.id})"
                    aria-label="选择提醒 ${escapeHTML(a.query_route)}">
                <div class="alert-config-info">
                    <div class="alert-config-route">${escapeHTML(a.query_route)} ${a.query_label && a.query_label !== a.query_route ? "· " + escapeHTML(a.query_label) : ""}</div>
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
        updateAlertBatchBar();
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
                <div class="alert-title">✈️ ${escapeHTML(h.departure || "")} → ${escapeHTML(h.destination || "")} 降价至 ¥${Math.round(h.price)}</div>
                <div class="alert-detail">
                    目标价: ¥${Math.round(h.target_price)}
                    | ${escapeHTML(h.airline || "")} ${escapeHTML(h.flight_no || "")}
                    | 日期: ${escapeHTML(h.departure_date || "")}
                </div>
                <div class="alert-time">${formatTime(h.triggered_at)}</div>
            </div>
        `).join("");
    } catch (e) { console.error("Load alert history error:", e); }
}

async function loadAlertQuerySelect() {
    // Use shared cache — no extra API call needed
    await loadQueriesShared();
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

// ── Batch Alert Operations ──────────────────────────────────
function toggleAlertSelection(alertId) {
    if (selectedAlertIds.has(alertId)) {
        selectedAlertIds.delete(alertId);
    } else {
        selectedAlertIds.add(alertId);
    }
    updateAlertBatchBar();
    const item = document.getElementById("alertItem" + alertId);
    if (item) item.classList.toggle("selected", selectedAlertIds.has(alertId));
}

function toggleSelectAllAlerts(checked) {
    const checkboxes = document.querySelectorAll(".alert-item-checkbox");
    checkboxes.forEach(cb => {
        cb.checked = checked;
        const id = parseInt(cb.closest(".alert-config-item").id.replace("alertItem", ""), 10);
        if (checked) selectedAlertIds.add(id);
        else selectedAlertIds.delete(id);
    });
    document.querySelectorAll(".alert-config-item").forEach(el => {
        el.classList.toggle("selected", checked);
    });
    updateAlertBatchBar();
}

function updateAlertBatchBar() {
    const bar = document.getElementById("alertBatchBar");
    const count = selectedAlertIds.size;
    const total = document.querySelectorAll(".alert-config-item").length;
    const countEl = document.getElementById("alertBatchCount");
    const delBtn = document.getElementById("alertBatchDelete");
    const clearBtn = document.getElementById("alertBatchClear");
    const allCb = document.getElementById("alertBatchAll");
    
    if (total > 0) {
        bar.classList.add("show");
        countEl.textContent = `已选 ${count}`;
        delBtn.disabled = count === 0;
        clearBtn.disabled = false;
        allCb.checked = count === total && total > 0;
        allCb.indeterminate = count > 0 && count < total;
    } else {
        bar.classList.remove("show");
        countEl.textContent = "已选 0";
        delBtn.disabled = true;
        clearBtn.disabled = true;
    }
}

async function batchDeleteAlerts() {
    const ids = [...selectedAlertIds];
    if (ids.length === 0) return;
    if (!confirm(`确定要删除选中的 ${ids.length} 个价格提醒吗？`)) return;
    
    let success = 0, fail = 0;
    for (const id of ids) {
        try {
            await api(`/api/alerts/${id}`, "DELETE");
            success++;
        } catch (e) { fail++; }
    }
    if (success > 0) toast(`已删除 ${success} 个提醒${fail > 0 ? `，${fail} 个失败` : ""}`, fail > 0 ? "warning" : "success");
    selectedAlertIds.clear();
    loadAlerts();
}

async function clearAllAlerts() {
    const items = document.querySelectorAll(".alert-config-item");
    if (items.length === 0) return;
    if (!confirm(`确定要清空所有 ${items.length} 个价格提醒吗？此操作不可恢复！`)) return;
    
    let success = 0, fail = 0;
    for (const el of items) {
        const id = parseInt(el.id.replace("alertItem", ""), 10);
        try {
            await api(`/api/alerts/${id}`, "DELETE");
            success++;
        } catch (e) { fail++; }
    }
    if (success > 0) toast(`已清空 ${success} 个提醒${fail > 0 ? `，${fail} 个失败` : ""}`, fail > 0 ? "warning" : "success");
    selectedAlertIds.clear();
    loadAlerts();
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
            // Use cached queries to check monitoring status
            const data = await loadQueriesShared();
            const monitoring = data && data.user ? data.user.filter(q => q.is_monitoring) : [];
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

// ── Sparkline Renderer ───────────────────────────────────────
function renderSparkline(prices, width = 80, height = 28) {
    if (!prices || prices.length < 2) return "";
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const range = max - min || 1;
    const padding = 2;
    const w = width - padding * 2;
    const h = height - padding * 2;
    const points = prices.map((p, i) => {
        const x = padding + (i / (prices.length - 1)) * w;
        const y = padding + h - ((p - min) / range) * h;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const trend = prices[prices.length - 1] > prices[0] ? "up" : prices[prices.length - 1] < prices[0] ? "down" : "flat";
    const color = trend === "up" ? "#ef4444" : trend === "down" ? "#10b981" : "#94a3b8";
    const pct = prices[0] > 0 ? ((prices[prices.length - 1] - prices[0]) / prices[0] * 100) : 0;
    const pctStr = (pct >= 0 ? "+" : "") + pct.toFixed(1) + "%";
    return `<div class="sparkline-wrap">
        <svg class="sparkline" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
            <polyline points="${points.join(" ")}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <circle points="${points[points.length-1]}" r="3" fill="${color}"/>
        </svg>
        <span class="sparkline-label ${trend}">${pctStr}</span>
    </div>`;
}

// ── Fetch Route Sparkline (on-demand) ───────────────────────
async function fetchRouteSparkline(idx, dep, arr, date) {
    const container = document.getElementById("sparkline" + idx);
    if (!container) return;
    container.innerHTML = '<span style="font-size:11px;color:var(--text-muted);">加载中...</span>';
    try {
        // Find a matching query ID from cached dashboard data
        const queries = await api("/api/queries?scope=user");
        const match = queries.find(q => q.departure === dep && q.destination === arr && q.departure_date === date);
        if (!match) {
            container.innerHTML = '<span style="font-size:11px;color:var(--text-muted);">无历史数据</span>';
            return;
        }
        const history = await api(`/api/queries/${match.id}/history?limit=30`);
        if (!history || history.length < 2) {
            container.innerHTML = '<span style="font-size:11px;color:var(--text-muted);">数据不足</span>';
            return;
        }
        const prices = history.map(h => h.min_price).reverse();
        container.innerHTML = renderSparkline(prices, 90, 30);
    } catch (e) {
        container.innerHTML = '<span style="font-size:11px;color:var(--text-muted);">加载失败</span>';
    }
}

// ── Price Change Indicator ───────────────────────────────────
function priceChangeHTML(current, previous) {
    if (!previous || previous <= 0 || !current || current <= 0) return "";
    const diff = current - previous;
    const pct = ((diff / previous) * 100).toFixed(1);
    if (Math.abs(diff) < 1) return `<span class="price-change flat">→ 0%</span>`;
    if (diff > 0) return `<span class="price-change up">↑ ${pct}%</span>`;
    return `<span class="price-change down">↓ ${pct}%</span>`;
}

// ── Data Freshness Indicator ─────────────────────────────────
function updateFreshnessIndicator() {
    const el = document.getElementById("dashboardFreshness");
    if (!el || !lastDashboardUpdate) return;
    const diff = (Date.now() - lastDashboardUpdate) / 1000; // seconds
    const dot = el.querySelector(".freshness-dot");
    const text = el.querySelector("span:last-child");
    if (diff < 60) { dot.className = "freshness-dot"; text.textContent = "刚刚更新"; }
    else if (diff < 300) { dot.className = "freshness-dot"; text.textContent = Math.floor(diff / 60) + "分钟前"; }
    else if (diff < 3600) { dot.className = "freshness-dot stale"; text.textContent = Math.floor(diff / 60) + "分钟前"; }
    else { dot.className = "freshness-dot old"; text.textContent = Math.floor(diff / 3600) + "小时前"; }
}

// ── Search Filter Bar ────────────────────────────────────────
function setupFilterBar() {
    document.querySelectorAll(".filter-chip").forEach(chip => {
        chip.addEventListener("click", () => {
            const filter = chip.dataset.filter;
            const value = chip.dataset.value;
            // Toggle active state within same filter group
            document.querySelectorAll(`.filter-chip[data-filter="${filter}"]`).forEach(c => c.classList.remove("active"));
            chip.classList.add("active");
            searchFilters[filter] = value;
            applyFilters();
        });
    });
    // Price range inputs
    ["filterPriceMin", "filterPriceMax"].forEach(id => {
        const input = document.getElementById(id);
        if (input) {
            input.addEventListener("input", () => {
                searchFilters.priceMin = parseFloat(input.value) || null;
            });
            input.addEventListener("change", () => {
                searchFilters.priceMax = parseFloat(document.getElementById("filterPriceMax").value) || null;
                searchFilters.priceMin = parseFloat(document.getElementById("filterPriceMin").value) || null;
                applyFilters();
            });
        }
    });
}

function applyFilters() {
    if (!currentSearchResults || !currentSearchResults.flights) return;
    const flights = [...currentSearchResults.flights];
    const filtered = flights.filter(f => {
        // Stops filter
        if (searchFilters.stops === "direct" && f.stops !== 0) return false;
        if (searchFilters.stops === "transfer" && f.stops === 0) return false;
        // Time filter
        if (searchFilters.time !== "all" && f.departure_time) {
            const hour = parseInt(f.departure_time.split(":")[0], 10);
            if (isNaN(hour)) return true;
            if (searchFilters.time === "morning" && (hour < 6 || hour >= 12)) return false;
            if (searchFilters.time === "afternoon" && (hour < 12 || hour >= 18)) return false;
            if (searchFilters.time === "evening" && (hour < 18 || hour < 6)) return false;
        }
        // Price filter
        if (searchFilters.priceMin && f.price < searchFilters.priceMin) return false;
        if (searchFilters.priceMax && f.price > searchFilters.priceMax) return false;
        return true;
    });
    // Re-render flight list
    const listEl = document.getElementById("flightResultsList");
    if (listEl) {
        if (filtered.length === 0) {
            listEl.innerHTML = `<div class="empty-state-enhanced"><div class="empty-icon">🔍</div><h4>没有符合条件的航班</h4><p>试试调整筛选条件</p></div>`;
        } else {
            const cheapest = Math.min(...filtered.map(f => f.price));
            listEl.innerHTML = filtered.map(f => renderFlightCard(f, f.price <= cheapest)).join("");
        }
    }
    // Update count
    const countEl = document.querySelector(".search-summary-count");
    if (countEl) countEl.textContent = `共 ${filtered.length} 个航班 (筛选自 ${flights.length})`;
}

function resetFilters() {
    searchFilters = { stops: "all", time: "all", priceMin: null, priceMax: null };
    document.querySelectorAll(".filter-chip").forEach(c => {
        c.classList.toggle("active", c.dataset.value === "all");
    });
    document.getElementById("filterPriceMin").value = "";
    document.getElementById("filterPriceMax").value = "";
    applyFilters();
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
