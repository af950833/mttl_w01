FROM python:3.12-slim

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
EXPOSE 18080 18443 18832 18833
VOLUME ["/data", "/certs"]
ENTRYPOINT ["python", "-m", "server"]
