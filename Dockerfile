FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD gunicorn -w 1 -k gevent --timeout 240 --bind 0.0.0.0:${PORT} main:app
