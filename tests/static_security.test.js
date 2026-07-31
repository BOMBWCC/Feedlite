'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
    renderPreview,
    renderSubscriptionList,
    safeExternalUrl,
} = require('../static/security.js');


class FakeElement {
    constructor(tagName) {
        this.tagName = String(tagName).toLowerCase();
        this.children = [];
        this.dataset = {};
        this.attributes = {};
        this.className = '';
        this.id = '';
        this.style = {};
        this._textContent = '';
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    replaceChildren(...children) {
        this.children = children;
        this._textContent = '';
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }

    set textContent(value) {
        this._textContent = value == null ? '' : String(value);
    }

    get textContent() {
        return this._textContent + this.children.map(child => child.textContent).join('');
    }

    set innerHTML(_value) {
        throw new Error('remote data must not use innerHTML');
    }
}


const fakeDocument = {
    createElement(tagName) {
        return new FakeElement(tagName);
    },
};


const descendantTags = (element) => [
    element.tagName,
    ...element.children.flatMap(descendantTags),
];


test('preview renders hostile publisher titles as text only', () => {
    const container = new FakeElement('div');
    const payload = '<img src=x onerror="globalThis.__feedliteXss=1">';

    renderPreview(container, [{ title: payload, published: '2026-07-31' }], fakeDocument);

    assert.equal(container.textContent, `${payload}2026-07-31`);
    assert.equal(descendantTags(container).includes('img'), false);
    assert.equal(globalThis.__feedliteXss, undefined);
});


test('subscription rows render hostile titles and URLs as text only', () => {
    const container = new FakeElement('div');
    const title = '<svg onload="globalThis.__feedliteXss=1">';
    const url = 'https://example.com/" onmouseover="globalThis.__feedliteXss=1';

    renderSubscriptionList(
        container,
        [{ id: 7, title, url, category: 2 }],
        { 2: { icon: 'cpu' } },
        fakeDocument,
    );

    assert.match(container.textContent, /<svg onload=/);
    assert.match(container.textContent, /onmouseover=/);
    assert.equal(descendantTags(container).includes('svg'), false);
    assert.equal(globalThis.__feedliteXss, undefined);
});


test('external URL allowlist accepts only absolute HTTP URLs', () => {
    assert.equal(safeExternalUrl('https://example.com/article'), 'https://example.com/article');
    assert.equal(safeExternalUrl('http://example.com/article'), 'http://example.com/article');
    assert.equal(safeExternalUrl('javascript:alert(1)'), null);
    assert.equal(safeExternalUrl('data:text/html,<script>alert(1)</script>'), null);
    assert.equal(safeExternalUrl('/relative/article'), null);
    assert.equal(safeExternalUrl('https://example.com/" onmouseover="alert(1)'), 'https://example.com/%22%20onmouseover=%22alert(1)');
});
