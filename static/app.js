console.log("🚀 FeedLite JS Starting...");

document.addEventListener('DOMContentLoaded', () => {
    console.log("✅ DOM Content Loaded");

    // Unified handling for backend exceptions that might return plain text 500 instead of JSON.
    const readApiResponse = async (res) => {
        const contentType = res.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            return await res.json();
        }

        const text = await res.text();
        return {
            detail: text || `HTTP ${res.status}`
        };
    };

    // --- API Fetch Wrapper (Auth Interceptor) ---
    const apiFetch = async (url, options = {}) => {
        const token = localStorage.getItem('feedlite_token');
        if (token) {
            options.headers = {
                ...options.headers,
                'Authorization': `Bearer ${token}`
            };
        }
        const res = await fetch(url, options);
        if (res.status === 401) {
            localStorage.removeItem('feedlite_token');
            const overlay = document.getElementById('login-overlay');
            if (overlay) overlay.classList.add('active');
            throw new Error('Unauthorized');
        }
        return res;
    };

    // --- Login Logic ---
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = e.target.querySelector('button');
            const err = document.getElementById('login-error');
            btn.textContent = 'Logging in...';
            err.textContent = '';

            try {
                // Must use native fetch for login to avoid loops
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        username: e.target['login-user'].value,
                        password: e.target['login-pass'].value
                    })
                });

                if (res.ok) {
                    const data = await res.json();
                    localStorage.setItem('feedlite_token', data.access_token);
                    document.getElementById('login-overlay').classList.remove('active');
                    window.location.reload();
                } else {
                    err.textContent = 'Invalid username or password';
                }
            } catch (error) {
                err.textContent = 'Network error';
            } finally {
                btn.textContent = 'Enter';
            }
        });
    }

    // --- Theme Management ---
    const themeToggle = document.getElementById('theme-toggle');
    const applyTheme = (theme) => {
        let isDark = true;

        if (theme === 'light') {
            document.body.classList.add('light-mode');
            isDark = false;
        } else if (theme === 'dark') {
            document.body.classList.remove('light-mode');
            isDark = true;
        } else {
            // Follow system preference
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            document.body.classList.toggle('light-mode', !prefersDark);
            isDark = prefersDark;
        }

        if (isDark) {
            themeToggle.innerHTML = '<i data-lucide="moon"></i>';
        } else {
            themeToggle.innerHTML = '<i data-lucide="sun"></i>';
        }

        lucide.createIcons();
    };

    const savedTheme = localStorage.getItem('theme') || 'auto';
    applyTheme(savedTheme);

    themeToggle.addEventListener('click', () => {
        const isLight = document.body.classList.contains('light-mode');
        const newTheme = isLight ? 'dark' : 'light';
        localStorage.setItem('theme', newTheme);
        applyTheme(newTheme);
    });

    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
        if (localStorage.getItem('theme') === 'auto') applyTheme('auto');
    });

    // --- Modal Logic ---
    const setupModal = (btnId, modalId) => {
        const btn = document.getElementById(btnId);
        const modal = document.getElementById(modalId);
        if (!btn || !modal) return;
        const closeBtn = modal.querySelector('.close-modal');

        const closeModal = () => {
            modal.style.display = 'none';
            if (modalId === 'modal-subs') {
                resetSubsModal();
            }
        };

        btn.onclick = () => {
            modal.style.display = 'block';
            if (modalId === 'modal-subs') {
                const listTab = modal.querySelector('[data-tab="tab-list"]');
                if (listTab && listTab.classList.contains('active')) {
                    loadSubsList();
                }
            }
        };
        if (closeBtn) closeBtn.onclick = closeModal;
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        });
    };
    setupModal('nav-subs', 'modal-subs');
    setupModal('nav-profile', 'modal-profile');

    const resetSubsModal = () => {
        const urlInput = document.getElementById('new-sub-url');
        const previewContainer = document.getElementById('preview-container');
        const categorySelect = document.getElementById('new-sub-category');
        const categoryText = document.querySelector('#custom-category-dropdown .custom-select-text');
        const categoryOptions = document.querySelectorAll('#custom-category-dropdown .custom-select-options li');

        if (urlInput) urlInput.value = '';
        if (previewContainer) {
            previewContainer.classList.add('hidden');
            const previewList = previewContainer.querySelector('.preview-list');
            if (previewList) previewList.innerHTML = '';
        }
        if (categorySelect) categorySelect.value = '';
        if (categoryText) categoryText.textContent = 'Select Category';
        if (categoryOptions) categoryOptions.forEach(opt => opt.classList.remove('selected'));
        lastPreviewData = null;

        document.querySelectorAll('.preview-area').forEach(area => {
            if (area.id !== 'preview-container') {
                area.classList.add('hidden');
                area.innerHTML = '';
            }
        });
        document.querySelectorAll('.btn-preview-list-sub').forEach(btn => {
            btn.innerHTML = '<i data-lucide="eye"></i>';
        });
        lucide.createIcons();
    };

    // --- Tab Switching ---
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;
            btn.parentElement.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.closest('.modal-content').querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            const targetPane = document.getElementById(tabId);
            if (targetPane) targetPane.classList.add('active');

            if (tabId === 'tab-list') {
                loadSubsList();
            }
        });
    });

    // --- Preview & Subscription Management ---
    const renderPreview = (container, data) => {
        if (!container) return;
        container.innerHTML = data.map(item => `
            <div class="preview-item">
                <h5>${item.title}</h5>
                <small>${item.published || ''}</small>
            </div>
        `).join('');
    };

    document.addEventListener('click', e => {
        const foldBtn = e.target.closest('.btn-fold');
        if (foldBtn) {
            foldBtn.closest('.preview-area').classList.add('hidden');
        }
    });

    // --- Custom Category Dropdown ---
    const categoryDropdown = document.getElementById('custom-category-dropdown');
    if (categoryDropdown) {
        const trigger = categoryDropdown.querySelector('.custom-select-trigger');
        const options = categoryDropdown.querySelectorAll('.custom-select-options li');
        const hiddenInput = document.getElementById('new-sub-category');
        const textSpan = categoryDropdown.querySelector('.custom-select-text');

        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            categoryDropdown.classList.toggle('open');
        });

        options.forEach(option => {
            option.addEventListener('click', (e) => {
                e.stopPropagation();
                textSpan.textContent = option.textContent;
                hiddenInput.value = option.dataset.value;
                options.forEach(opt => opt.classList.remove('selected'));
                option.classList.add('selected');
                categoryDropdown.classList.remove('open');
            });
        });

        document.addEventListener('click', (e) => {
            if (!categoryDropdown.contains(e.target)) {
                categoryDropdown.classList.remove('open');
            }
        });
    }

    // Add New Source - Preview
    let lastPreviewData = null;
    const previewNewBtn = document.getElementById('preview-new-btn');
    if (previewNewBtn) {
        previewNewBtn.addEventListener('click', async () => {
            const urlInput = document.getElementById('new-sub-url');
            const url = urlInput.value.trim();
            if (!url) return;

            previewNewBtn.innerHTML = '<i data-lucide="loader-circle" class="lucide-spin"></i>';
            lucide.createIcons();
            try {
                const res = await apiFetch(`/api/sources/preview?url=${encodeURIComponent(url)}`, { method: 'POST' });
                const data = await readApiResponse(res);
                if (!res.ok) throw new Error(data.detail || 'Preview failed');

                lastPreviewData = data;
                document.getElementById('preview-title-text').textContent = data.feed_title || 'Untitled Source';
                document.getElementById('preview-container').classList.remove('hidden');
                renderPreview(document.getElementById('preview-container').querySelector('.preview-list'), data.articles);
            } catch (e) {
                alert('Preview failed: ' + e.message);
            } finally {
                previewNewBtn.innerHTML = '<i data-lucide="eye"></i>';
                lucide.createIcons();
            }
        });
    }

    // Add New Source - Confirm Add
    const confirmAddBtn = document.getElementById('confirm-add-btn');
    if (confirmAddBtn) {
        confirmAddBtn.addEventListener('click', async () => {
            const urlInput = document.getElementById('new-sub-url');
            const url = urlInput.value.trim();
            const categorySelect = document.getElementById('new-sub-category');
            if (!url) return;
            if (!categorySelect.value) {
                alert("Please select a category first!");
                return;
            }

            confirmAddBtn.innerHTML = '<i data-lucide="loader-circle" class="lucide-spin"></i>';
            try {
                const feedTitle = lastPreviewData?.feed_title || '';
                const category = categorySelect.value;
                const res = await apiFetch(`/api/sources/?url=${encodeURIComponent(url)}&title=${encodeURIComponent(feedTitle)}&category=${category}`, { method: 'POST' });
                const data = await readApiResponse(res);
                if (!res.ok) throw new Error(data.detail || 'Failed to add source');

                alert('✅ Source added successfully!');
                urlInput.value = '';
                confirmAddBtn.disabled = true;
                document.getElementById('preview-container').classList.add('hidden');
                lastPreviewData = null;
            } catch (e) {
                alert('Failed to add: ' + e.message);
            } finally {
                confirmAddBtn.innerHTML = '<i data-lucide="plus"></i>';
                lucide.createIcons();
            }
        });
    }

    // My Subscriptions - Load List
    const loadSubsList = async () => {
        const container = document.getElementById('my-subs-list');
        if (!container) return;
        try {
            const res = await apiFetch('/api/sources/');
            const feeds = await res.json();
            container.innerHTML = feeds.map(f => {
                const catIcon = CATEGORY_MAP[f.category]?.icon || 'layers';
                return `
                <div class="sub-item-card" data-id="${f.id}">
                    <div style="display:flex; align-items:center; gap:12px; flex:1; min-width:0;">
                        <i data-lucide="${catIcon}" style="color:var(--text-muted); flex-shrink:0;"></i>
                        <div class="sub-item-info">
                            <span class="sub-name">${f.title || f.url}</span>
                            <span class="sub-url">${f.url}</span>
                        </div>
                    </div>
                    <div class="sub-item-actions">
                        <button class="btn-action btn-preview-list-sub" data-url="${f.url}" title="Preview latest content"><i data-lucide="eye"></i></button>
                        <button class="btn-action btn-delete-sub" title="Delete subscription"><i data-lucide="trash-2"></i></button>
                    </div>
                </div>
                <div id="list-preview-${f.id}" class="preview-area hidden" style="margin-top: -8px; margin-bottom: 12px; background: rgba(0,0,0,0.2); border-radius: 0 0 12px 12px;"></div>
            `;
            }).join('');
            lucide.createIcons();
        } catch (e) {
            container.innerHTML = '<div class="loading-trigger">Failed to load</div>';
        }
    };

    // My Subscriptions - Delete
    document.addEventListener('click', async (e) => {
        const delBtn = e.target.closest('.btn-delete-sub');
        if (!delBtn) return;
        const card = delBtn.closest('.sub-item-card');
        const id = card.dataset.id;
        if (!confirm('Confirm delete this subscription?')) return;

        try {
            const res = await apiFetch(`/api/sources/${id}`, { method: 'DELETE' });
            if (res.ok) {
                card.remove();
                document.getElementById(`list-preview-${id}`)?.remove();
            }
        } catch (e) {
            alert('Delete failed');
        }
    });

    // My Subscriptions - Inline Preview
    document.addEventListener('click', async (e) => {
        const previewBtn = e.target.closest('.btn-preview-list-sub');
        if (!previewBtn) return;

        const card = previewBtn.closest('.sub-item-card');
        const id = card.dataset.id;
        const url = previewBtn.dataset.url;
        const previewBox = document.getElementById(`list-preview-${id}`);

        if (!previewBox.classList.contains('hidden')) {
            previewBox.classList.add('hidden');
            previewBox.innerHTML = '';
            previewBtn.innerHTML = '<i data-lucide="eye"></i>';
            lucide.createIcons();
            return;
        }

        previewBtn.innerHTML = '<i data-lucide="loader-circle" class="lucide-spin"></i>';
        lucide.createIcons();
        try {
            const res = await apiFetch(`/api/sources/preview?url=${encodeURIComponent(url)}`, { method: 'POST' });
            const data = await readApiResponse(res);
            if (!res.ok) throw new Error(data.detail || 'Preview detection failed');

            previewBox.classList.remove('hidden');
            previewBox.innerHTML = `
                <div class="preview-list"></div>
            `;
            renderPreview(previewBox.querySelector('.preview-list'), data.articles);
        } catch (err) {
            alert('Preview failed: ' + err.message);
        } finally {
            previewBtn.innerHTML = '<i data-lucide="chevron-up"></i>';
            lucide.createIcons();
        }
    });

    // --- Article Loading & Rendering ---
    const feedStream = document.getElementById('feed-stream');
    const loadingTrigger = document.getElementById('loading');
    const searchState = document.getElementById('search-state');
    const searchStateQuery = document.getElementById('search-state-query');
    const clearSearchBtn = document.getElementById('clear-search');
    let offset = 0;
    const limit = 20;
    let isLoading = false;
    let lastDateStr = "";
    let currentSearchQuery = "";

    const escapeHtml = (str) => {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    const escapeRegExp = (str) => String(str).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

    const getSearchTokens = (query) => {
        if (!query) return [];
        const normalized = query
            .toLowerCase()
            .replace(/[^\w\u4e00-\u9fff]+/g, ' ')
            .trim();
        if (!normalized) return [];

        const rawTokens = normalized.split(/\s+/).filter(Boolean);
        return [...new Set(rawTokens)].sort((a, b) => b.length - a.length);
    };

    const highlightText = (text, query) => {
        const safeText = escapeHtml(text || '');
        const tokens = getSearchTokens(query);
        if (!safeText || tokens.length === 0) return safeText;

        const pattern = new RegExp(`(${tokens.map(escapeRegExp).join('|')})`, 'gi');
        return safeText.replace(pattern, '<mark class="search-highlight">$1</mark>');
    };

    const updateSearchState = (query = "") => {
        currentSearchQuery = query.trim();
        const searching = Boolean(currentSearchQuery);

        if (searchState) {
            searchState.classList.toggle('hidden', !searching);
        }
        if (searchStateQuery) {
            searchStateQuery.textContent = searching ? `"${currentSearchQuery}"` : '';
        }
        if (loadingTrigger) {
            loadingTrigger.textContent = searching ? 'All search results displayed' : 'Loading...';
        }
    };

    const resetFeedStream = () => {
        lastDateStr = "";
        const indicator = document.getElementById('pull-to-refresh');
        const loader = document.getElementById('loading');
        feedStream.innerHTML = '';
        if (searchState) feedStream.appendChild(searchState);
        if (indicator) feedStream.appendChild(indicator);
        if (loader) feedStream.appendChild(loader);
    };

    const formatDate = (dateObj) => {
        const year = dateObj.getFullYear();
        const month = String(dateObj.getMonth() + 1).padStart(2, '0');
        const date = String(dateObj.getDate()).padStart(2, '0');
        const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const day = days[dateObj.getDay()];

        const today = new Date();
        const isToday = dateObj.toDateString() === today.toDateString();
        const yesterday = new Date(today);
        yesterday.setDate(today.getDate() - 1);
        const isYesterday = dateObj.toDateString() === yesterday.toDateString();

        const prefix = isToday ? "Today" : (isYesterday ? "Yesterday" : "");
        return `${prefix ? prefix + ' · ' : ''}${year}-${month}-${date} ${day}`;
    };

    const formatTime = (dateObj) => {
        const hh = String(dateObj.getHours()).padStart(2, '0');
        const mm = String(dateObj.getMinutes()).padStart(2, '0');
        return `${hh}:${mm}`;
    };

    const getScoreClass = (score) => {
        if (score >= 80) return 'high';
        if (score >= 50) return 'mid';
        return 'low';
    };

    const CATEGORY_MAP = {
        1: { name: 'News & Biz', icon: 'briefcase' },
        2: { name: 'Tech & Dev', icon: 'cpu' },
        3: { name: 'Games & Ent', icon: 'gamepad-2' },
        4: { name: 'Lifestyle', icon: 'coffee' },
        5: { name: 'General', icon: 'layers' }
    };

    const renderArticle = (article) => {
        let rawDateStr = article.published_at || article.published || article.created_at;
        if (rawDateStr && typeof rawDateStr === 'string' && !rawDateStr.includes('Z') && !rawDateStr.match(/[+-]\d{2}:?\d{2}$/)) {
            rawDateStr = String(rawDateStr).replace(" ", "T") + "Z";
        }

        const pubDate = new Date(rawDateStr);
        const dateStr = formatDate(pubDate);
        let html = "";

        if (dateStr !== lastDateStr) {
            html += `<div class="date-divider">${dateStr}</div>`;
            lastDateStr = dateStr;
        }

        const score = Math.round(article.ai_score || 0);
        const scoreClass = getScoreClass(score);
        const rawExcerpt = currentSearchQuery
            ? (article.search_excerpt || article.description || article.content || 'No preview available')
            : (article.description
                ? (article.description.length > 120 ? article.description.substring(0, 120) + '...' : article.description)
                : 'No preview available');
        const excerptHtml = currentSearchQuery
            ? highlightText(rawExcerpt, currentSearchQuery)
            : escapeHtml(rawExcerpt);
        const titleHtml = currentSearchQuery
            ? highlightText(article.title, currentSearchQuery)
            : escapeHtml(article.title);

        const categoryData = CATEGORY_MAP[article.category] || { name: 'General', icon: 'layers' };

        const escapeAttr = (str) => {
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/"/g, '&quot;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        };
        const escapedTitle = escapeAttr(article.title);
        const escapedDesc = escapeAttr(rawExcerpt || 'No preview available');

        html += `
            <article class="article-card" data-id="${article.id}">
                <div class="card-header-inline">
                    <div class="header-left">
                        <span class="source-tag" title="${categoryData.name}"><i data-lucide="${categoryData.icon}"></i></span>
                        <h2 class="article-title" title="${escapedTitle}">${titleHtml}</h2>
                    </div>
                    <div class="header-right-meta">
                        <span class="pub-time">${formatTime(pubDate)}</span>
                        <span class="ai-score ${scoreClass}">${score}</span>
                        <div class="action-menu-container">
                            <button class="btn-more-options" title="More options"><i data-lucide="more-horizontal"></i></button>
                            <div class="action-dropdown">
                                <a href="${article.link}" target="_blank" rel="noopener" class="dropdown-item" title="View original"><i data-lucide="external-link"></i></a>
                                <button class="dropdown-item btn-not-interest ${article.feedback === -1 ? 'active' : ''}" data-type="-1" title="Not interested"><i data-lucide="thumbs-down"></i></button>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="excerpt-with-like">
                    <p class="article-excerpt" title="${escapedDesc}">${excerptHtml}</p>
                    <button class="btn-action btn-interest inline-like ${article.feedback === 1 ? 'active' : ''}" data-type="1" title="Interested"><i data-lucide="thumbs-up"></i></button>
                </div>
            </article>
        `;
        return html;
    };

    const loadArticles = async (reset = false) => {
        if (isLoading) return;
        if (currentSearchQuery && !reset) return;
        isLoading = true;

        if (reset) {
            offset = 0;
            updateSearchState("");
            resetFeedStream();
        }

        const loader = document.getElementById('loading');

        try {
            const response = await apiFetch(`/api/articles/?limit=${limit}&offset=${offset}`);
            const articles = await response.json();

            if (articles.length > 0) {
                const fragment = document.createElement('div');
                fragment.innerHTML = articles.map(a => renderArticle(a)).join('');

                while (fragment.firstChild) {
                    feedStream.insertBefore(fragment.firstChild, loader);
                }
                offset += articles.length;
                lucide.createIcons();
            } else if (reset) {
                const emptyMsg = document.createElement('div');
                emptyMsg.className = 'loading-trigger';
                emptyMsg.textContent = 'No new content. Click Logo to refresh.';
                feedStream.insertBefore(emptyMsg, loader);
            }
        } catch (e) {
            console.error("Failed to load articles:", e);
        } finally {
            isLoading = false;
        }
    };

    const searchArticles = async (query) => {
        updateSearchState(query);
        resetFeedStream();
        const loader = document.getElementById('loading');

        try {
            const res = await apiFetch(`/api/articles/search?q=${encodeURIComponent(query)}`);
            const articles = await res.json();

            if (articles.length > 0) {
                const fragment = document.createElement('div');
                fragment.innerHTML = articles.map(a => renderArticle(a)).join('');
                while (fragment.firstChild) {
                    feedStream.insertBefore(fragment.firstChild, loader);
                }
                lucide.createIcons();
            } else {
                const emptyMsg = document.createElement('div');
                emptyMsg.className = 'loading-trigger';
                emptyMsg.textContent = `No articles found containing "${query}"`;
                feedStream.insertBefore(emptyMsg, loader);
            }
        } catch (e) {
            console.error("Search failed:", e);
        }
    };

    loadArticles(true);

    document.addEventListener('click', async (e) => {
        const dropdownItem = e.target.closest('.dropdown-item');
        if (dropdownItem) {
            const container = dropdownItem.closest('.action-menu-container');
            if (container) {
                container.classList.remove('active');
                container.querySelector('.action-dropdown').classList.remove('show');
            }
        } else if (!e.target.closest('.action-menu-container')) {
            document.querySelectorAll('.action-dropdown.show').forEach(el => el.classList.remove('show'));
            document.querySelectorAll('.action-menu-container.active').forEach(el => el.classList.remove('active'));
        }

        const moreBtn = e.target.closest('.btn-more-options');
        if (moreBtn) {
            e.stopPropagation();
            const container = moreBtn.closest('.action-menu-container');
            const dropdown = moreBtn.nextElementSibling;
            document.querySelectorAll('.action-menu-container.active').forEach(el => {
                if (el !== container) {
                    el.classList.remove('active');
                    el.querySelector('.action-dropdown').classList.remove('show');
                }
            });
            container.classList.toggle('active');
            dropdown.classList.toggle('show');
        }

        const btn = e.target.closest('.btn-interest, .btn-not-interest');
        if (btn) {
            e.stopPropagation();
            const dropdown = btn.closest('.action-dropdown');
            if (dropdown) dropdown.classList.remove('show');

            const card = btn.closest('.article-card');
            const id = card.dataset.id;
            const type = parseInt(btn.dataset.type);
            const isCancel = btn.classList.contains('active');
            const finalType = isCancel ? 0 : type;

            card.querySelectorAll('.btn-interest, .btn-not-interest').forEach(b => b.classList.remove('active'));
            if (!isCancel) {
                btn.classList.add('active');
            }

            try {
                await apiFetch(`/api/articles/${id}/feedback?type=${finalType}`, { method: 'PATCH' });
            } catch (e) {
                console.error("Feedback sync failed");
            }
        }
    });

    document.getElementById('logo-refresh').onclick = async () => {
        const searchInput = document.getElementById('search-input');
        if (searchInput) searchInput.value = '';
        toggleSearch(true);
        await refreshFeeds();
    };

    const searchToggle = document.getElementById('search-toggle');
    const searchBox = document.getElementById('header-search');
    const searchInput = document.getElementById('search-input');
    let searchOpen = false;

    const toggleSearch = (forceClose = false) => {
        if (forceClose || searchOpen) {
            searchBox.classList.remove('expanded');
            const hd = document.querySelector('.header-content');
            if (hd) hd.classList.remove('search-active');
            searchOpen = false;
            if (forceClose) searchInput.blur();
            searchToggle.innerHTML = '<i data-lucide="search"></i>';
        } else {
            searchBox.classList.add('expanded');
            const hd = document.querySelector('.header-content');
            if (hd) hd.classList.add('search-active');
            searchOpen = true;
            setTimeout(() => searchInput.focus(), 350);
            searchToggle.innerHTML = '<i data-lucide="x"></i>';
        }
        lucide.createIcons();
    };

    searchToggle.addEventListener('click', () => toggleSearch());

    searchInput.addEventListener('keydown', async (e) => {
        if (e.key === 'Escape') {
            toggleSearch(true);
            if (!searchInput.value.trim() && currentSearchQuery) {
                updateSearchState("");
                await loadArticles(true);
            }
            return;
        }
        if (e.key === 'Enter') {
            const query = searchInput.value.trim();
            if (!query) {
                updateSearchState("");
                await loadArticles(true);
                return;
            }
            await searchArticles(query);
        }
    });

    if (clearSearchBtn) {
        clearSearchBtn.addEventListener('click', async () => {
            if (searchInput) searchInput.value = '';
            updateSearchState("");
            await loadArticles(true);
        });
    }

    document.addEventListener('click', (e) => {
        if (searchOpen && !searchBox.contains(e.target) && e.target !== searchToggle) {
            toggleSearch(true);
        }
    });

    const observer = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && !isLoading) {
            loadArticles();
        }
    }, { threshold: 0.1 });
    observer.observe(loadingTrigger);

    const refreshFeeds = async () => {
        const logo = document.getElementById('logo-refresh');
        const indicator = document.getElementById('pull-to-refresh');

        logo.style.opacity = '0.5';
        indicator.classList.add('active');
        indicator.querySelector('span').textContent = 'Loading latest content...';

        try {
            await loadArticles(true);
        } catch (e) {
            alert("Refresh failed. Please check your network or configuration.");
        } finally {
            logo.style.opacity = '1';
            indicator.classList.remove('active');
            setTimeout(() => {
                indicator.querySelector('span').textContent = 'Pull to refresh...';
            }, 300);
        }
    };

    let touchStart = 0;
    window.addEventListener('touchstart', e => { touchStart = e.touches[0].pageY; }, { passive: true });
    window.addEventListener('touchmove', e => {
        const touchDiff = e.touches[0].pageY - touchStart;
        if (window.scrollY === 0 && touchDiff > 60) {
            document.getElementById('pull-to-refresh').classList.add('active');
        }
    }, { passive: true });
    window.addEventListener('touchend', () => {
        const indicator = document.getElementById('pull-to-refresh');
        if (indicator.classList.contains('active')) {
            refreshFeeds();
        }
    });

    const backToTopBtn = document.getElementById('back-to-top');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 400) {
            backToTopBtn.style.display = 'block';
            setTimeout(() => backToTopBtn.style.opacity = '1', 10);
        } else {
            backToTopBtn.style.opacity = '0';
            setTimeout(() => { if (window.scrollY <= 400) backToTopBtn.style.display = 'none'; }, 300);
        }
    }, { passive: true });

    backToTopBtn.onclick = () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    const profileModal = document.getElementById('modal-profile');
    const tagsList = document.getElementById('tags-list');
    const promptEditor = document.getElementById('system-prompt-editor');

    const loadProfile = async () => {
        try {
            const res = await apiFetch('/api/profile/');
            const data = await res.json();
            const tags = data.active_tags ? data.active_tags.split(',').map(t => t.trim()).filter(Boolean) : [];
            renderTags(tags);
            if (promptEditor) {
                promptEditor.value = data.base_prompt || '';
            }
        } catch (e) {
            console.error('Failed to load profile:', e);
        }
    };

    const renderTags = (tags) => {
        if (!tagsList) return;
        tagsList.innerHTML = ''; 

        // 1. Render existing tags
        tags.forEach(t => {
            const tagEl = document.createElement('span');
            tagEl.className = 'tag';
            tagEl.textContent = t;

            const removeBtn = document.createElement('div');
            removeBtn.className = 'tag-remove';
            removeBtn.innerHTML = '&times;';
            removeBtn.onclick = async (e) => {
                e.stopPropagation();
                try {
                    const res = await apiFetch(`/api/profile/tags?tag=${encodeURIComponent(t)}`, { method: 'DELETE' });
                    if (res.ok) {
                        loadProfile(); 
                    }
                } catch (err) {
                    console.error('Failed to delete tag:', err);
                }
            };
            tagEl.appendChild(removeBtn);
            tagsList.appendChild(tagEl);
        });

        // 2. Render "+" bubble
        const addBubble = document.createElement('div');
        addBubble.className = 'tag tag-add-bubble';
        addBubble.innerHTML = '<span class="plus-sign">+</span>';
        
        addBubble.onclick = () => {
            if (addBubble.querySelector('input')) return; 
            
            addBubble.innerHTML = '';
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'tag-input-inline';
            input.placeholder = 'New...';
            input.maxLength = 8; 
            input.autocomplete = 'off';
            
            addBubble.appendChild(input);
            input.focus();

            const submitTag = async () => {
                const val = input.value.trim();
                if (val && !tags.includes(val)) {
                    try {
                        const res = await apiFetch('/api/profile/tags', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ tag: val }),
                        });
                        if (res.ok) {
                            loadProfile(); 
                            return;
                        }
                    } catch (err) {
                        console.error('Failed to add tag:', err);
                    }
                }
                renderTags(tags); 
            };

            input.onkeydown = (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    submitTag();
                }
                if (e.key === 'Escape') renderTags(tags);
            };
            input.onblur = submitTag;
        };

        tagsList.appendChild(addBubble);
    };

    const profileBtn = document.getElementById('nav-profile');
    if (profileBtn) {
        const origClick = profileBtn.onclick;
        profileBtn.onclick = () => {
            if (origClick) origClick();
            loadProfile();
        };
    }

    lucide.createIcons();
});
