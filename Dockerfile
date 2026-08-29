FROM python:3.10-slim-bookworm

WORKDIR /app

# Install polyglot execution runtimes (C/C++, Node.js, Go, Java)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    nodejs \
    golang-go \
    default-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]