#!/usr/bin/env bash
# GitHub Actions의 제한 SSH 키가 호출하는 운영 배포 진입점이다.
# 저장소의 compose 템플릿을 stdin으로 받아 고정된 bae-blog 앱에만 적용한다.

set -euo pipefail

APP_NAME="bae-blog"
CONTAINER_NAME="bae-blog"
DATA_DIR="/mnt/nvme/90.service/blog_data"
DEPLOY_CONFIG="$HOME/bin/deploy-blog.env"
COMPOSE_FILE="$DATA_DIR/compose.yml"
PREVIOUS_COMPOSE="$DATA_DIR/compose.previous.yml"
REGISTRY="127.0.0.1:5000"
TIMEOUT="${DEPLOY_HEALTH_TIMEOUT:-120}"

original_command="${SSH_ORIGINAL_COMMAND:-}"
if [[ -z "$original_command" && "$#" -gt 0 ]]; then
    original_command="$*"
fi
read -r action version digest extra <<< "$original_command"

# 새 workflow가 main에 들어가기 전 기존 CD의 재시작 명령도 계속 받는다.
if [[ "$action" == "restart" && -z "${version:-}" && -z "${digest:-}" && -z "${extra:-}" ]]; then
    if ! docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
        echo "컨테이너 없음: $CONTAINER_NAME" >&2
        exit 10
    fi
    echo "재시작: $CONTAINER_NAME"
    docker restart "$CONTAINER_NAME" >/dev/null
    deadline=$((SECONDS + TIMEOUT))
    while (( SECONDS < deadline )); do
        status=$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || true)
        health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER_NAME" 2>/dev/null || true)
        if [[ "$status" == "running" && ( "$health" == "healthy" || "$health" == "none" ) ]]; then
            echo "정상: status=$status health=$health"
            exit 0
        fi
        if [[ "$status" == "exited" || "$status" == "dead" ]]; then
            docker logs --tail 60 "$CONTAINER_NAME" >&2 2>&1 || true
            exit 11
        fi
        sleep 3
    done
    echo "제한시간(${TIMEOUT}s) 안에 healthy가 되지 않았다" >&2
    exit 12
fi

if [[ "$action" != "deploy" || -n "${extra:-}" ]]; then
    echo "사용법: deploy v<major>.<minor>.<patch> sha256:<digest>" >&2
    exit 2
fi
if [[ ! "${version:-}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "허용되지 않은 버전: ${version:-없음}" >&2
    exit 2
fi
if [[ ! "${digest:-}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "허용되지 않은 이미지 digest: ${digest:-없음}" >&2
    exit 2
fi
if [[ ! -r "$DEPLOY_CONFIG" ]]; then
    echo "배포 설정을 읽을 수 없다: $DEPLOY_CONFIG" >&2
    exit 3
fi

# shellcheck disable=SC1090
source "$DEPLOY_CONFIG"
: "${TRAEFIK_ROUTER_RULE:?deploy.env에 TRAEFIK_ROUTER_RULE이 필요하다}"

template_file=$(mktemp /tmp/bae-blog-compose.incoming.XXXXXX)
rendered_file=$(mktemp /tmp/bae-blog-compose.rendered.XXXXXX)
previous_file=$(mktemp /tmp/bae-blog-compose.previous.XXXXXX)
# trap에서 간접 호출한다.
# shellcheck disable=SC2329
cleanup() {
    rm -f "$template_file" "$rendered_file" "$previous_file"
}
trap cleanup EXIT

# 비정상적으로 큰 입력은 compose가 아니라 잘못된 전송으로 본다.
head -c 65537 > "$template_file"
if [[ $(wc -c < "$template_file") -gt 65536 ]]; then
    echo "compose 입력이 64KiB를 넘는다" >&2
    exit 4
fi

VERSION="$version" DIGEST="$digest" ROUTER_RULE="$TRAEFIK_ROUTER_RULE" \
    python3 - "$template_file" "$rendered_file" <<'PY'
import os
import pathlib
import sys

import yaml

source = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
version = os.environ["VERSION"]
digest = os.environ["DIGEST"]
router_rule = os.environ["ROUTER_RULE"]

text = source.read_text(encoding="utf-8")
if (
    text.count("__VERSION__") != 1
    or text.count("__DIGEST__") != 1
    or text.count("__TRAEFIK_ROUTER_RULE__") != 1
):
    raise SystemExit("compose 템플릿 자리표시자가 올바르지 않다")
text = (
    text.replace("__VERSION__", version)
    .replace("__DIGEST__", digest)
    .replace("__TRAEFIK_ROUTER_RULE__", router_rule)
)
config = yaml.safe_load(text)

if set(config or {}) - {"version", "networks", "services"}:
    raise SystemExit("허용되지 않은 compose 최상위 항목")
services = config.get("services") or {}
if set(services) != {"bae-blog"}:
    raise SystemExit("bae-blog 단일 서비스만 허용한다")
service = services["bae-blog"]

allowed_service_keys = {
    "image", "container_name", "env_file", "user", "volumes", "networks",
    "restart", "deploy", "healthcheck", "labels", "logging",
}
if set(service) != allowed_service_keys:
    raise SystemExit("허용되지 않았거나 빠진 서비스 설정")

expected = {
    "image": f"127.0.0.1:5000/bae-blog:{version}@{digest}",
    "container_name": "bae-blog",
    "env_file": ["/mnt/nvme/90.service/blog_data/.env.api"],
    "user": "1000:3000",
    "volumes": ["/mnt/nvme/90.service/blog_data/uploads:/app/public/uploads"],
    "networks": ["db_bridge"],
    "restart": "unless-stopped",
}
for key, value in expected.items():
    if service.get(key) != value:
        raise SystemExit(f"허용되지 않은 {key} 설정")

expected_healthcheck = {
    "test": ["CMD", "curl", "-fsS", "http://localhost:8080/healthz"],
    "interval": "30s",
    "timeout": "5s",
    "retries": 3,
    "start_period": "10s",
}
if service.get("healthcheck") != expected_healthcheck:
    raise SystemExit("허용되지 않은 healthcheck 설정")
expected_deploy = {"resources": {"limits": {"cpus": "1.0", "memory": "512M"}}}
if service.get("deploy") != expected_deploy:
    raise SystemExit("허용되지 않은 자원 제한")
expected_logging = {
    "driver": "syslog",
    "options": {
        "syslog-address": "udp://127.0.0.1:5514",
        "syslog-format": "rfc5424micro",
        "tag": "{{.Name}}",
    },
}
if service.get("logging") != expected_logging:
    raise SystemExit("허용되지 않은 로그 설정")

labels = set(service.get("labels") or [])
expected_labels = {
    "traefik.enable=true",
    f"traefik.http.routers.blog.rule={router_rule}",
    "traefik.http.routers.blog.entrypoints=web",
    "traefik.http.services.blog.loadbalancer.server.port=8080",
}
if labels != expected_labels:
    raise SystemExit("Traefik 라벨이 보호된 설정과 다르다")
if config.get("networks") != {"db_bridge": {"external": True}}:
    raise SystemExit("db_bridge 외 네트워크는 허용하지 않는다")

target.write_text(text, encoding="utf-8")
PY

image="$REGISTRY/bae-blog:$version@$digest"
echo "이미지 받기: $image"
docker pull "$image"

current_config=$(sudo -n midclt call app.config "$APP_NAME")
CURRENT_CONFIG="$current_config" python3 - "$previous_file" <<'PY'
import json
import os
import pathlib
import sys

import yaml

config = json.loads(os.environ["CURRENT_CONFIG"])
pathlib.Path(sys.argv[1]).write_text(
    yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)
PY
sudo -n install -o 1000 -g 3000 -m 640 "$previous_file" "$PREVIOUS_COMPOSE"

first_cutover=false
cutover_marker="$DATA_DIR/.image-cutover-complete"
if [[ -n "${LEGACY_APP_DIR:-}" ]] && ! sudo -n test -f "$cutover_marker"; then
    if [[ ! -f "$LEGACY_APP_DIR/.env.api" || ! -d "$LEGACY_APP_DIR/public/uploads" ]]; then
        echo "기존 운영 데이터 경로가 올바르지 않다: $LEGACY_APP_DIR" >&2
        exit 5
    fi
    echo "최초 전환: 기존 앱을 멈추고 영속 데이터를 최종 동기화한다"
    docker stop "$CONTAINER_NAME" >/dev/null
    if ! sudo -n rsync -a "$LEGACY_APP_DIR/public/uploads/" "$DATA_DIR/uploads/" \
        || ! sudo -n install -o 1000 -g 3000 -m 640 "$LEGACY_APP_DIR/.env.api" "$DATA_DIR/.env.api"; then
        docker start "$CONTAINER_NAME" >/dev/null || true
        echo "영속 데이터 최종 동기화 실패" >&2
        exit 5
    fi
    first_cutover=true
fi

sudo -n install -o 1000 -g 3000 -m 640 "$rendered_file" "$COMPOSE_FILE"

compose_payload() {
    python3 - "$1" <<'PY'
import json
import pathlib
import sys
print(json.dumps({"custom_compose_config_string": pathlib.Path(sys.argv[1]).read_text()}))
PY
}

rollback() {
    echo "직전 compose로 되돌리는 중" >&2
    previous_payload=$(compose_payload "$previous_file")
    if sudo -n midclt call -j app.update "$APP_NAME" "$previous_payload"; then
        sudo -n install -o 1000 -g 3000 -m 640 "$previous_file" "$COMPOSE_FILE"
        echo "롤백 적용 완료" >&2
    else
        echo "롤백도 실패했다" >&2
    fi
}

payload=$(compose_payload "$rendered_file")

echo "TrueNAS 앱 갱신: $APP_NAME"
if ! sudo -n midclt call -j app.update "$APP_NAME" "$payload"; then
    echo "앱 갱신 실패" >&2
    rollback
    exit 5
fi

deadline=$((SECONDS + TIMEOUT))
while (( SECONDS < deadline )); do
    status=$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || true)
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER_NAME" 2>/dev/null || true)
    if [[ "$status" == "running" && "$health" == "healthy" ]]; then
        running_image=$(docker inspect -f '{{.Config.Image}}' "$CONTAINER_NAME")
        if [[ "$running_image" != "$image" ]]; then
            echo "실행 이미지가 다르다: $running_image" >&2
            rollback
            exit 6
        fi
        if [[ "$first_cutover" == true ]]; then
            sudo -n touch "$cutover_marker"
            sudo -n chown 1000:3000 "$cutover_marker"
        fi
        echo "정상: image=$running_image health=$health"
        exit 0
    fi
    if [[ "$status" == "exited" || "$status" == "dead" ]]; then
        docker logs --tail 60 "$CONTAINER_NAME" >&2 2>&1 || true
        rollback
        exit 7
    fi
    sleep 3
done

echo "제한시간(${TIMEOUT}s) 안에 healthy가 되지 않았다" >&2
docker logs --tail 60 "$CONTAINER_NAME" >&2 2>&1 || true
rollback
exit 8
