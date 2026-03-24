import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# 主动加载 .env 环境变量（为本地无 Docker 开发兜底）
load_dotenv()

from app.database import engine, init_db
from app.services.scheduler import start_scheduler, stop_scheduler

from fastapi import Depends

# 路由
from app.routers import feeds, sources, profile, auth
from app.auth_deps import verify_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化数据库和调度器，关闭时释放资源"""
    # 冷启动：初始化数据库结构
    await init_db()
    print("✅ Database initialized.")

    # 启动定时抓取调度器
    start_scheduler()

    yield

    # 关闭：清理资源
    stop_scheduler()
    await engine.dispose()
    print("🛑 Engine disposed.")


app = FastAPI(
    title="Feedlite API",
    description="AI 驱动的轻量级个人 RSS 信息流阅读器",
    version="2.4",
    lifespan=lifespan,
)

# CORS 设置（开发阶段允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 注册 API 路由 ---
app.include_router(auth.router)
app.include_router(feeds.router, dependencies=[Depends(verify_token)])
app.include_router(sources.router, dependencies=[Depends(verify_token)])
app.include_router(profile.router, dependencies=[Depends(verify_token)])


# --- 健康检查端点 ---
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "2.4"}


# --- 挂载静态文件 ---
# 注意：必须放在路由注册之后，因为 mount("/") 会捕获所有未匹配的路径
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


# --- 启动服务器 ---
# 若需在生产环境手动管理服务，可注释掉下方代码块。
# 注意：定时抓取任务绑定在 FastAPI 的 lifespan 中，关闭 Web 服务会导致抓取任务也停止。
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
