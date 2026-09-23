FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY services/analytics-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/analytics-service/app ./app
COPY services/analytics-service/tests ./tests
COPY infrastructure/athena/queries ./queries
RUN python -m unittest discover -s tests -v

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
