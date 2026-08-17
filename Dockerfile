# Single image: FastAPI serves both the WebSocket simulation stream and the
# static frontend. The frontend needs no build step (plain ES modules), which
# keeps the demo a one-command start and the image small.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

EXPOSE 8000

# Render injects $PORT; local/Fly keep 8000.
ENV PORT=8000

HEALTHCHECK --interval=20s --timeout=3s --start-period=5s \
    CMD python -c "import os,urllib.request,sys; p=os.environ.get('PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/api/health').status==200 else 1)"

WORKDIR /app/backend
CMD uvicorn app.server:app --host 0.0.0.0 --port ${PORT}
