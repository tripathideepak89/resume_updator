FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLASK_HOST=0.0.0.0 \
    PORT=5000 \
    DATA_DIR=/app/data \
    USERS_DIR=/app/data/users \
    PROFILE_DIR=/app/data/profiles \
    UPLOAD_DIR=/app/data/uploads \
    RUNS_DIR=/app/data/runs \
    OUTPUT_DIR=/app/data/generated \
    AUDIT_DIR=/app/data/audits \
    LOG_DIR=/app/data/logs

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN mkdir -p /app/data/users /app/data/profiles /app/data/uploads /app/data/runs /app/data/audits /app/data/generated /app/data/logs \
    && chown -R app:app /app

USER app

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/').status == 200 else 1)"

CMD ["python", "app.py"]
