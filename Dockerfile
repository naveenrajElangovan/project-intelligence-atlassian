FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system atlassian && adduser --system --ingroup atlassian atlassian
COPY requirements.txt pyproject.toml ./
RUN python -m pip install --disable-pip-version-check -r requirements.txt
COPY app ./app
RUN python -m pip install --disable-pip-version-check --no-deps .
USER atlassian
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=2)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
