FROM python:3.11-slim

# Enforce clean standard output logging patterns without container caching delay
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Install system dependencies if required for compiling certain libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Optimize Docker layer caching by separating requirements installation
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy the rest of the application files into the working directory
COPY . .

# Pin a safe non-root security container path
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

# Expose network ports dynamically matching environmental runtime bindings
EXPOSE 8000

# Spin up production server with optimized worker processes (disable reload)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 2"]