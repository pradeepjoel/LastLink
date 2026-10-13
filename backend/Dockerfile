FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PYTHONUNBUFFERED=1 LASTLINK_DB=/app/data/lastlink.sqlite LASTLINK_REGIONAL_DB=/app/data/zou-express.sqlite
EXPOSE 8000
CMD ["sh", "-c", "python -m app.import_gtfs --ensure && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
