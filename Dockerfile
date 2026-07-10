FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONPATH=/app/src
EXPOSE 8765
# Ollama must run on host or separate container — see README
CMD ["uvicorn", "llm_council.main:app", "--host", "0.0.0.0", "--port", "8765"]
