import os
import aiosqlite
import yaml
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import event

from app.services.search_index import build_search_text

# 获取项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "feedlite.db")
SCHEMA_PATH = os.path.join(DATA_DIR, "schemas.sql")

# 确保 data 目录存在
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 异步数据库 URL (使用 aiosqlite)
SQLALCHEMY_DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

# 创建异步引擎
engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# 开启 WAL 模式 (异步方式在连接时设置)
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

# 异步会话工厂
AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()

from datetime import datetime, timezone
import bcrypt


async def _migrate_user_profiles(db):
    """兼容历史数据库：创建 user_profiles，并把 users 中的画像字段迁移过去。"""
    cursor = await db.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in await cursor.fetchall()}

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            base_prompt TEXT DEFAULT '',
            active_tags TEXT DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )

    cursor = await db.execute("SELECT COUNT(*) FROM user_profiles")
    profile_count = (await cursor.fetchone())[0]

    if {"base_prompt", "active_tags"}.issubset(user_columns):
        rows = await db.execute("SELECT id, base_prompt, active_tags FROM users")
        user_rows = await rows.fetchall()
        payload = [
            (
                row[0],
                row[1] or "",
                row[2] or "",
                datetime.now(timezone.utc).isoformat(),
            )
            for row in user_rows
            if row[1] or row[2] or profile_count == 0
        ]
        if payload:
            await db.executemany(
                """
                INSERT INTO user_profiles (user_id, base_prompt, active_tags, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    base_prompt = excluded.base_prompt,
                    active_tags = excluded.active_tags,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
            await db.commit()
            print(f"✅ Migrated {len(payload)} user profile rows into user_profiles")


async def _cleanup_users_table(db):
    """清理 users 表中的遗留画像字段，保留纯账户结构。"""
    cursor = await db.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in await cursor.fetchall()}
    legacy_columns = {"base_prompt", "active_tags"}

    if not legacy_columns.intersection(user_columns):
        return

    await db.execute("PRAGMA foreign_keys=OFF")
    await db.execute(
        """
        CREATE TABLE users_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """
    )
    await db.execute(
        """
        INSERT INTO users_new (id, username, password_hash, created_at)
        SELECT id, username, password_hash, created_at
        FROM users
        """
    )
    await db.execute("DROP TABLE users")
    await db.execute("ALTER TABLE users_new RENAME TO users")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.commit()
    print("✅ Cleaned legacy profile columns from users table")


def _load_runtime_defaults() -> dict:
    config_path = os.path.join(BASE_DIR, "config.yml")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


async def _migrate_article_translation_columns(db):
    """兼容历史数据库：补齐翻译相关字段。"""
    cursor = await db.execute("PRAGMA table_info(articles)")
    article_columns = {row[1] for row in await cursor.fetchall()}
    expected_columns = {
        "translated_title": "ALTER TABLE articles ADD COLUMN translated_title TEXT",
        "translated_description": "ALTER TABLE articles ADD COLUMN translated_description TEXT",
        "translation_language": "ALTER TABLE articles ADD COLUMN translation_language TEXT",
        "translation_status": "ALTER TABLE articles ADD COLUMN translation_status TEXT DEFAULT 'pending'",
        "translation_updated_at": "ALTER TABLE articles ADD COLUMN translation_updated_at TEXT",
    }

    for column, ddl in expected_columns.items():
        if column not in article_columns:
            await db.execute(ddl)
            await db.commit()
            print(f"✅ Added missing column: articles.{column}")


async def _sync_app_config_defaults(db):
    """启动时将 config.yml 中的运行时默认值同步到 app_config。"""
    cfg = _load_runtime_defaults()
    translation_cfg = cfg.get("translation", {})
    defaults = {
        "translation.enabled": str(bool(translation_cfg.get("enabled", True))).lower(),
        "translation.target_language": str(translation_cfg.get("target_language", "zh-CN") or "zh-CN"),
        "translation.translate_title": str(bool(translation_cfg.get("translate_title", True))).lower(),
        "translation.translate_description": str(bool(translation_cfg.get("translate_description", True))).lower(),
    }
    now = datetime.now(timezone.utc).isoformat()
    await db.executemany(
        """
        INSERT INTO app_config (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        [(key, value, now) for key, value in defaults.items()],
    )
    await db.commit()
    print(f"✅ Synced {len(defaults)} runtime defaults into app_config")


async def _rebuild_search_index(db):
    """兼容历史数据库：补齐 search_text，并重建 FTS5 索引与触发器。"""
    cursor = await db.execute("PRAGMA table_info(articles)")
    article_columns = {row[1] for row in await cursor.fetchall()}

    if "search_text" not in article_columns:
        await db.execute("ALTER TABLE articles ADD COLUMN search_text TEXT DEFAULT ''")
        await db.commit()
        print("✅ Added missing column: articles.search_text")

    await db.execute("DROP TRIGGER IF EXISTS articles_ai")
    await db.execute("DROP TRIGGER IF EXISTS articles_au")
    await db.execute("DROP TRIGGER IF EXISTS articles_ad")
    await db.execute("DROP TABLE IF EXISTS articles_fts")
    await db.commit()

    await db.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
            search_text,
            content='articles',
            content_rowid='id',
            tokenize='unicode61'
        )
        """
    )
    rows = await db.execute("SELECT id, title, description, content FROM articles")
    article_rows = await rows.fetchall()
    if article_rows:
        payload = [
            (
                build_search_text(
                    title=row[1] or "",
                    description=row[2] or "",
                    content=row[3] or "",
                ),
                row[0],
            )
            for row in article_rows
        ]
        await db.executemany("UPDATE articles SET search_text = ? WHERE id = ?", payload)

    await db.execute("INSERT INTO articles_fts(articles_fts) VALUES ('rebuild')")
    await db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
          INSERT INTO articles_fts(rowid, search_text) VALUES (new.id, new.search_text);
        END;
        """
    )
    await db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
          INSERT INTO articles_fts(articles_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
          INSERT INTO articles_fts(rowid, search_text) VALUES (new.id, new.search_text);
        END;
        """
    )
    await db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
          INSERT INTO articles_fts(articles_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
        END;
        """
    )
    await db.commit()
    print("✅ Rebuilt FTS5 search index with search_text backfill")

# 初始化数据库结构 (冷启动调用)
async def init_db():
    if not os.path.exists(SCHEMA_PATH):
        print(f"Warning: Schema file not found at {SCHEMA_PATH}")
        return

    # 1. 执行 SQL 脚本初始化表结构 (if not exists)
    async with aiosqlite.connect(DB_PATH) as db:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        await db.executescript(schema_sql)
        await db.commit()

        # 兼容历史数据库：为 articles 表补充反馈更新时间字段，便于按“最近一周反馈”生成画像。
        cursor = await db.execute("PRAGMA table_info(articles)")
        article_columns = {row[1] for row in await cursor.fetchall()}
        if "feedback_updated_at" not in article_columns:
            await db.execute("ALTER TABLE articles ADD COLUMN feedback_updated_at TEXT")
            await db.commit()
            print("✅ Added missing column: articles.feedback_updated_at")

        await _migrate_user_profiles(db)
        await _cleanup_users_table(db)
        await _migrate_article_translation_columns(db)
        await _sync_app_config_defaults(db)
        await _rebuild_search_index(db)

        # 2. 启动时将 .env 中的 AI 配置按角色写入数据库，确保重启后数据库与当前环境一致。
        models_to_upsert = []
        now = datetime.now(timezone.utc).isoformat()

        # Scorer 配置
        if os.getenv("SCORER_API_KEY"):
            provider = os.getenv("SCORER_PROVIDER", "openai").lower()
            if provider == "google":
                provider = "gemini"
            models_to_upsert.append((
                "scorer",
                provider,
                os.getenv("SCORER_MODEL", "gpt-4o-mini"),
                os.getenv("SCORER_API_BASE", "https://api.openai.com/v1"),
                os.getenv("SCORER_API_KEY"),
                now
            ))

        # Profiler 配置
        if os.getenv("PROFILER_API_KEY"):
            provider = os.getenv("PROFILER_PROVIDER", "openai").lower()
            if provider == "google":
                provider = "gemini"
            models_to_upsert.append((
                "profiler",
                provider,
                os.getenv("PROFILER_MODEL", "gpt-4o-mini"),
                os.getenv("PROFILER_API_BASE", "https://api.openai.com/v1"),
                os.getenv("PROFILER_API_KEY"),
                now
            ))

        if models_to_upsert:
            await db.executemany(
                """
                INSERT INTO ai_models (role, provider, model_name, api_base, api_key, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(role) DO UPDATE SET
                    provider = excluded.provider,
                    model_name = excluded.model_name,
                    api_base = excluded.api_base,
                    api_key = excluded.api_key,
                    updated_at = excluded.updated_at
                """,
                models_to_upsert
            )
            print(f"✅ Upserted {len(models_to_upsert)} AI models from ENV.")

        # 3. 注入默认管理员 (如果表为空)
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        user_count = (await cursor.fetchone())[0]
        if user_count == 0:
            username = os.getenv("ADMIN_USERNAME", "admin")
            password = os.getenv("ADMIN_PASSWORD", "admin123")
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, hashed, now)
            )
            print(f"✅ Seeded default admin user: {username}")
        
        await db.commit()

    print("Database structures and seed data initialized.")

# 获取数据库会话的依赖项
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
