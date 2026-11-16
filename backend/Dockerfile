FROM python:3.12.16-slim-bookworm
WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY manage.py .
COPY toptenpercent ./toptenpercent