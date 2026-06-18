FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt flask>=3.0

# Copy source
COPY . .

EXPOSE 5000

# Default: run the operator dashboard
CMD ["python", "webapp/app.py"]
