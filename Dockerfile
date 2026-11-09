# GHUS Compass, hosted (Render, 10-day team trial, 9 Nov 2026).
# One image: the web app and the ghus-backend agents it starts (Run now, Review
# admission, Data Feed) share this Python. Settings and secrets come from the
# host's environment; durable state lives on the disk at /var/data.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf \
    GHUS_DATA_DIR=/var/data

WORKDIR /app

# CPU-only torch first, so sentence-transformers does not pull the CUDA build.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.0

COPY requirements-deploy.txt .
RUN pip install -r requirements-deploy.txt

# The entity-resolution name model, baked in: Review admission never waits on
# (or fails because of) a download at decision time.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
ENV HF_HUB_OFFLINE=1

COPY . .

EXPOSE 10000
CMD ["python", "-m", "scripts.run_hosted_server"]
