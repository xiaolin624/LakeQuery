FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ── 依赖层（充分利用 Docker 层缓存）──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── 业务代码层 ──
COPY lakequery/ lakequery/

EXPOSE 8000 7860

# ── 启动脚本：后台 uvicorn + 前台 Gradio ──
CMD ["sh", "-c", "uvicorn lakequery.main:app --host 0.0.0.0 --port 8000 & python -m lakequery.ui.app"]
