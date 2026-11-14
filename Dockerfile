FROM python:3.14.4-slim AS matcher
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY src/reconciliation/ /app/reconciliation/
ENV PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
ENTRYPOINT ["python", "-m", "reconciliation.matcher_entry"]
