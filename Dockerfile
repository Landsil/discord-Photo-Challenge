FROM python:3.12-slim-bookworm

WORKDIR /app

Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

Copy source code
COPY main.py .

Command to run the application using Gunicorn's gevent worker.
This single process will now handle both the web server (Flask) and the Discord bot (async loop).
CMD sh -c "gunicorn -w 1 -k gevent --timeout 300 --bind 0.0.0.0:${PORT} main:app"
