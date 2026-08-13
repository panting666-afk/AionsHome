FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

RUN sed -i "s@deb.debian.org@mirrors.aliyun.com@g; s@security.debian.org@mirrors.aliyun.com@g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libglib2.0-0 libgl1 libportaudio2 nodejs npm ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY deploy/pyncm-1.8.1-py3-none-any.whl /tmp/pyncm-1.8.1-py3-none-any.whl
RUN pip install /tmp/pyncm-1.8.1-py3-none-any.whl && rm /tmp/pyncm-1.8.1-py3-none-any.whl

COPY deploy/requirements-linux.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY aion-chat /app/aion-chat
COPY public /app/public
COPY AionPet /app/AionPet
COPY Connor-Codex /app/Connor-Codex

WORKDIR /app/aion-chat
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
