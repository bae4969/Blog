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

# 투자 계획 AI — codex CLI(2026-10-10). 빌드할 때 그때의 최신을 깐다(배포마다 따라 올라간다 — 실행 중 자체 업데이트는 안 한다).
# 실행 파일은 이미지(/opt/codex), 로그인(auth.json)은 볼륨(/data/codex — compose 가 blog_data/codex 를 붙인다)에 둔다.
RUN curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_HOME=/opt/codex CODEX_INSTALL_DIR=/usr/local/bin sh \
    && /usr/local/bin/codex --version
ENV CODEX_HOME=/data/codex

COPY --chown=1000:3000 app/ /app/app/
COPY --chown=1000:3000 public/ /app/public/
RUN mkdir -p /app/public/uploads && chown 1000:3000 /app/public/uploads

USER 1000:3000

# 시작 순서: DB 마이그레이션(`app/migrate.py`) → 앱.
# · 마이그레이션이 실패하면 앱을 띄우지 않는다(`&&`) — 건강 검사에 걸려 배포 스크립트가 옛 이미지로 되돌린다.
# · 앱은 마이그레이션 계정을 모른다 — `env -u` 로 그 값을 지운 환경에서 띄운다.
# · `exec` 로 셸을 uvicorn 이 대신한다(PID 1 이 종료 신호를 받게).
CMD ["sh", "-c", "python -m app.migrate && exec env -u MIGRATE_DATABASE_URL uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips '*'"]
