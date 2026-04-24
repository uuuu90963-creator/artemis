# Artemis Agent - Docker 镜像
FROM python:3.11-slim

LABEL maintainer="Artemis Agent"
LABEL description="通用型 AI 助手框架"

# 设置环境
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建必要目录
RUN mkdir -p /root/.hermes/artemis/memories /root/.hermes/artemis/logs

# 默认运行入口
ENTRYPOINT ["python", "artemis.py"]
CMD ["--help"]
