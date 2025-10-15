# Use Python 3.11 for compatibility with eventlet
FROM python:3.11.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 5000

# Use environment variable for port
ENV PORT=5000

# Run gunicorn with gevent worker
CMD ["gunicorn", "--config", "gunicorn_config.py", "app:socketio"]

