# Rapor Web UI - kuma-db-api'a HTTP ile baglanip PDF ureten Flask uygulamasi.
#
# Build:
#   docker build -f kuma_ui.Dockerfile -t kuma-ui .
#
# kuma-db-api ile ayni docker-compose'da, ayni network'te calisir; ona
# --api-url yerine KUMA_API_URL=http://kuma-db-api:8090 ortam degiskeniyle
# baglanir (docker network icinde servis adi = DNS adi).
FROM python:3.12-slim

WORKDIR /srv

COPY requirements-ui.txt .
RUN pip install --no-cache-dir -r requirements-ui.txt

COPY kuma_dbaccess.py kuma_report.py kuma_ui.py Pegasus_Logo.avif ./

ENV KUMA_UI_HOST=0.0.0.0
ENV KUMA_UI_PORT=5000
EXPOSE 5000

CMD ["python3", "kuma_ui.py"]
