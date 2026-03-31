-- 1. 用户与画像表
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id INTEGER PRIMARY KEY,
    base_prompt TEXT DEFAULT '',
    active_tags TEXT DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- 2. 订阅源管理表
CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    category INTEGER NOT NULL DEFAULT 5,
    error_count INTEGER DEFAULT 0,
    next_retry_time TEXT,
    last_success_time TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- 3. 文章数据主表
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    link TEXT UNIQUE NOT NULL,
    description TEXT,
    content TEXT,
    search_text TEXT DEFAULT '',
    translated_title TEXT,
    translated_description TEXT,
    translation_language TEXT,
    translation_status TEXT DEFAULT 'pending',
    translation_updated_at TEXT,
    published TEXT NOT NULL,
    ai_score INTEGER DEFAULT 0,
    feedback INTEGER DEFAULT 0,
    feedback_updated_at TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    FOREIGN KEY (feed_id) REFERENCES feeds (id)
);

-- 索引：提高常用检索性能
CREATE INDEX IF NOT EXISTS idx_articles_status_published_id ON articles (status, published DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_feeds_status_next_retry ON feeds (status, next_retry_time);

-- 4. 常规系统配置表 (存储界面或爬虫维度的通用级配置，覆盖 AI 凭证的功能已经移交)
CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- 5. 全文检索虚拟表 (FTS5)
-- 仅包含用于搜索的文本字段，rowid 将映射到 articles.id
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    search_text,
    content='articles',
    content_rowid='id',
    tokenize='unicode61'
);

-- 6. 触发器：同步 FTS 索引
-- 插入新文章时自动更新 FTS
CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
  INSERT INTO articles_fts(rowid, search_text) VALUES (new.id, new.search_text);
END;

-- 更新文章时同步索引
CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
  INSERT INTO articles_fts(rowid, search_text) VALUES (new.id, new.search_text);
END;

-- 删除文章时清理索引
CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
END;

-- 7. AI 模型角色配置表
CREATE TABLE IF NOT EXISTS ai_models (
    role TEXT PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'openai',
    model_name TEXT NOT NULL,
    api_base TEXT NOT NULL,
    api_key TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- 8. 用户画像历史快照
CREATE TABLE IF NOT EXISTS profile_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    profile_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE INDEX IF NOT EXISTS idx_profile_history_user_created ON profile_history (user_id, created_at DESC, id DESC);
