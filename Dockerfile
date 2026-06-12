FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ART_GEN_HOST=0.0.0.0
ENV ART_GEN_PORT=80

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py README.md ./
COPY web ./web

EXPOSE 80

CMD ["python", "server.py"]
