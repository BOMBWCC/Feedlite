import os
import aiosqlite
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import event

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
