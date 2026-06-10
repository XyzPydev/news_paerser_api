// Global state management
const state = {
    limit: 10,
    offset: 0,
    search: '',
    source: '',
    language: '',
    total: 0,
    currentPage: 1,
    knownLanguages: new Set(),
    lastMaxId: null,
    refreshIntervalSeconds: 30,
    refreshCountdown: 30,
    refreshTimerId: null,
    ws: null,
    wsConnected: false,
    wsReconnectDelay: 2000,
};

// DOM Elements
const newsContainer = document.getElementById('news-container');
const searchInput = document.getElementById('search-input');
const sourceFilter = document.getElementById('source-filter');
const langFilter = document.getElementById('lang-filter');
const prevBtn = document.getElementById('prev-btn');
const nextBtn = document.getElementById('next-btn');
const pageInfo = document.getElementById('page-info');
const refreshBtn = document.getElementById('refresh-btn');
const refreshText = document.getElementById('refresh-text');
const wsIndicator = document.getElementById('ws-indicator');
const wsDot = document.getElementById('ws-dot');

// Stats DOM Elements
const statTotal = document.getElementById('stat-total');
const statTelegram = document.getElementById('stat-telegram');
const statLanguages = document.getElementById('stat-languages');
const statMedia = document.getElementById('stat-media');
const toast = document.getElementById('toast');
const toastMessage = document.getElementById('toast-message');
const toastIcon = document.getElementById('toast-icon');

// Initialize Dashboard
document.addEventListener('DOMContentLoaded', () => {
    fetchData();
    startCountdown();
    setupEventListeners();
    connectWebSocket();
});

// ─── WebSocket Real-Time Feed ────────────────────────────────────────────────

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    const ws = new WebSocket(wsUrl);
    state.ws = ws;

    ws.addEventListener('open', () => {
        state.wsConnected = true;
        state.wsReconnectDelay = 2000;
        updateWsStatus(true);
        console.log('[WS] Connected to', wsUrl);
    });

    ws.addEventListener('message', (event) => {
        try {
            const data = JSON.parse(event.data);
            handleRealTimeEvent(data);
        } catch (e) {
            console.warn('[WS] Could not parse message:', event.data);
        }
    });

    ws.addEventListener('close', () => {
        state.wsConnected = false;
        updateWsStatus(false);
        console.warn('[WS] Disconnected. Reconnecting in', state.wsReconnectDelay, 'ms...');
        // Exponential back-off capped at 30s
        setTimeout(connectWebSocket, state.wsReconnectDelay);
        state.wsReconnectDelay = Math.min(state.wsReconnectDelay * 1.5, 30000);
    });

    ws.addEventListener('error', (err) => {
        console.error('[WS] Error:', err);
    });
}

function handleRealTimeEvent(data) {
    const channel = data._channel || '';
    const isEnriched = channel.includes('enriched') || data.type === 'telegram.news.enriched';

    if (isEnriched) {
        // Update existing card's sentiment badge if on page 1
        updateCardSentiment(data);
        return;
    }

    // Only prepend on page 1, no active filters
    if (state.currentPage === 1 && !state.search && !state.source && !state.language) {
        prependNewsCard(data);
        // Update counters
        const newTotal = state.total + 1;
        animateValue(statTotal, state.total, newTotal, 400);
        state.total = newTotal;
        state.lastMaxId = Math.max(state.lastMaxId || 0, data.message?.id || 0);
    }

    showToast('🔴 Live: New article received!', 'live');
    fetchStats(); // refresh stats silently
}

function prependNewsCard(data) {
    // Remove skeleton if it's still there
    const skeletons = newsContainer.querySelectorAll('.skeleton-card');
    skeletons.forEach(s => s.remove());

    const msg = data.message || {};
    const ch = data.channel || {};
    const displayTitle = ch.title || ch.username || 'Telegram Channel';
    const timeAgo = formatRelativeTime(msg.published_at || new Date().toISOString());

    let badgesHtml = `<span class="badge badge-source">${escapeHtml(data.source || '')}</span>`;
    if (msg.detected_language && msg.detected_language !== 'en') {
        badgesHtml += `<span class="badge badge-lang">${msg.detected_language}</span>`;
    }
    if (msg.has_media) {
        badgesHtml += `<span class="badge badge-media"><i class="fa-solid fa-image"></i> Media</span>`;
    }
    badgesHtml += `<span class="badge badge-live"><i class="fa-solid fa-circle-dot"></i> Live</span>`;

    const translationText = msg.translated_text || msg.raw_text || '';
    let showOriginalBtn = '';
    if (msg.detected_language && msg.detected_language !== 'en' && msg.translated_text) {
        showOriginalBtn = `
            <button class="original-toggle-btn" onclick="toggleOriginal(this)">
                <i class="fa-solid fa-chevron-down"></i> Show Original (${msg.detected_language})
            </button>
            <div class="original-text-panel">${escapeHtml(msg.raw_text || '')}</div>
        `;
    }

    const card = document.createElement('div');
    card.className = 'news-card glass-card animate-slide-in';
    card.dataset.messageId = msg.id || '';
    card.innerHTML = `
        <div class="card-header">
            <div class="card-meta">
                <span class="channel-tag">
                    <i class="fa-solid fa-circle-nodes"></i> ${escapeHtml(displayTitle)}
                </span>
                ${badgesHtml}
            </div>
            <div class="card-time">
                <i class="fa-regular fa-clock"></i> ${timeAgo}
            </div>
        </div>
        <div class="card-body">
            ${msg.detected_language && msg.detected_language !== 'en' ? '<div class="translated-title">Translation (EN)</div>' : ''}
            <div class="translation-text">${escapeHtml(translationText)}</div>
            ${showOriginalBtn}
        </div>
        <div class="card-footer">
            ${msg.url ? `
                <a href="${msg.url}" target="_blank" class="card-link">
                    View post <i class="fa-solid fa-arrow-up-right-from-square"></i>
                </a>
            ` : '<span></span>'}
            <div class="sentiment-badge" id="sentiment-${msg.id}"></div>
        </div>
    `;

    // Limit cards to `state.limit` on real-time inserts
    newsContainer.insertBefore(card, newsContainer.firstChild);
    const cards = newsContainer.querySelectorAll('.news-card');
    if (cards.length > state.limit) {
        cards[cards.length - 1].remove();
    }
}

function updateCardSentiment(data) {
    const msg = data.message || {};
    const msgId = msg.id;
    if (!msgId) return;

    const badge = document.getElementById(`sentiment-${msgId}`);
    if (!badge) return;

    const sentiment = data.sentiment || 'neutral';
    const icons = { positive: 'fa-arrow-trend-up', negative: 'fa-arrow-trend-down', neutral: 'fa-minus' };
    const icon = icons[sentiment] || 'fa-minus';
    badge.innerHTML = `<span class="badge badge-sentiment-${sentiment}"><i class="fa-solid ${icon}"></i> ${sentiment}</span>`;
}

function updateWsStatus(connected) {
    if (!wsIndicator || !wsDot) return;
    if (connected) {
        wsDot.className = 'indicator-dot online';
        wsIndicator.querySelector('span:last-child').textContent = 'WebSocket: Live';
        // Switch to longer polling interval since WS handles real-time
        state.refreshIntervalSeconds = 60;
        state.refreshCountdown = 60;
    } else {
        wsDot.className = 'indicator-dot offline';
        wsIndicator.querySelector('span:last-child').textContent = 'Reconnecting...';
        // Revert to faster polling as fallback
        state.refreshIntervalSeconds = 10;
        state.refreshCountdown = 10;
    }
}

// ─── Event Listeners ─────────────────────────────────────────────────────────

function setupEventListeners() {
    // Search input with debounce
    let debounceTimer;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            state.search = e.target.value.trim();
            state.offset = 0;
            state.currentPage = 1;
            fetchData();
        }, 400);
    });

    // Filters
    sourceFilter.addEventListener('change', (e) => {
        state.source = e.target.value;
        state.offset = 0;
        state.currentPage = 1;
        fetchData();
    });

    langFilter.addEventListener('change', (e) => {
        state.language = e.target.value;
        state.offset = 0;
        state.currentPage = 1;
        fetchData();
    });

    // Pagination
    prevBtn.addEventListener('click', () => {
        if (state.currentPage > 1) {
            state.currentPage--;
            state.offset = (state.currentPage - 1) * state.limit;
            fetchData();
        }
    });

    nextBtn.addEventListener('click', () => {
        const totalPages = Math.ceil(state.total / state.limit);
        if (state.currentPage < totalPages) {
            state.currentPage++;
            state.offset = (state.currentPage - 1) * state.limit;
            fetchData();
        }
    });

    // Manual Refresh
    refreshBtn.addEventListener('click', () => {
        const icon = refreshBtn.querySelector('i');
        icon.classList.add('fa-spin');
        state.refreshCountdown = state.refreshIntervalSeconds;
        fetchData().finally(() => {
            setTimeout(() => icon.classList.remove('fa-spin'), 500);
        });
    });
}

// ─── Auto-refresh Countdown ──────────────────────────────────────────────────

function startCountdown() {
    if (state.refreshTimerId) clearInterval(state.refreshTimerId);

    state.refreshTimerId = setInterval(() => {
        state.refreshCountdown--;
        if (state.refreshCountdown <= 0) {
            state.refreshCountdown = state.refreshIntervalSeconds;
            if (!state.wsConnected) {
                fetchSilent();
            } else {
                fetchStats(); // still refresh stats periodically
            }
        }
        if (!state.wsConnected) {
            if (refreshText) refreshText.textContent = `Polling: Refresh in ${state.refreshCountdown}s`;
        }
    }, 1000);
}

// ─── Data Fetching ───────────────────────────────────────────────────────────

async function fetchData() {
    showSkeleton();
    try {
        await Promise.all([fetchNews(), fetchStats()]);
    } catch (error) {
        console.error('Error loading dashboard data:', error);
        newsContainer.innerHTML = `
            <div class="no-data-card glass-card">
                <i class="fa-solid fa-triangle-exclamation" style="color: var(--accent);"></i>
                <h3>Failed to load dashboard data</h3>
                <p>Verify that the API server is running and database is connected.</p>
            </div>
        `;
    }
}

async function fetchSilent() {
    try {
        const previousMaxId = state.lastMaxId;
        await Promise.all([fetchNews(true), fetchStats()]);
        if (previousMaxId !== null && state.lastMaxId > previousMaxId) {
            showToast('New articles parsed!', 'new');
        }
    } catch (e) {
        console.warn('Silent refresh failed', e);
    }
}

async function fetchNews(isSilent = false) {
    let url = `/api/v1/news?limit=${state.limit}&offset=${state.offset}`;
    if (state.source) url += `&source=${state.source}`;
    if (state.language) url += `&language=${state.language}`;
    if (state.search) url += `&search=${encodeURIComponent(state.search)}`;

    const response = await fetch(url);
    if (!response.ok) throw new Error('Failed to fetch news');

    const data = await response.json();
    state.total = data.total;

    if (data.items && data.items.length > 0) {
        state.lastMaxId = Math.max(...data.items.map(item => item.id || item.message_id || 0));
    }

    renderNewsList(data.items);
    updatePaginationControls();
}

async function fetchStats() {
    // Correct endpoint: /api/v1/news/stats
    const response = await fetch('/api/v1/news/stats');
    if (!response.ok) throw new Error('Failed to fetch stats');

    const stats = await response.json();

    animateValue(statTotal, parseInt(statTotal.textContent) || 0, stats.total_articles, 600);
    animateValue(statTelegram, parseInt(statTelegram.textContent) || 0, stats.by_source?.telegram || 0, 600);
    animateValue(statMedia, parseInt(statMedia.textContent) || 0, stats.with_media || 0, 600);

    const totalLanguages = Object.keys(stats.by_language || {}).filter(l => l !== 'unknown').length;
    animateValue(statLanguages, parseInt(statLanguages.textContent) || 0, totalLanguages, 600);

    updateLanguageDropdown(Object.keys(stats.by_language || {}));
}

// ─── Rendering ───────────────────────────────────────────────────────────────

function renderNewsList(items) {
    if (!items || items.length === 0) {
        newsContainer.innerHTML = `
            <div class="no-data-card glass-card animate-fade-in">
                <i class="fa-solid fa-folder-open"></i>
                <h3>No articles found</h3>
                <p>Try clearing filters or search parameters.</p>
            </div>
        `;
        return;
    }

    newsContainer.innerHTML = '';
    items.forEach((item, index) => {
        const card = document.createElement('div');
        card.className = 'news-card glass-card animate-fade-in';
        card.style.animationDelay = `${index * 0.05}s`;
        if (item.message_id) card.dataset.messageId = item.message_id;

        const timeAgo = formatRelativeTime(item.published_at);
        const displayTitle = item.channel_title || item.channel_username || 'Telegram Channel';

        let badgesHtml = `<span class="badge badge-source">${escapeHtml(item.source)}</span>`;
        if (item.detected_language && item.detected_language !== 'en') {
            badgesHtml += `<span class="badge badge-lang">${item.detected_language}</span>`;
        }
        if (item.has_media) {
            badgesHtml += `<span class="badge badge-media"><i class="fa-solid fa-image"></i> Media</span>`;
        }

        // Sentiment badge
        let sentimentHtml = '';
        if (item.sentiment) {
            const icons = { positive: 'fa-arrow-trend-up', negative: 'fa-arrow-trend-down', neutral: 'fa-minus' };
            const icon = icons[item.sentiment] || 'fa-minus';
            sentimentHtml = `<span class="badge badge-sentiment-${item.sentiment}"><i class="fa-solid ${icon}"></i> ${item.sentiment}</span>`;
        }

        const translationText = item.translated_text || item.raw_text;
        let showOriginalBtn = '';
        if (item.detected_language && item.detected_language !== 'en' && item.translated_text) {
            showOriginalBtn = `
                <button class="original-toggle-btn" onclick="toggleOriginal(this)">
                    <i class="fa-solid fa-chevron-down"></i> Show Original (${item.detected_language})
                </button>
                <div class="original-text-panel">${escapeHtml(item.raw_text)}</div>
            `;
        }

        card.innerHTML = `
            <div class="card-header">
                <div class="card-meta">
                    <span class="channel-tag">
                        <i class="fa-solid fa-circle-nodes"></i> ${escapeHtml(displayTitle)}
                    </span>
                    ${badgesHtml}
                </div>
                <div class="card-time">
                    <i class="fa-regular fa-clock"></i> ${timeAgo}
                </div>
            </div>
            <div class="card-body">
                ${item.detected_language && item.detected_language !== 'en' ? '<div class="translated-title">Translation (EN)</div>' : ''}
                <div class="translation-text">${escapeHtml(translationText)}</div>
                ${showOriginalBtn}
            </div>
            <div class="card-footer">
                ${item.url ? `
                    <a href="${item.url}" target="_blank" class="card-link">
                        View post <i class="fa-solid fa-arrow-up-right-from-square"></i>
                    </a>
                ` : '<span></span>'}
                <div class="provider-and-sentiment">
                    <div class="provider-info">via ${escapeHtml(item.provider)}</div>
                    <div class="sentiment-badge" id="sentiment-${item.message_id}">${sentimentHtml}</div>
                </div>
            </div>
        `;
        newsContainer.appendChild(card);
    });
}

// ─── UI Helpers ──────────────────────────────────────────────────────────────

function updatePaginationControls() {
    const totalPages = Math.ceil(state.total / state.limit) || 1;
    pageInfo.textContent = `Page ${state.currentPage} of ${totalPages} (${state.total} total)`;
    prevBtn.disabled = state.currentPage <= 1;
    nextBtn.disabled = state.currentPage >= totalPages;
}

function showSkeleton() {
    newsContainer.innerHTML = `
        <div class="skeleton-card glass-card"></div>
        <div class="skeleton-card glass-card"></div>
        <div class="skeleton-card glass-card"></div>
    `;
}

window.toggleOriginal = function (button) {
    const panel = button.nextElementSibling;
    if (panel.classList.contains('expanded')) {
        panel.classList.remove('expanded');
        button.innerHTML = `<i class="fa-solid fa-chevron-down"></i> Show Original`;
    } else {
        panel.classList.add('expanded');
        button.innerHTML = `<i class="fa-solid fa-chevron-up"></i> Hide Original`;
    }
};

function updateLanguageDropdown(languages) {
    languages.forEach(lang => {
        if (lang !== 'unknown' && !state.knownLanguages.has(lang)) {
            state.knownLanguages.add(lang);
            const option = document.createElement('option');
            option.value = lang;
            option.textContent = lang.toUpperCase();
            langFilter.appendChild(option);
        }
    });
}

function formatRelativeTime(dateStr) {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function showToast(message, type = 'new') {
    if (!toast || !toastMessage) return;
    toastMessage.textContent = message;
    if (toastIcon) {
        toastIcon.className = type === 'live'
            ? 'fa-solid fa-circle-dot'
            : 'fa-solid fa-circle-check';
        toastIcon.style.color = type === 'live' ? 'var(--accent)' : 'var(--success)';
    }
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 4000);
}

function animateValue(obj, start, end, duration) {
    if (start === end) return;
    let startTimestamp = null;
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        obj.innerHTML = Math.floor(progress * (end - start) + start);
        if (progress < 1) window.requestAnimationFrame(step);
    };
    window.requestAnimationFrame(step);
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
