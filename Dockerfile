FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .
EXPOSE 8080
CMD ["toolfence", "serve", "--host", "0.0.0.0", "--port", "8080", "--results-dir", "results"]
