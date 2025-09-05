FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir --upgrade yt-dlp

# Copy application code
COPY . .

# Expose the port that the application will run on
EXPOSE 8080

# Set Google Cloud credentials environment variable
ENV GOOGLE_APPLICATION_CREDENTIALS="/app/yt-dlp-worker-key.json"

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
