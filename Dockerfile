FROM python:3.12-slim

# ffmpeg — ovozli xabarlarni (.oga/opus) Vosk uchun wav'ga o'girish
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY xalyava/ ./xalyava/
COPY bench/ ./bench/
COPY main.py botd.py run.py config.json ./

# Ma'lumotlar (DB, modellar, ovoz keshi) doimiy volume'da
ENV DATA_DIR=/data DB_PATH=/data/xalyava.db PYTHONUNBUFFERED=1
VOLUME ["/data"]

# Root bo'lmagan foydalanuvchi
RUN useradd -m -u 10001 xalyava && mkdir -p /data && chown -R xalyava /data /app
USER xalyava

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os,time,sys; p=os.environ.get('DATA_DIR','/data')+'/heartbeat'; \
sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p) < 300 else 1)"

CMD ["python", "run.py"]
