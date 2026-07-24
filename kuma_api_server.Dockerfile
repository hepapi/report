# Uptime Kuma DB API sunucusu - sidecar image
#
# Build:
#   docker build -f kuma_api_server.Dockerfile -t kuma-db-api .
#
# Uptime Kuma container'i ile ayni docker-compose'a ekleyip onun veri
# volume'unu SALT-OKUNUR (:ro) mount edin. Ornek icin
# docker-compose.kuma-api.yml.example dosyasina bakin.
FROM python:3.12-slim

WORKDIR /srv

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY kuma_dbaccess.py kuma_api_server.py ./

ENV KUMA_DB_PATH=/app/data/kuma.db
EXPOSE 8090

CMD ["python3", "kuma_api_server.py"]
