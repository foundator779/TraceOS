FROM node:22-alpine AS web-builder
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    TRACEOS_DB_PATH=/tmp/traceos.db
WORKDIR /app
COPY backend/requirements-runtime.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=web-builder /src/frontend/out ./static
RUN useradd --create-home --uid 10001 traceos && chown -R traceos:traceos /app
USER traceos
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
