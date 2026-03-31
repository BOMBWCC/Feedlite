"""
Search indexing helpers.
核心职责：生成稳定的预分词检索文本，并构建安全的 FTS 查询串。
"""

import html as html_module
import re

import jieba

_TAG_RE = re.compile(r"<.*?>", re.DOTALL)
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")


def _dedupe_preserve_order(tokens: list[str]) -> list[str]:
    seen = set()
    result = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result


def normalize_search_source(text: str) -> str:
    """清洗 HTML、统一小写，并保留适合分词的基础文本。"""
    if not text:
        return ""

    cleaned = _TAG_RE.sub(" ", text)
    cleaned = html_module.unescape(cleaned).lower()
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", cleaned)
    return " ".join(cleaned.split())


def tokenize_search_text(text: str) -> list[str]:
    """将文本拆分为适合 FTS 检索的 token。"""
    normalized = normalize_search_source(text)
    if not normalized:
        return []

    tokens: list[str] = []
    for chunk in _TOKEN_RE.findall(normalized):
        if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
            tokens.extend(token.strip() for token in jieba.cut_for_search(chunk) if token.strip())
        else:
            tokens.append(chunk)
    return _dedupe_preserve_order(tokens)


def build_search_text(title: str = "", description: str = "", content: str = "") -> str:
    """合并标题、简介、正文，生成预分词搜索字段。"""
    pieces = [title or "", description or "", content or ""]
    tokens: list[str] = []
    for piece in pieces:
        tokens.extend(tokenize_search_text(piece))
    return " ".join(_dedupe_preserve_order(tokens))


def build_search_query(query: str) -> str:
    """将用户输入转换为安全、稳定的 FTS 查询串。"""
    tokens = tokenize_search_text(query or "")
    return " ".join(_dedupe_preserve_order(tokens))


def build_search_excerpt(
    title: str = "",
    description: str = "",
    content: str = "",
    query: str = "",
    max_length: int = 140,
) -> str:
    """从标题、简介、正文中提取更适合展示的命中摘要。"""
    tokens = build_search_query(query).split()
    candidates = [
        normalize_search_source(description),
        normalize_search_source(content),
        normalize_search_source(title),
    ]

    for candidate in candidates:
        if not candidate:
            continue

        lowered = candidate.lower()
        matched_index = -1
        matched_token = ""
        for token in tokens:
            idx = lowered.find(token.lower())
            if idx != -1 and (matched_index == -1 or idx < matched_index):
                matched_index = idx
                matched_token = token

        if matched_index == -1:
            continue

        window = max_length // 2
        start = max(0, matched_index - window)
        end = min(len(candidate), matched_index + max(len(matched_token), window))
        snippet = candidate[start:end].strip()

        if start > 0:
            snippet = "..." + snippet
        if end < len(candidate):
            snippet = snippet + "..."

        return snippet

    fallback = normalize_search_source(description) or normalize_search_source(content) or normalize_search_source(title)
    if len(fallback) > max_length:
        return fallback[:max_length].rstrip() + "..."
    return fallback
