FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "gunicorn -k uvicorn.workers.UvicornWorker app.main:app -b 0.0.0.0:${PORT:-8080} --workers=4 --log-level=info"]
