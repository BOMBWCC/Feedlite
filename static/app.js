console.log("🚀 FeedLite JS Starting...");

document.addEventListener('DOMContentLoaded', () => {
    console.log("✅ DOM Content Loaded");

    // 后端异常时可能返回纯文本 500，而不是 JSON；这里统一兜底，避免前端再报 Unexpected token。
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
            btn.textContent = '登录中...';
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
                    err.textContent = '用户名或密码错误';
                }
            } catch (error) {
                err.textContent = '网络错误';
            } finally {
                btn.textContent = '进入';
            }
        });
    }

    // --- 智能主题管理 ---
    // 默认暗色（body 无 class），亮色为 body.light-mode
    const themeToggle = document.getElementById('theme-toggle');
    const applyTheme = (theme) => {
        let isDark = true; // 用一个变量记录当前到底是不是暗色模式

        if (theme === 'light') {
            document.body.classList.add('light-mode');
            isDark = false;
        } else if (theme === 'dark') {
            document.body.classList.remove('light-mode');
            isDark = true;
        } else {
            // 跟随系统
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            document.body.classList.toggle('light-mode', !prefersDark);
            isDark = prefersDark;
        }

        // 核心修改区：动态插入对应图标的 HTML 标签
        if (isDark) {
            themeToggle.innerHTML = '<i data-lucide="moon"></i>';
        } else {
            themeToggle.innerHTML = '<i data-lucide="sun"></i>';
        }

        // 【千万别忘了这行】每次替换完里面的 HTML，都要让 Lucide 重新扫描并渲染一次
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

    // --- 弹窗逻辑 ---
    const setupModal = (btnId, modalId) => {
        const btn = document.getElementById(btnId);
        const modal = document.getElementById(modalId);
        if (!btn || !modal) return;
        const closeBtn = modal.querySelector('.close-modal');
        btn.onclick = () => modal.style.display = 'block';
        if (closeBtn) closeBtn.onclick = () => modal.style.display = 'none';
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.style.display = 'none';
        });
    };
    setupModal('nav-subs', 'modal-subs');
    setupModal('nav-profile', 'modal-profile');

    // --- 标签页切换 ---
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;
            btn.parentElement.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.closest('.modal-content').querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(tabId).classList.add('active');
        });
    });

    // --- 预览与订阅管理 ---
    const renderPreview = (container, data) => {
        container.innerHTML = data.map(item => `
            <div class="preview-item">
                <h5>${item.title}</h5>
                <small>${item.published || ''}</small>
            </div>
        `).join('');
    };

    // 统一处理折叠
    document.addEventListener('click', e => {
        if (e.target.classList.contains('btn-fold')) e.target.closest('.preview-area').classList.add('hidden');
    });

    // --- 自定义分类下拉框交互逻辑 ---
    const categoryDropdown = document.getElementById('custom-category-dropdown');
    if (categoryDropdown) {
        const trigger = categoryDropdown.querySelector('.custom-select-trigger');
        const options = categoryDropdown.querySelectorAll('.custom-select-options li');
        const hiddenInput = document.getElementById('new-sub-category');
        const textSpan = categoryDropdown.querySelector('.custom-select-text');

        // 切换下拉菜单
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            categoryDropdown.classList.toggle('open');
        });

        // 点击选项
        options.forEach(option => {
            option.addEventListener('click', (e) => {
                e.stopPropagation();
                // 更换文字与隐藏原生 input 设值
                textSpan.textContent = option.textContent;
                hiddenInput.value = option.dataset.value;
                
                // 处理选中高亮状态
                options.forEach(opt => opt.classList.remove('selected'));
                option.classList.add('selected');
                
                // 选定后自动折叠关闭
                categoryDropdown.classList.remove('open');
            });
        });

        // 防误触：点击空白区域收起拉框
        document.addEventListener('click', (e) => {
            if (!categoryDropdown.contains(e.target)) {
                categoryDropdown.classList.remove('open');
            }
        });
    }

    // 添加新源 - 预览（调用真实 RSS 抓取）
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
                if (!res.ok) throw new Error(data.detail || '预览失败');

                lastPreviewData = data;
                document.getElementById('preview-title-text').textContent = data.feed_title || '未命名订阅源';
                document.getElementById('preview-container').classList.remove('hidden');
                renderPreview(document.getElementById('preview-container').querySelector('.preview-list'), data.articles);
            } catch (e) {
                alert('预览失败: ' + e.message);
            } finally {
                previewNewBtn.innerHTML = '<i data-lucide="eye"></i>';
                lucide.createIcons();
            }
        });
    }

    // 添加新源 - 确认添加
    const confirmAddBtn = document.getElementById('confirm-add-btn');
    if (confirmAddBtn) {
        confirmAddBtn.addEventListener('click', async () => {
            const urlInput = document.getElementById('new-sub-url');
            const url = urlInput.value.trim();
            const categorySelect = document.getElementById('new-sub-category');
            if (!url) return;
            if (!categorySelect.value) {
                alert("请先选择一个订阅分类！");
                return;
            }

            confirmAddBtn.innerHTML = '<i data-lucide="loader-circle" class="lucide-spin"></i>';
            try {
                const feedTitle = lastPreviewData?.feed_title || '';
                const category = categorySelect.value;
                const res = await apiFetch(`/api/sources/?url=${encodeURIComponent(url)}&title=${encodeURIComponent(feedTitle)}&category=${category}`, { method: 'POST' });
                const data = await readApiResponse(res);
                if (!res.ok) throw new Error(data.detail || '添加失败');

                alert('✅ 订阅源添加成功！');
                urlInput.value = '';
                confirmAddBtn.disabled = true;
                document.getElementById('preview-container').classList.add('hidden');
                lastPreviewData = null;
            } catch (e) {
                alert('添加失败: ' + e.message);
            } finally {
                confirmAddBtn.innerHTML = '<i data-lucide="plus"></i>';
                lucide.createIcons();
            }
        });
    }

    // 我的订阅 - 加载列表
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
                        <button class="btn-action btn-preview-list-sub" data-url="${f.url}" title="展开预览最新内容"><i data-lucide="eye"></i></button>
                        <button class="btn-action btn-delete-sub" title="删除订阅"><i data-lucide="trash-2"></i></button>
                    </div>
                </div>
                <div id="list-preview-${f.id}" class="preview-area hidden" style="margin-top: -8px; margin-bottom: 12px; background: rgba(0,0,0,0.2); border-radius: 0 0 12px 12px;"></div>
            `;
            }).join('');
            lucide.createIcons();
        } catch (e) {
            container.innerHTML = '<div class="loading-trigger">加载失败</div>';
        }
    };

    // 切到"我的订阅"标签时加载
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.tab === 'tab-list') loadSubsList();
        });
    });

    // 删除订阅（事件委托）
    document.addEventListener('click', async (e) => {
        const delBtn = e.target.closest('.btn-delete-sub');
        if (!delBtn) return;
        const card = delBtn.closest('.sub-item-card');
        const id = card.dataset.id;
        if (!confirm('确认删除此订阅源？')) return;

        try {
            const res = await apiFetch(`/api/sources/${id}`, { method: 'DELETE' });
            if (res.ok) {
                card.remove();
                document.getElementById(`list-preview-${id}`)?.remove();
            }
        } catch (e) {
            alert('删除失败');
        }
    });

    // 列表内的独立预览事件委托
    document.addEventListener('click', async (e) => {
        const previewBtn = e.target.closest('.btn-preview-list-sub');
        if (!previewBtn) return;

        const card = previewBtn.closest('.sub-item-card');
        const id = card.dataset.id;
        const url = previewBtn.dataset.url;
        const previewBox = document.getElementById(`list-preview-${id}`);

        // 折叠逻辑
        if (!previewBox.classList.contains('hidden')) {
            previewBox.classList.add('hidden');
            previewBox.innerHTML = '';
            previewBtn.innerHTML = '<i data-lucide="eye"></i>';
            lucide.createIcons();
            return;
        }

        // 展开与网络探测逻辑
        previewBtn.innerHTML = '<i data-lucide="loader-circle" class="lucide-spin"></i>';
        lucide.createIcons();
        try {
            const res = await apiFetch(`/api/sources/preview?url=${encodeURIComponent(url)}`, { method: 'POST' });
            const data = await readApiResponse(res);
            if (!res.ok) throw new Error(data.detail || '预览探测失败');

            previewBox.classList.remove('hidden');
            previewBox.innerHTML = `
                <div class="preview-list"></div>
            `;
            renderPreview(previewBox.querySelector('.preview-list'), data.articles);
        } catch (err) {
            alert('预览探测失败: ' + err.message);
        } finally {
            previewBtn.innerHTML = '<i data-lucide="chevron-up"></i>';
            lucide.createIcons();
        }
    });

    // --- 文章加载与渲染 ---
    const feedStream = document.getElementById('feed-stream');
    const loadingTrigger = document.getElementById('loading');
    let offset = 0;
    const limit = 20;
    let isLoading = false;
    let lastDateStr = "";

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
        1: { name: '\u65f6\u653f\u5546\u4e1a', icon: 'briefcase' }, // 时政商业
        2: { name: '\u79d1\u6280\u5f00\u53d1', icon: 'cpu' },       // 科技开发
        3: { name: '\u6e38\u620f\u6587\u5a31', icon: 'gamepad-2' }, // 游戏文娱
        4: { name: '\u751f\u6d3b\u6d89\u730e', icon: 'coffee' },    // 生活涉猎
        5: { name: '\u7efc\u5408\u4e0e\u5176\u4ed6', icon: 'layers' } // 综合与其他
    };

    const renderArticle = (article) => {
        let rawDateStr = article.published_at || article.published || article.created_at;
        // Convert strict SQL strings (e.g. "2026-03-23 10:45:27") to UTC ISO8601 so browsers parse as local time
        if (rawDateStr && typeof rawDateStr === 'string' && !rawDateStr.includes('Z') && !rawDateStr.match(/[+-]\d{2}:?\d{2}$/)) {
            rawDateStr = String(rawDateStr).replace(" ", "T") + "Z";
        }

        const pubDate = new Date(rawDateStr);
        const dateStr = formatDate(pubDate);
        let html = "";

        // 插入日期分隔线
        if (dateStr !== lastDateStr) {
            html += `<div class="date-divider">${dateStr}</div>`;
            lastDateStr = dateStr;
        }

        const score = Math.round(article.ai_score || 0);
        const scoreClass = getScoreClass(score);
        const excerpt = article.description
            ? (article.description.length > 120 ? article.description.substring(0, 120) + '...' : article.description)
            : '无内容预览';

        const categoryData = CATEGORY_MAP[article.category] || { name: '\u7efc\u5408', icon: 'layers' }; // 综合

        const escapeAttr = (str) => {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
        };
        const escapedTitle = escapeAttr(article.title);
        const escapedDesc = escapeAttr(article.description || '无内容预览');

        html += `
            <article class="article-card" data-id="${article.id}">
                <div class="card-header-inline">
                    <h2 class="article-title" title="${escapedTitle}">${article.title}</h2>
                    <div class="meta-right">
                        <span class="pub-time">${formatTime(pubDate)}</span>
                        <span class="ai-score ${scoreClass}">${score}</span>
                        <span class="source-tag" title="${categoryData.name}"><i data-lucide="${categoryData.icon}"></i></span>
                        <div class="action-menu-container">
                            <button class="btn-more-options" title="更多选项"><i data-lucide="more-horizontal"></i></button>
                            <div class="action-dropdown">
                                <a href="${article.link}" target="_blank" rel="noopener" class="dropdown-item" title="查看原文"><i data-lucide="external-link"></i></a>
                                <button class="dropdown-item btn-not-interest ${article.feedback === -1 ? 'active' : ''}" data-type="-1" title="不感兴趣"><i data-lucide="thumbs-down"></i></button>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="excerpt-with-like">
                    <p class="article-excerpt" title="${escapedDesc}">${excerpt}</p>
                    <button class="btn-action btn-interest inline-like ${article.feedback === 1 ? 'active' : ''}" data-type="1" title="感兴趣"><i data-lucide="thumbs-up"></i></button>
                </div>
            </article>
        `;
        return html;
    };

    const loadArticles = async (reset = false) => {
        if (isLoading) return;
        isLoading = true;

        if (reset) {
            offset = 0;
            lastDateStr = "";
            const indicator = document.getElementById('pull-to-refresh');
            const loader = document.getElementById('loading');
            feedStream.innerHTML = '';
            if (indicator) feedStream.appendChild(indicator);
            if (loader) feedStream.appendChild(loader);
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
                emptyMsg.textContent = '暂无新内容，点击 Logo 刷新';
                feedStream.insertBefore(emptyMsg, loader);
            }
        } catch (e) {
            console.error("Failed to load articles:", e);
        } finally {
            isLoading = false;
        }
    };

    // 全文检索
    const searchArticles = async (query) => {
        lastDateStr = "";
        const indicator = document.getElementById('pull-to-refresh');
        const loader = document.getElementById('loading');
        feedStream.innerHTML = '';
        if (indicator) feedStream.appendChild(indicator);
        if (loader) feedStream.appendChild(loader);

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
                emptyMsg.textContent = `未找到包含「${query}」的文章`;
                feedStream.insertBefore(emptyMsg, loader);
            }
        } catch (e) {
            console.error("Search failed:", e);
        }
    };

    // 初始加载
    loadArticles(true);

    // --- 关注/不关注 交互 & 更多菜单 ---
    document.addEventListener('click', async (e) => {
        // Toggle Dropdown menu
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
            // Optional: Close dropdown automatically when feedback is clicked
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

    // --- Logo 点击刷新 ---
    document.getElementById('logo-refresh').onclick = async () => {
        await refreshFeeds();
    };

    // --- 搜索展开/收起动画 ---
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
            searchInput.blur();
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

    // ESC 关闭搜索
    searchInput.addEventListener('keydown', async (e) => {
        if (e.key === 'Escape') {
            toggleSearch(true);
            return;
        }
        if (e.key === 'Enter') {
            const query = searchInput.value.trim();
            if (!query) { loadArticles(true); return; }
            // 调用 FTS5 全文检索 API
            await searchArticles(query);
        }
    });

    // 点击页面其他地方收起搜索
    document.addEventListener('click', (e) => {
        if (searchOpen && !searchBox.contains(e.target) && e.target !== searchToggle) {
            toggleSearch(true);
        }
    });

    // --- 无限滚动 ---
    const observer = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && !isLoading) {
            loadArticles();
        }
    }, { threshold: 0.1 });
    observer.observe(loadingTrigger);

    // --- 刷新逻辑 ---
    const refreshFeeds = async () => {
        const logo = document.getElementById('logo-refresh');
        const indicator = document.getElementById('pull-to-refresh');

        logo.style.opacity = '0.5';
        indicator.classList.add('active');
        indicator.querySelector('span').textContent = '加载最新内容...';

        try {
            await loadArticles(true);
        } catch (e) {
            alert("加载失败，请检查网络或配置");
        } finally {
            logo.style.opacity = '1';
            indicator.classList.remove('active');
            setTimeout(() => {
                indicator.querySelector('span').textContent = '下拉刷新...';
            }, 300);
        }
    };

    // --- 下拉刷新触摸逻辑 ---
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

    // --- 回到顶部 ---
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

    // --- AI 画像管理 ---
    const profileModal = document.getElementById('modal-profile');
    const tagsList = document.getElementById('tags-list');
    const promptEditor = document.getElementById('system-prompt-editor');
    const saveProfileBtn = document.getElementById('save-profile');

    // 加载画像数据
    const loadProfile = async () => {
        try {
            const res = await apiFetch('/api/profile/');
            const data = await res.json();

            // 渲染 Tags
            const tags = data.active_tags ? data.active_tags.split(',').map(t => t.trim()).filter(Boolean) : [];
            renderTags(tags);

            // 填充 Prompt
            if (promptEditor) {
                promptEditor.value = data.base_prompt || '';
            }
        } catch (e) {
            console.error('加载画像失败:', e);
        }
    };

    const renderTags = (tags) => {
        if (!tagsList) return;
        tagsList.innerHTML = tags.map(t =>
            `<span class="tag">${t} <small class="tag-remove">&times;</small></span>`
        ).join('') + '<input type="text" placeholder="在新标签页输入..." class="tag-input-inline" id="tag-new-input">';

        // 删除标签
        tagsList.querySelectorAll('.tag-remove').forEach(btn => {
            btn.addEventListener('click', () => btn.closest('.tag').remove());
        });

        // 回车添加标签
        const input = document.getElementById('tag-new-input');
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const val = input.value.trim();
                    if (!val) return;
                    const span = document.createElement('span');
                    span.className = 'tag';
                    span.innerHTML = `${val} <small class="tag-remove">&times;</small>`;
                    span.querySelector('.tag-remove').addEventListener('click', () => span.remove());
                    tagsList.insertBefore(span, input);
                    input.value = '';
                }
            });
        }
    };

    // 打开画像弹窗时加载数据
    const profileBtn = document.getElementById('nav-profile');
    if (profileBtn) {
        const origClick = profileBtn.onclick;
        profileBtn.onclick = () => {
            if (origClick) origClick();
            loadProfile();
        };
    }

    // 保存 Tag（base_prompt 仅允许 AI 自动生成）
    if (saveProfileBtn) {
        saveProfileBtn.addEventListener('click', async () => {
            const tags = Array.from(tagsList.querySelectorAll('.tag'))
                .map(el => el.textContent.replace('×', '').trim())
                .filter(Boolean);
            let currentTags = [];
            try {
                const currentRes = await apiFetch('/api/profile/');
                const currentData = await currentRes.json();
                currentTags = currentData.active_tags ? currentData.active_tags.split(',').map(t => t.trim()).filter(Boolean) : [];
            } catch (e) {
                alert('读取当前标签失败: ' + e.message);
                return;
            }

            saveProfileBtn.innerHTML = '<i data-lucide="loader-circle" class="lucide-spin"></i>';
            lucide.createIcons();
            try {
                const tagsToAdd = tags.filter(tag => !currentTags.includes(tag));
                const tagsToDelete = currentTags.filter(tag => !tags.includes(tag));

                for (const tag of tagsToAdd) {
                    const res = await apiFetch('/api/profile/tags', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ tag }),
                    });
                    const data = await readApiResponse(res);
                    if (!res.ok) throw new Error(data.detail || data.message || '新增标签失败');
                }

                for (const tag of tagsToDelete) {
                    const res = await apiFetch(`/api/profile/tags?tag=${encodeURIComponent(tag)}`, {
                        method: 'DELETE',
                    });
                    const data = await readApiResponse(res);
                    if (!res.ok) throw new Error(data.detail || data.message || '删除标签失败');
                }

                alert('✅ 标签已保存');
                await loadProfile();
            } catch (e) {
                alert('保存失败: ' + e.message);
            } finally {
                saveProfileBtn.innerHTML = '<i data-lucide="save"></i>';
                lucide.createIcons();
            }
        });
    }

    lucide.createIcons();
});
