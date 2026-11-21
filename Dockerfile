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

# AI CLI (codex · agy) — 빌드 시 최신 설치. 설치 단계에서 VCS_REF를 참조해 새 커밋마다 다시 설치한다.
# 실행 중 자체 업데이트는 하지 않는다. CI·배포 빌드와 관리자 화면에서 실제 바이너리 버전을 확인한다.
# 실행 파일은 이미지(/usr/local/bin), 로그인(codex auth.json · agy OAuth 토큰)은 볼륨(/data/codex)에 둔다.
RUN echo "AI CLI install revision: ${VCS_REF}" \
    && curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_HOME=/opt/codex CODEX_INSTALL_DIR=/usr/local/bin sh \
    && /usr/local/bin/codex --version \
    && HOME=/opt/agy-install curl -fsSL https://antigravity.google/cli/install.sh | HOME=/opt/agy-install bash \
    && cp /opt/agy-install/.local/bin/agy /usr/local/bin/agy \
    && rm -rf /opt/agy-install \
    && /usr/local/bin/agy --version
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
