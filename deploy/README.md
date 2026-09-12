# 이미지 기반 운영 배포

`main` 머지 뒤 모든 CI/CD 계산은 UbuntuVM의 self-hosted GitHub Actions Runner에서 수행한다.
GitHub 호스팅 Runner와 Actions artifact 저장소는 사용하지 않는다.

1. VM이 `Dockerfile`로 `bae-blog:vX.Y.Z` 이미지를 만든다.
2. 이미지를 TrueNAS의 `bae-registry`로 push하고 SHA-256 digest를 확정한다.
3. `truenas/bae-blog.yml`을 제한 SSH 연결의 stdin으로 보낸다.
4. NAS의 강제 명령 스크립트가 이미지 태그·서비스·볼륨·네트워크·Traefik 라벨을 검증한다.
5. 버전 태그와 digest로 고정한 YAML을 TrueNAS `bae-blog` 앱에 적용하고 healthy 상태와 실행
   이미지까지 확인한다.

## 영속 데이터

코드는 이미지 안에만 있으며 운영 컨테이너는 코드 디렉터리를 마운트하지 않는다.

- 환경설정: `/mnt/nvme/90.service/blog_data/.env.api`
- 업로드: `/mnt/nvme/90.service/blog_data/uploads`
- 적용된 compose: `/mnt/nvme/90.service/blog_data/compose.yml`
- 로컬 registry 데이터: `/mnt/nvme/90.service/blog_data/registry`

최초 이미지 배포 때 강제 명령 스크립트가 기존 운영 컨테이너를 잠시 멈추고 마지막 데이터
증분을 동기화한다. 성공 후 `.image-cutover-complete` 마커를 남기므로 이후에는 옛 코드
디렉터리를 읽지 않는다.

## NAS에만 있는 보호 설정

저장소에는 도메인과 LAN 주소를 넣지 않는다. 강제 명령이 읽는 `$HOME/bin/deploy-blog.env`에
`TRAEFIK_ROUTER_RULE`과 최초 전환용 `LEGACY_APP_DIR`을 둔다. 저장소의
`nas/deploy-blog-image.sh`는 검토용 원본이며, 실제 forced-command 경로에는 운영자가 직접
복사한다. CI가 이 스크립트 자체를 교체할 권한은 없다.

`truenas/bae-registry.yml`도 저장소에서는 주소 자리표시자를 유지한다. 레지스트리는 한 번만
TrueNAS Custom App으로 만들며, 앱 베이스 이미지 `fastapi-py312:latest`도 최초 한 번 seed한다.

## 롤백

각 배포 직전 TrueNAS 앱 설정은 `compose.previous.yml`에 보존된다. 이미지 pull, 앱 갱신,
healthy 확인 또는 실행 이미지 검증이 실패하면 강제 명령이 직전 compose를 다시 적용한다.
최초 전환처럼 앱이 정지된 상태에서 compose를 바꾼 경우에는 갱신·롤백 뒤 TrueNAS 앱을
명시적으로 다시 시작한다.
정상 배포 뒤 수동 롤백이 필요하면 보호된 스크립트에서 이전 버전 태그의 YAML을 적용한다.
