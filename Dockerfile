FROM python:3.12-slim

WORKDIR /app

# Dependências de sistema mínimas para psycopg2
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV PORT=5000
EXPOSE 5000

# Roda com gunicorn (produção), apontando para app.py -> app = Flask(...)
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} app:app"]
