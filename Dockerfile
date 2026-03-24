# Dockerfile for FeedLite
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 启动 FastAPI Web 服务
# 若需改为手动管理（如仅通过脚本运行），可将下方 CMD 注释，改为 CMD ["tail", "-f", "/dev/null"] 使容器保持空转。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
