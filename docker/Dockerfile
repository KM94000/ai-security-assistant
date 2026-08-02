FROM python:3.12-slim

WORKDIR /app

# Copier les metadonnees + le code, puis installer (bon cache de couches)
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

EXPOSE 8000

# Le conteneur declare lui-meme son etat de sante
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "aisecassist.main:app", "--host", "0.0.0.0", "--port", "8000"]
