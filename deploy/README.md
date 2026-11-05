# 이미지 기반 운영 배포

`main` 머지 뒤 모든 CI/CD 계산은 UbuntuVM의 self-hosted GitHub Actions Runner에서 수행한다.
GitHub 호스팅 Runner와 Actions artifact 저장소는 사용하지 않는다.

## PR·릴리스 버전

`main` 직접 푸시는 저장소 규칙이 막으며 PR로만 변경한다. `dev` 푸시는 CI·배포를 실행하지 않고,
`main`으로 가는 PR은 검사를, `main` 머지는 검사 → 릴리스 → 배포를 실행한다.
파이프라인의 원본은 [release.yml](../.github/workflows/release.yml)이다.

릴리스 번호는 최신 `vX.Y.Z` 태그를 기준으로 정한다. `package.json`의 `version`이 최신 태그보다
큰 새 번호이면 그 번호를 사용하고, 그렇지 않으면 최신 태그의 patch를 1 올린다.
같은 버전 태그가 이미 있다는 이유만으로 배포를 건너뛰지는 않는다.

- 버그 수정·문구·스타일 변경은 버전 파일을 수정하지 않는다. patch는 CI가 올린다.
- 기능 추가·제거·화면 개편은 minor, 스택 교체·데이터 구조 변경은 major를 수동으로 올린다.
  `package.json`의 `version`과 `package-lock.json`의 최상위 `version`·`packages[""].version`을 함께 바꾼다.
- CI는 릴리스 태그만 만들고 버전 파일을 `main`에 되밀지 않는다. 따라서 `package.json` 숫자는
  실제 릴리스보다 뒤처질 수 있으며, 배포된 버전은 운영 컨테이너의 실행 이미지 태그·digest로 확인한다.
- 이미 배포된 태그를 삭제하거나 같은 이름으로 다시 만들지 않는다.

## 이미지 적용

1. VM이 `Dockerfile`로 `bae-blog:vX.Y.Z` 이미지를 만든다.
2. 이미지를 TrueNAS의 `bae-registry`로 push하고 SHA-256 digest를 확정한다.
3. `truenas/bae-blog.yml`을 제한 SSH 연결의 stdin으로 보낸다.
4. NAS의 강제 명령 스크립트가 이미지 태그·서비스·볼륨·네트워크·Traefik 라벨을 검증한다.
5. 버전 태그와 digest로 고정한 YAML을 TrueNAS `bae-blog` 앱에 적용하고 healthy 상태와 실행
   이미지까지 확인한다.
6. CI가 `HEALTH_URL` 응답을 확인한다. 응답 성공은 화면의 JS·상호작용 검증을 대신하지 않는다.

## DB 변경

`app/migrations/NNNN_이름.sql`에 추가한 변경은 컨테이너가 뜰 때 앱보다 먼저 적용된다.
새 테이블·기본값이 있는 새 컬럼·데이터 채우기처럼 **더하기만** 하며, 재실행에도 안전하도록 작성한다.
배포 실패 시 이미지는 이전 것으로 돌아가지만 DB는 그대로이므로, 삭제·이름 변경은 옛 코드를 깨뜨린다.

## 영속 데이터

코드는 이미지 안에만 있으며 운영 컨테이너는 코드 디렉터리를 마운트하지 않는다.

- 환경설정: `/mnt/nvme/90.service/blog_data/.env.api`
- 업로드: `/mnt/nvme/90.service/blog_data/uploads`
- 적용된 compose: `/mnt/nvme/90.service/blog_data/compose.yml`

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

이 레지스트리는 블로그 전용이 아니라 **NAS 공용**이다(`bae-stock-ticker`와 공용 베이스
`fastapi-py312`도 들어 있다). 그래서 데이터는 블로그 영속 데이터와 분리해
`/mnt/nvme/90.service/registry_data/data`에 둔다(2026-09-12 이전). 주소는 그대로라 CI와
배포 스크립트는 이 경로를 모른다.

## 롤백

각 배포 직전 TrueNAS 앱 설정은 `compose.previous.yml`에 보존된다. 이미지 pull, 앱 갱신,
healthy 확인 또는 실행 이미지 검증이 실패하면 강제 명령이 직전 compose를 다시 적용한다.
최초 전환처럼 앱이 정지된 상태에서 compose를 바꾼 경우에는 갱신·롤백 뒤 TrueNAS 앱을
명시적으로 다시 시작한다.
정상 배포 뒤 수동 롤백이 필요하면 보호된 스크립트에서 이전 버전 태그의 YAML을 적용한다.
