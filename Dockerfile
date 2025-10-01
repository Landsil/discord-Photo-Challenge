# Use a slim Python base image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy requirement files and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Run the Flask app using Gunicorn, binding to the port provided by the environment variable ($PORT)
# Gunicorn will start the Flask 'app' defined in 'main.py', which starts the Discord bot in a thread.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:app"]
