# 基于 playwright 官方 Python 镜像(内含 Chromium)
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# 装 ffmpeg + CJK 字体 + CUDA 12 runtime libs
# TTS GPU 加速需要 libcublas.so.12 / libcudart.so.12 一套 cu12 runtime,
# 宿主驱动 13.x 不一定 backward-compat 提供,所以容器里直接装。
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-noto-cjk \
        wget gnupg ca-certificates \
    && wget -qO /tmp/cuda-keyring.deb \
         https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb \
    && dpkg -i /tmp/cuda-keyring.deb \
    && rm /tmp/cuda-keyring.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends cuda-libraries-12-1 \
    && rm -rf /var/lib/apt/lists/* \
    && ldconfig

ENV CUDA_HOME=/usr/local/cuda-12.1
ENV LD_LIBRARY_PATH=/usr/local/cuda-12.1/lib64:${LD_LIBRARY_PATH}

WORKDIR /app

# 装其余依赖(qwen-tts 会从 git 装,可能间接拉一个 cu130/cpu 版 torch —— 下面会锁回来)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 最后显式锁定 torch 为 cu121(2025-Q3 TTS GPU 加速用)。
# 宿主要求: NVIDIA 驱动 ≥ 530(torch cu121 向前兼容,包括 CUDA 13.1 驱动)。
# 这里用 --force-reinstall 保证 覆盖 qwen-tts 间接拉的 cu130/cpu 版。
# libcudart.so.13 找不到的错 就是因为 被间接拉成 cu130 + Docker 容器只有 cu12 runtime。
RUN pip install --no-cache-dir --force-reinstall --no-deps \
        torch \
        --index-url https://download.pytorch.org/whl/cu121

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
