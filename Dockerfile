# Use a slim Python base image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy requirement files and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Cloud Run injects the PORT environment variable; 
# we don't need to listen on it, but the container must run indefinitely.
# We just use the standard Python Discord bot execution.
CMD ["python", "main.py"]
