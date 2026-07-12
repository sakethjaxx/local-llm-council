FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8765
# Bind localhost by default. Running through main.py (not `uvicorn main:app`)
# routes startup through the guard that REQUIRES COUNCIL_API_KEY before it will
# bind a non-localhost interface. To expose the container, set both
# COUNCIL_HOST=0.0.0.0 and COUNCIL_API_KEY=<secret>.
ENV COUNCIL_HOST=127.0.0.1
ENV COUNCIL_PORT=8765
# Ollama must run on host or separate container — see README
CMD ["python", "main.py"]
