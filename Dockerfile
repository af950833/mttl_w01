FROM python:3.12-slim

LABEL org.opencontainers.image.title="MTTL-W01 Local Server" \
      org.opencontainers.image.description="Local MEF, TLS MQTT, QMS, dashboard, and Home Assistant bridge for LG U+ MTTL-W01" \
      org.opencontainers.image.source="https://github.com/af950833/mttl_w01"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MTTL_DATA_DIR=/data \
    MTTL_CERT_DIR=/certs \
    MTTL_WEB_BIND=0.0.0.0 \
    MTTL_WEB_PORT=18833

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY server /app/server
COPY web /app/web
COPY work/ap/mttl_cert_server.py work/ap/mttl_mef_proxy.py /app/legacy/
COPY work/firmware/1.0.66/comMTTL-W01_1.0.66.fwr /app/firmware/comMTTL-W01_1.0.66.fwr

RUN useradd --system --uid 10001 --home /app mttl \
    && mkdir -p /data/devices /data/state /data/energy /data/logs \
    && chown -R mttl:mttl /app /data

USER mttl
EXPOSE 18080 18443 18832 18833 19443
VOLUME ["/data", "/certs"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18833/api/health', timeout=3).read()"]
ENTRYPOINT ["python", "-m", "server"]
