# AI Job Scout —— 容器镜像
# 单进程 Flask 应用（内存态 + 后台扫描线程），务必单实例运行，不要开多 worker。
FROM python:3.12-slim

# 不写 .pyc、日志实时刷出（容器里看日志更顺）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

# 先装依赖：利用 Docker 层缓存，改代码时不必重装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷代码（templates 是前端页面）。个人数据 data/ 不进镜像，见 .dockerignore，
# 运行时用挂载卷提供，避免把简历/API key 打进镜像层。
COPY app.py .
COPY templates ./templates

# 个人数据目录（运行时挂载卷到这里）
VOLUME ["/app/data"]

EXPOSE 8080

# 云平台负载均衡用；未配置登录时也可访问
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/healthz').read()" || exit 1

CMD ["python", "app.py"]
