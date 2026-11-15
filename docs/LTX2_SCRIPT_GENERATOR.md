# LTX-2 영상 스크립트 생성기

기존 로컬 Qwen 생성기의 입력·출력 형식을 유지하면서, LTX-2용 대사와 환경음을 포함한 촬영 프롬프트를 만듭니다. 검색이나 외부 API 호출은 추가하지 않았습니다.

먼저 모델을 불러오지 않고 지시문을 확인할 수 있습니다.

```bash
python3 mk_script_video.py \
  --input /path/to/source.jsonl \
  --output /path/to/prompt-preview.jsonl \
  --work-title "The Gift of the Magi" \
  --visual-style "Lyrical New York social realism around 1900" \
  --clip-seconds 8 \
  --prompt-only --limit 3
```

실제 생성은 기존에 쓰던 `torch`, `transformers`, `accelerate` 환경에서 같은 명령의 `--prompt-only`를 빼고 실행합니다. 기본 모델은 `Qwen/Qwen3-14B`이며, 기존 모델·revision·장치·4비트·graph 옵션을 그대로 사용할 수 있습니다. 결과 파일은 새 경로를 지정합니다.

- `--work-title`: 작품 제목. 모든 장면에 같은 값을 전달합니다.
- `--visual-style`: 작품 전체에 유지할 시각 스타일. 원문에 명시된 시대와 사실을 우선합니다.
- `--clip-seconds`: 영상 길이. 기본 8초이며 전체 발화는 초당 2.5단어 이내로 지시합니다.
- 기본 입력 한도는 8,192토큰, 새 출력 한도는 480토큰입니다.

프롬프트는 한 문단 4~8문장으로, 한 연속 촬영과 원인·행동·결과를 담습니다. 원문에 대사가 있으면 보통 한 화자의 짧은 원문 영어 대사를 골라 음색과 입 움직임을 지정합니다. 내레이션은 설명 연결이 꼭 필요한 경우에만 쓰고, 행동으로 충분한 장면은 환경음으로 구성합니다. 화면의 읽을 수 있는 글자와 자막은 넣지 않습니다. 거짓말·비유·가정은 실제 사건처럼 재현하지 않습니다.

출력은 원본 행에 `video_script.prompt`와 기존 생성 메타데이터를 더한 JSONL입니다. 원문·장면 번호·기존 필드는 보존됩니다. 작품 설정과 발화 단어 예산은 `generation_config`에 함께 기록됩니다. `--prompt-only`는 기존처럼 `video_script: null`, `generation_status: "retrieval_only"`와 지시문을 저장합니다.

JSON 구조 검사와 내용 검수는 구분됩니다. `json_valid`는 원문 인용·발화 길이·연속성까지 자동 확인했다는 뜻은 아닙니다. 실제 모델 생성은 이번 수정에서 실행하지 않았습니다.

모델 없이 빠른 검사를 실행합니다.

```bash
python3 -B -m unittest discover -s tests -v
```

이 검사는 대사·스타일·발화 예산 지시와 기존 인자 호환, `--prompt-only`의 모델 로딩 우회를 확인합니다. 원본 참고 파일은 수정하지 않았습니다.
