FROM python:3.12-slim-buster

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and the new Gunicorn config
COPY main.py .
COPY gunicorn.conf.py .

# Command to run the application using our Gunicorn config file.
# The config file handles binding, workers, and starting the bot.
CMD ["gunicorn", "-c", "gunicorn.conf.py", "main:app"]
