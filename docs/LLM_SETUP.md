# LLM 보고서 연동 가이드

주유소 입지 보고서 생성 엔드포인트(`/api/stations/{id}/report`)는 LLM에 요청을 보내 분석 요약을 작성합니다. 아래 환경변수를 설정하면 실제 모델에 연결할 수 있습니다.

## 필수 환경 변수

| 변수 | 설명 |
| --- | --- |
| `LLM_API_KEY` | OpenAI 또는 호환 API의 비밀 키. 미설정 시 기본 분석 문구로 폴백합니다. |

## 선택 환경 변수

| 변수 | 설명 |
| --- | --- |
| `LLM_API_URL` | Chat Completions 엔드포인트 URL. 기본값은 `https://api.openai.com/v1/chat/completions`. |
| `LLM_MODEL` | 사용할 모델 ID. 기본값은 `gpt-4o-mini`. |
| `LLM_TIMEOUT` | 요청 타임아웃(초). 기본값은 `30`. |
| `LLM_TEMPERATURE` | 생성 온도. 기본값은 `0.3`. |
| `LLM_FORCE_JSON` | `false`로 지정하면 JSON 강제 옵션을 비활성화합니다. 기본은 강제 JSON. |

## 주유소별 라우팅

여러 모델이나 엔드포인트를 주유소 ID마다 다르게 사용하고 싶다면 라우팅 테이블을 구성하세요. 두 가지 방법을 지원합니다.

1. `LLM_ROUTING_TABLE` 환경 변수에 JSON 문자열을 직접 지정
2. `LLM_ROUTING_FILE` 환경 변수에 JSON 파일 경로 지정 (예: `configs/llm_routes.json`)

JSON 구조 예시는 다음과 같습니다.

```json
{
  "0": {
    "model": "gpt-4o",
    "temperature": 0.2
  },
  "42": {
    "api_key": "sk-live-another-key",
    "base_url": "https://my-azure-endpoint",
    "model": "gpt-35-turbo",
    "force_json": true
  },
  "*": {
    "temperature": 0.4
  }
}
```

- 키는 문자열 형태의 주유소 ID입니다.
- `*` 또는 `default` 키는 기본 라우팅을 오버라이드합니다.
- 각 항목에서는 `api_key`, `base_url`, `model`, `timeout`, `temperature`, `force_json`을 덮어쓸 수 있습니다.

## 분석 입력 데이터

LLM에는 다음 정보가 전달됩니다.

- 주유소 기본 속성 (상호, 주소, 용도지역 등)
- 추천 서비스가 반환한 상위 5개 활용 방안 요약
- 반경 300m 내 필지 통계(면적 분포, 평균 면적, 주요 지목, 중심까지의 최단 거리)

환경변수 설정 후 `python main.py`로 서버를 실행하면 LLM 기반 보고서를 실시간으로 확인할 수 있습니다.
