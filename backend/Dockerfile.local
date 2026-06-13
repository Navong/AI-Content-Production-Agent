# ---- Backend: FastAPI + LangGraph agent ----
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# Dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000
# Honor $PORT (Railway/Cloud Run set it); default 8000 for compose/local.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
