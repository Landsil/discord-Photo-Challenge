# Use a specific, stable version of the Python slim image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application source code
COPY . .

# Set the command to run Gunicorn with Flask
# It will listen on 0.0.0.0 and use the PORT environment variable provided by Cloud Run.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "2", "--timeout", "300", "main:app"]
