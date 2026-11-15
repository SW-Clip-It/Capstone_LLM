# Jupyter에서 완성된 작품 등록

원문과 영상 프롬프트가 들어 있는 JSONL, 선택한 한국어 원문, 완성된 MP4 폴더를 함께 보냅니다. 업로드 뒤 웹 등록까지 성공하면 사이트에서 원문과 영상을 볼 수 있습니다. 별도 영상 생성 호출은 하지 않으며, 작성된 프롬프트의 대사 유무를 바꾸지 않습니다.

## 준비

저장소 전체를 클론한 뒤 `integrations/content-publisher/`를 Jupyter 작업 폴더로 맞추고 `publish_completed.ipynb`를 순서대로 실행합니다. 이 저장소의 노트북은 `../../data/short_stories/books.json`과 해당 작품의 영어·한국어 JSONL을 함께 읽으므로 노트북 파일만 다른 폴더로 복사하지 않습니다. `WORK_SLUG`와 `VIDEOS_DIR`를 지정하면 세 작품의 메타데이터·입력 경로가 자동으로 선택됩니다. 파일은 브라우저 PC가 아닌 Jupyter 커널 서버에 있어야 합니다. 영상 인코딩을 끝내고 파일을 닫은 뒤 실행하세요.

영상 담당자는 다음 세 값을 각각 받습니다. 키와 토큰은 노트북 코드·출력·Git·공용 채팅에 저장하지 않습니다.

- `clipit-script-uploader`의 AWS 키: `originals/*`, `scripts/*` 저장 전용입니다.
- `clipit-video-uploader`의 AWS 키: `videos/*` 저장 전용입니다.
- `CONTENT_PUBLISH_TOKEN`: 완성된 작품 등록 API 전용입니다. `VIDEO_WORKER_TOKEN`, `SCRIPT_INGEST_TOKEN`, 관리자 키와 다릅니다.

두 AWS 키는 서로 다른 세션으로 사용하고 STS의 정확한 IAM 사용자를 확인합니다. 관리자/root 키나 DB 암호는 사용하지 않습니다. 버킷과 리전은 `clipit-videos-506318770879` / `ap-northeast-1`입니다. Jupyter 서버에서 웹 API·S3·STS에 외부 HTTPS 연결이 필요합니다.

별도로 받은 비공개 `.env.content-publisher.json`을 노트북과 같은 폴더에 놓으면 첫 설정 셀이 다음 여섯 키만 검증해서 현재 프로세스 환경에 불러옵니다. 파일이나 값을 출력하지 않으며 일반 ZIP에 넣지 않습니다. POSIX 서버에서는 `chmod 600 .env.content-publisher.json`으로 소유자만 읽게 설정합니다. 이 파일이 없으면 숨김 입력을 사용합니다.

`CLIPIT_API_BASE`, `CONTENT_PUBLISH_TOKEN`, `CLIPIT_SCRIPT_ACCESS_KEY_ID`, `CLIPIT_SCRIPT_SECRET_ACCESS_KEY`, `CLIPIT_VIDEO_ACCESS_KEY_ID`, `CLIPIT_VIDEO_SECRET_ACCESS_KEY`

기본 `AWS_ACCESS_KEY_ID`·`AWS_PROFILE` 등과 섞거나 자동으로 대체하지 않습니다. JSON 설정은 셸 명령으로 실행하지 않습니다.

## 입력 파일

생성자가 받은 기존 다섯 필드를 그대로 읽습니다. 한 줄은 한 장면입니다.

```json
{"scene_id":"1_1","chapter":1,"scene_number":1,"scene_text":"이 장면의 영어 원문 전체","video_script":{"prompt":"실제로 영상 생성에 사용한 영어 프롬프트"}}
```

`chapter`, `scene_number`는 1 이상의 정수이고 ID와 장·장면 번호 조합은 중복되지 않아야 합니다. 실패·미리보기 행은 거절합니다. 이 helper는 생성이나 번역을 대신 수행하지 않습니다.

MP4 폴더에는 `1_1.mp4`, `1_2.mp4`처럼 장·장면 번호에 맞는 **모든 입력 장면**의 파일이 있어야 합니다. JSONL 순서와 무관하게 번호로 대응합니다. 각 MP4는 5 GiB 이하여야 합니다. 일부 장면만 등록하려면 그 장면만 포함한 별도 입력 JSONL을 사용합니다.

한국어 파일은 선택입니다. 기존 웹 원문 형식을 읽고 영어 원문도 함께 있으면 정확히 일치하는지 확인합니다.

```json
{"Chapter":1,"Scene number":1,"Content":"이 장면의 영어 원문 전체","Content_kor":"이 장면의 한국어 번역 전체"}
```

`Content_kor: null`은 번역 미제공이며 기존 번역을 지우지 않습니다. 번역 파일 대신 다섯 필드 입력에 선택 필드 `content_ko`를 추가해도 됩니다. 한국어 제목은 노트북의 `TITLE_KO`로 따로 지정합니다. 번역은 업로드 원문 객체와 웹의 `content_ko`에 함께 보관합니다.

## 실행과 성공 확인

노트북의 작품 slug·제목·저자와 입력 경로를 지정한 뒤 로컬 검증을 먼저 실행합니다. 검증은 클라우드에 접속하지 않습니다. 터미널 검증도 가능합니다.

```bash
python3 clipit_publish.py --scripts '/입력/book.jsonl' --videos '/완성된/mp4폴더' \
  --slug book --title 'Book' --author 'Author' --korean '/입력/book-ko.jsonl'
```

검증 후 숨김 입력으로 세 종류의 키·토큰을 넣고 게시 셀을 실행합니다. 프로그램은 원문·스크립트·영상의 업로드를 모두 끝낸 뒤 `/api/integrations/publications`를 호출합니다. 성공 영수증의 `ok: true`, `registered_in_web: true`, `registered_scenes`를 확인하세요. S3 저장만 성공하고 웹 등록은 실패했다면 같은 파일로 다시 실행합니다. 비싼 영상 생성을 다시 할 필요는 없습니다.

표지는 웹 서버가 자동으로 지정합니다. 이미 있는 표지는 보존하고, 새 작품이나 표지가 없는 작품에는 기본 표지를 사용합니다. 썸네일·길이·모델 정보는 등록 필수가 아닙니다.

## 다시 올리기와 보호

- 같은 파일은 같은 SHA-256 경로를 사용합니다. `If-None-Match: *`와 S3 checksum으로 저장하고 기존 객체는 덮어쓰지 않습니다.
- 영상이 달라지면 새로운 경로에 저장됩니다. 기존 웹 영상을 바꾸려면 `REPLACE_VIDEOS = True`를 명시해야 합니다. 같은 장면의 프롬프트도 그때 함께 교체됩니다.
- 이미 있는 번역을 수정하려면 `REPLACE_TRANSLATIONS = True`를 지정합니다. 처음 번역을 추가할 때는 필요 없습니다.
- **기존 영어 원문은 두 옵션을 켜도 바꿀 수 없습니다.** 수정 원문이나 장면 재분할판은 새 작품 slug를 사용합니다. 제목·저자가 다른 작품을 기존 slug에 넣어도 거절합니다.
- 이 게시 방식은 새 영상 작업을 만들지 않습니다. 해당 장면에 queued/running 생성 작업이 있으면 먼저 웹 담당자와 완료·취소 상태를 확인합니다.
- 기존 `videos/{slug}/{chapter}_{scene}.mp4` 업로더와 다른 불변 경로를 사용합니다. 이 helper 결과를 기존 S3 동기화로 등록하지 않습니다. 성공한 publication API가 정확한 장면에 연결합니다.

## 오류와 다음 행동

| 결과 | 다음 행동 |
| --- | --- |
| 401 | `CONTENT_PUBLISH_TOKEN`과 배포 서버 설정을 확인합니다. 다른 담당자 토큰이나 관리자 키로 바꾸지 않습니다. |
| 404/405 | 이 API가 포함된 웹 배포와 `CLIPIT_API_BASE`를 확인합니다. |
| `PUBLICATION_SOURCE_CONFLICT` | 기존 영어 원문과 다릅니다. 파일·장면 번호를 확인하고 수정판은 새 slug를 사용합니다. |
| `PUBLICATION_WORK_CONFLICT` | 기존 작품의 정확한 제목·저자를 확인합니다. |
| `PUBLICATION_VIDEO_CONFLICT` | 같은 원문의 의도적인 영상 교체일 때만 `REPLACE_VIDEOS`를 켭니다. |
| `PUBLICATION_TRANSLATION_CONFLICT` | 기존 번역 수정이 맞는지 확인한 뒤 `REPLACE_TRANSLATIONS`를 켭니다. |
| `PUBLICATION_ACTIVE_GENERATION` | 웹 담당자가 해당 장면의 진행 작업을 먼저 정리합니다. |
| `PUBLICATION_VIDEO_NOT_FOUND` / `INVALID_PUBLICATION_VIDEO` | 모든 MP4 업로드와 파일 크기·`video/mp4` 유형을 확인합니다. 파일을 수정하지 말고 동일 입력으로 다시 실행합니다. |
| `PUBLICATION_VIDEO_CHECKSUM_MISMATCH` | 저장된 객체의 SHA-256이 경로와 다릅니다. 파일을 직접 덮어쓰지 말고 이 helper로 올린 원본과 경로를 웹 담당자가 확인합니다. |
| 네트워크·응답 유실 | 같은 입력으로 재실행합니다. 동일한 콘텐츠 객체는 중복 저장하지 않습니다. |

## 웹 담당자 배포 계약

기존 `000`, `001`, `002` migration이 적용되어 있어야 합니다. 새 migration은 필요하지 않습니다. `CONTENT_PUBLISH_TOKEN`을 다른 두 integration token과 다른 난수로 배포합니다. 웹 런타임은 비공개 원문·스크립트 읽기와 영상 HEAD 권한을 사용하며, 생성자는 위 두 쓰기 전용 IAM 키를 분리해서 사용합니다. 일반 담당자에게 웹 런타임 AWS 키·DB 암호·`ADMIN_API_KEY`를 주지 않습니다.

서버는 두 JSONL의 실제 bytes로 batch hash를 재계산하고 장면·원문·성공 상태를 검증합니다. 영상 경로는 해당 slug·장·장면의 `videos/{slug}/published/{chapter}_{scene}/video-{sha256}.mp4`만 허용하며 HEAD의 크기·MIME·S3 SHA-256 checksum을 경로와 대조합니다. 모든 객체 확인 후 작품·원문·번역·스크립트·영상 연결을 한 DB 트랜잭션으로 반영합니다. 최종 SQL에도 교체 허용 조건을 넣어 동시에 들어온 관리자 영상을 조용히 덮어쓰지 않습니다. 기존 장면의 ID 표기가 `1_1`과 내부 ID로 다르더라도 장·장면 번호와 동일 원문으로 매칭합니다. 외부 URL을 서버가 다운로드하는 기능은 없습니다.

로컬 검증:

```bash
python3 -m unittest discover -s tests -v
```

로컬 테스트는 실제 AWS·운영 DB·Jupyter 네트워크에서의 게시 확인을 대신하지 않습니다. 처음 사용할 때 실제 완성 영상 한 장면으로 성공 영수증과 웹 표시를 함께 확인합니다.
