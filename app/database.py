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

        # 2. 注入环境变量中的 AI 配置 (如果表为空)
        cursor = await db.execute("SELECT COUNT(*) FROM ai_models")
        count = (await cursor.fetchone())[0]
        if count == 0:
            models_to_insert = []
            now = datetime.now(timezone.utc).isoformat()
            
            # Scorer 配置
            if os.getenv("SCORER_API_KEY"):
                provider = os.getenv("SCORER_PROVIDER", "openai").lower()
                if provider == "google": provider = "gemini"
                models_to_insert.append((
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
                if provider == "google": provider = "gemini"
                models_to_insert.append((
                    "profiler",
                    provider,
                    os.getenv("PROFILER_MODEL", "gpt-4o-mini"),
                    os.getenv("PROFILER_API_BASE", "https://api.openai.com/v1"),
                    os.getenv("PROFILER_API_KEY"),
                    now
                ))

            if models_to_insert:
                await db.executemany(
                    "INSERT INTO ai_models (role, provider, model_name, api_base, api_key, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    models_to_insert
                )
                print(f"✅ Seeded {len(models_to_insert)} AI models from ENV.")

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
