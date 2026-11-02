FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock && groupadd --gid 10001 flowsentry && useradd --uid 10001 --gid 10001 --no-create-home flowsentry
COPY --chown=flowsentry:flowsentry backend/ /app/
USER flowsentry
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
