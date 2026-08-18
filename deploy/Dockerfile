# 基于 playwright 官方 Python 镜像(内含 Chromium)
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# 装 ffmpeg + CJK 字体
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖,利用 Docker 缓存
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝应用代码
COPY backend/ .

# 运行时目录(也可挂载 volume)
RUN mkdir -p storage/uploads storage/outputs
ENV WORKER_COUNT=2 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
