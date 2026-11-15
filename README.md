# CLIP-IT 문학 영상 스크립트

기존 Qwen 스크립트 생성기와 LTX-2용 세 단편의 완성된 영상 프롬프트를 보관합니다. 세 단편은 아래 JSONL을 바로 영상 생성 입력으로 사용하면 됩니다. 별도로 LLM을 다시 실행할 필요는 없습니다.

## 세 단편: 84장면

| 작품 | 장면 수 | 영상 생성 입력 | 전체 한국어 번역 | 장면 길이·발화 |
| --- | ---: | --- | --- | --- |
| 크리스마스 선물 — O. Henry | 30 | [생성 JSONL](data/short_stories/the-gift-of-the-magi.jsonl) | [원문·번역](data/short_stories/the-gift-of-the-magi.source-ko.jsonl) | [audio.json](data/short_stories/the-gift-of-the-magi.audio.json) |
| 열린 창 — Saki | 24 | [생성 JSONL](data/short_stories/the-open-window.jsonl) | [원문·번역](data/short_stories/the-open-window.source-ko.jsonl) | [audio.json](data/short_stories/the-open-window.audio.json) |
| 이기적인 거인 — Oscar Wilde | 30 | [생성 JSONL](data/short_stories/the-selfish-giant.jsonl) | [원문·번역](data/short_stories/the-selfish-giant.source-ko.jsonl) | [audio.json](data/short_stories/the-selfish-giant.audio.json) |

각 생성 JSONL의 한 줄은 정확히 다음 5필드입니다. 원문 전체와 기존 장면 번호를 유지했습니다.

```json
{"scene_id":"1_1","chapter":1,"scene_number":1,"scene_text":"이 장면의 영어 원문 전체","video_script":{"prompt":"LTX-2용 영어 촬영·대사·음성 지침"}}
```

`scene_id`는 작품 안에서 고유합니다. 세 작품 모두 `1_1`부터 시작하므로 작품 slug와 함께 대응시키세요. `.source-ko.jsonl`은 기존 웹 형식인 `Chapter`, `Scene number`, `Content`, `Content_kor`의 4필드입니다. [작품 정보](data/short_stories/books.json)와 [Project Gutenberg 원문 출처](data/short_stories/SOURCES.json)도 함께 제공합니다.

## LTX-2로 영상 생성

각 행의 `video_script.prompt`를 사용하고, 대응하는 `.audio.json`의 `scenes` 배열에서 `scene_id`별 `duration_seconds`를 읽습니다. 장면 길이는 8·10·12초입니다. 음성 생성을 켜고 MP4에도 오디오 트랙을 남기세요.

대사 장면 1~2개를 먼저 생성해 영어 대사, 화자, 입 모양과 실제 소리를 확인한 뒤 나머지를 생성합니다. 《크리스마스 선물》의 `1_18`, `1_29`는 각각 12초인 대사 확인 예시입니다. 한국어 전문을 짧은 클립 안에 전부 낭독하는 방식은 아닙니다.

무음·대사 금지 규칙은 제거했습니다. 환경음만으로 이어지는 장면도 있습니다. 《열린 창》에서 베라가 지어내는 이야기는 실제 사건으로 재연하지 않으며, 인물·소품·행동의 연결은 프롬프트와 음성 sidecar의 메모를 따릅니다.

**이 저장소에는 새로 렌더링한 MP4가 없습니다. 기존 사이트 영상에도 새 대사가 자동으로 생기지 않습니다.** 새 프롬프트로 다시 생성하고 재생 확인을 해야 합니다. 텍스트 검증은 실제 LTX-2 출력 품질 검사를 대신하지 않습니다.

## 완성 영상을 사이트에 등록

작품별 폴더에 `1_1.mp4`, `1_2.mp4`처럼 장·장면 번호로 저장합니다. [주피터 노트북](integrations/content-publisher/publish_completed.ipynb)을 해당 폴더의 작업 환경에서 실행하고 `WORK_SLUG`, `VIDEOS_DIR`를 지정하면 원문·전체 번역·영상이 함께 업로드되고 사이트 등록까지 요청됩니다.

세 작품의 영어 제목·저자·JSONL 경로는 노트북에서 자동으로 지정됩니다. 이미 사이트에 이전 영상이 있으므로 이 노트북은 `REPLACE_VIDEOS = True`로 준비되어 있습니다. 새로 생성한 MP4 폴더를 지정하세요. 같은 번역을 쓸 때는 `REPLACE_TRANSLATIONS = False`를 유지합니다.

별도로 받은 비공개 `.env.content-publisher.json`은 노트북과 같은 폴더에 두고 POSIX 서버에서는 `chmod 600 .env.content-publisher.json`을 적용합니다. 이 파일은 Git에 올리지 않습니다. 없으면 노트북이 숨김 입력을 받습니다. 키·토큰을 셀 코드나 출력에 붙여넣지 마세요.

게시 성공은 영수증의 `ok`, `registered_in_web`, `registered_scenes`로 확인합니다. 같은 파일은 덮어쓰지 않고 재시도할 수 있으며, 새 영상 교체는 명시한 옵션으로 진행합니다. 새 작품의 기본 표지는 서버에서 지정합니다. [자세한 업로드 안내](integrations/content-publisher/README.md)를 참고하세요.

## 후속 작품의 프롬프트 생성

루트의 [mk_script_video.py](mk_script_video.py)는 기존 로컬 Qwen 실행 흐름을 유지하면서 LTX-2 대사·음성 지침을 사용하도록 수정했습니다. 작품 제목·스타일·영상 길이를 지정할 수 있습니다. [생성기 사용 안내](docs/LTX2_SCRIPT_GENERATOR.md)에 CLI 예제가 있습니다.

기존 `data/Emma/`, `data/SignOfFour/` 자료는 그대로 보관합니다. 새 지침이 과거에 생성된 프롬프트나 MP4를 소급해서 바꾸지는 않습니다.

## 모델 없이 검증

저장소 루트에서 Python 3.10 이상으로 실행합니다. API 키, GPU, 모델 다운로드는 필요하지 않습니다.

```bash
python3 -B tools/verify_short_stories.py
python3 -B -m unittest discover -s tests -v
python3 -B -m unittest discover -s integrations/content-publisher/tests -v
```

GitHub Actions도 같은 검증을 실행합니다. 실제 영상 생성·클라우드 업로드는 이 검사에서 실행하지 않습니다.
