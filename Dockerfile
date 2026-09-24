# AI Job Scout - container image
# Single-process Flask app (in-memory state + background scan threads): run exactly
# one instance, never multiple workers or replicas.
FROM python:3.12-slim

# No .pyc files; unbuffered logs so `docker logs` shows output immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

# Dependencies first, so Docker's layer cache skips reinstalling them on code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (templates = the web UI). Personal data in data/ is never baked
# into the image (see .dockerignore); it is mounted as a volume at runtime so
# resumes and API keys never end up in an image layer.
COPY app.py matching.py ./
COPY templates ./templates

# Personal data directory (mounted as a volume at runtime)
VOLUME ["/app/data"]

EXPOSE 8080

# For load balancers / `docker ps` health; /healthz needs no login
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/healthz').read()" || exit 1

CMD ["python", "app.py"]
