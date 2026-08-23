# Use lightweight Python 3.12 image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Prevent Python from writing bytecode and buffer stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose server port
EXPOSE 8000

# Start FastAPI application with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
