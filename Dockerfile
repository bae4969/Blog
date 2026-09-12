ARG BASE_IMAGE=fastapi-py312:latest
FROM ${BASE_IMAGE}

ARG APP_VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="bae-blog" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

WORKDIR /app
ENV HOME=/tmp \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements-api.txt /tmp/blog-requirements.txt
RUN pip install --no-cache-dir -r /tmp/blog-requirements.txt \
    && rm /tmp/blog-requirements.txt

COPY --chown=1000:3000 app/ /app/app/
COPY --chown=1000:3000 public/ /app/public/
RUN mkdir -p /app/public/uploads && chown 1000:3000 /app/public/uploads

USER 1000:3000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
