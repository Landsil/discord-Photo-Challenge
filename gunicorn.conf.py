import os
from main import start_bot_thread

# Get the port from the environment variable provided by Cloud Run
port = os.environ.get("PORT", "8080")

# Gunicorn configuration settings
# See: https://docs.gunicorn.org/en/stable/settings.html
bind = f"0.0.0.0:{port}"
workers = 1
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 300

def when_ready(server):
    """
    Gunicorn server hook called when the master process is ready.
    This is the ideal place to start our background Discord bot thread.
    """
    server.log.info("Gunicorn master process is ready. Starting Discord Bot.")
    start_bot_thread()
