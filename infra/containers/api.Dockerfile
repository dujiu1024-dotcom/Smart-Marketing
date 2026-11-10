FROM python:3.13-slim
WORKDIR /app
COPY apps/api/pyproject.toml ./pyproject.toml
COPY apps/api/src ./src
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["uvicorn", "store_operator.main:app", "--host", "0.0.0.0", "--port", "8000"]
