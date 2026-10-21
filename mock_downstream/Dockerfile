FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mock_downstream/ ./mock_downstream/

RUN adduser --disabled-password --gecos "" appuser
USER appuser

EXPOSE 9000

CMD ["uvicorn", "mock_downstream.main:app", "--host", "0.0.0.0", "--port", "9000"]
