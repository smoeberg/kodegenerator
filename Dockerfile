FROM python:3.11-slim

RUN useradd -u 1000 -ms /bin/bash dor
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R dor:dor /app
USER dor

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
