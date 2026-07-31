(function exposeFeedLiteSecurity(root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    }
    root.FeedLiteSecurity = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function buildFeedLiteSecurity() {
    'use strict';

    const safeExternalUrl = (value) => {
        if (typeof value !== 'string' || !/^[a-z][a-z0-9+.-]*:/i.test(value)) {
            return null;
        }

        try {
            const parsed = new URL(value);
            if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
                return null;
            }
            return parsed.href;
        } catch {
            return null;
        }
    };

    const appendTextElement = (documentRef, parent, tagName, className, value) => {
        const element = documentRef.createElement(tagName);
        if (className) element.className = className;
        element.textContent = value == null ? '' : String(value);
        parent.appendChild(element);
        return element;
    };

    const appendIcon = (documentRef, parent, iconName) => {
        const icon = documentRef.createElement('i');
        icon.setAttribute('data-lucide', iconName);
        parent.appendChild(icon);
        return icon;
    };

    const renderPreview = (container, items, documentRef = document) => {
        if (!container) return;
        container.replaceChildren();

        for (const item of Array.isArray(items) ? items : []) {
            const row = documentRef.createElement('div');
            row.className = 'preview-item';
            appendTextElement(documentRef, row, 'h5', '', item?.title || '');
            appendTextElement(documentRef, row, 'small', '', item?.published || '');
            container.appendChild(row);
        }
    };

    const renderSubscriptionList = (
        container,
        feeds,
        categoryMap,
        documentRef = document,
    ) => {
        if (!container) return;
        container.replaceChildren();

        for (const feed of Array.isArray(feeds) ? feeds : []) {
            const feedId = String(feed?.id ?? '');
            const feedUrl = String(feed?.url ?? '');
            const categoryIcon = categoryMap?.[feed?.category]?.icon || 'layers';

            const card = documentRef.createElement('div');
            card.className = 'sub-item-card';
            card.dataset.id = feedId;

            const summary = documentRef.createElement('div');
            summary.setAttribute('style', 'display:flex; align-items:center; gap:12px; flex:1; min-width:0;');
            const category = appendIcon(documentRef, summary, categoryIcon);
            category.setAttribute('style', 'color:var(--text-muted); flex-shrink:0;');

            const info = documentRef.createElement('div');
            info.className = 'sub-item-info';
            appendTextElement(documentRef, info, 'span', 'sub-name', feed?.title || feedUrl);
            appendTextElement(documentRef, info, 'span', 'sub-url', feedUrl);
            summary.appendChild(info);
            card.appendChild(summary);

            const actions = documentRef.createElement('div');
            actions.className = 'sub-item-actions';

            const previewButton = documentRef.createElement('button');
            previewButton.className = 'btn-action btn-preview-list-sub';
            previewButton.dataset.url = feedUrl;
            previewButton.setAttribute('title', 'Preview latest content');
            previewButton.setAttribute('aria-label', 'Preview latest content');
            appendIcon(documentRef, previewButton, 'eye');
            actions.appendChild(previewButton);

            const deleteButton = documentRef.createElement('button');
            deleteButton.className = 'btn-action btn-delete-sub';
            deleteButton.setAttribute('title', 'Delete subscription');
            deleteButton.setAttribute('aria-label', 'Delete subscription');
            appendIcon(documentRef, deleteButton, 'trash-2');
            actions.appendChild(deleteButton);

            card.appendChild(actions);
            container.appendChild(card);

            const previewArea = documentRef.createElement('div');
            previewArea.id = `list-preview-${feedId}`;
            previewArea.className = 'preview-area hidden';
            previewArea.setAttribute('style', 'margin-top:-8px; margin-bottom:12px; background:rgba(0,0,0,0.2); border-radius:0 0 12px 12px;');
            container.appendChild(previewArea);
        }
    };

    return {
        renderPreview,
        renderSubscriptionList,
        safeExternalUrl,
    };
}));
