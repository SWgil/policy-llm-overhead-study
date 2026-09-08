# 실험 하네스 실행 안내 (로컬 Qwen 환경)

[Policy_LLM_Overhead_Study.md](Policy_LLM_Overhead_Study.md) §6의 실측용 환경. **외부 API 없이 로컬 OpenAI 호환 서버 하나로 전체 실험이 돌아간다.**

## 0. 전제

로컬에 OpenAI 호환 엔드포인트로 Qwen(기본 `Qwen/Qwen3-8B`)이 서빙돼 있을 것. 예:

```bash
vllm serve Qwen/Qwen3-8B \
  --port 8000 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --guided-decoding-backend xgrammar
```

- `--enable-auto-tool-choice --tool-call-parser hermes` — 에이전트가 네이티브 function calling을 쓰기 위해 필요. 없이 띄웠다면 에이전트 모델을 `qwen-local-prompting`으로 바꿀 것(프롬프트 기반 툴 호출).
- `--guided-decoding-backend` — 정책 JSON 봉투를 디코딩 단계에서 강제하는 데 필요. 7~8B 모델에서 형태 실패와 보안 추론 실패를 분리하는 핵심 통제다.

모델 id는 `vllm serve <id>`에 준 값과 정확히 일치해야 한다.

## 준비된 환경

| 항목 | 상태 |
|---|---|
| Python | uv로 3.12.14 설치, `progent/.venv` 생성 완료 |
| agentdojo + secagent | `uv pip install -e` 완료, CLI 동작 확인 |
| Node.js | 24.19.0 |
| gemini-cli | v0.58.0 클론, `npm ci` 완료, conseca 테스트 29개 통과 |

## 트랙 1 — Progent (AgentDojo)

### 서버 점검 (스윕 전 필수)

```bash
cd progent && source .venv/Scripts/activate
python analysis/probe_models.py
SECAGENT_JSON_MODE=True python analysis/probe_models.py    # guided decoding까지 확인
```

엔드포인트·프로바이더 판별·파라미터 호환성(`seed` 거부 여부)·토큰 계측이 한 번에 확인된다. `seed`를 거부하는 서버면 `SECAGENT_SEND_SEED=False`.

### 실행

```bash
./run_sweep.sh m0-nodefense qwen-local banking          # 기준선 (반드시 먼저)
./run_sweep.sh m1-init-only Qwen/Qwen3-8B banking slack
./run_sweep.sh m3-auto-approve Qwen/Qwen3-8B banking slack
```

모드: `m0-nodefense` / `m1-init-only`(≈Conseca) / `m2-auto-deny` / `m3-auto-approve`(논문 기본값) / `m4-hybrid`.

> **M0를 먼저 확보할 것.** 에이전트가 gpt-4o가 아니므로 논문의 절대 수치와 직접 비교할 수 없다. 모든 판정은 동일 에이전트 위에서의 **M0 대비 상대 변화**로 한다.

`m4-hybrid`는 신뢰 컨텍스트 단계(`init`, `update_gate`)에만 경량 모델을 쓰고, 비신뢰 툴 결과를 읽는 `update_gen`만 상위 모델에 맡긴다:

```bash
HEAVY_MODEL=Qwen/Qwen2.5-32B-Instruct \
  ./run_sweep.sh m4-hybrid Qwen/Qwen3-8B banking slack
```

상위 모델이 다른 포트에 있으면 `SECAGENT_POLICY_BASE_URL`을 그쪽으로 두고 경량 모델을 별도 지정하는 식으로 나눌 수 있다.

### 주요 환경변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `LOCAL_MODEL` | `Qwen/Qwen3-8B` | 서버가 응답하는 모델 id |
| `LOCAL_BASE_URL` | `http://127.0.0.1:8000/v1` | 엔드포인트 |
| `SECAGENT_POLICY_MODEL` | 위 로컬 모델 | 정책 모델(전 단계) |
| `SECAGENT_POLICY_MODEL_{INIT,UPDATE_GATE,UPDATE_GEN}` | — | 단계별 개별 지정 |
| `SECAGENT_POLICY_PROVIDER` | 자동 판별 | `local`/`openai`/`anthropic`/`gemini` 강제 |
| `SECAGENT_JSON_MODE` | `True` | 정책 JSON 봉투 강제 |
| `SECAGENT_GUIDED_JSON` | `True` | 로컬에서 guided decoding 사용 |
| `SECAGENT_SEND_SEED` | `True` | `seed` 거부 서버면 `False` |

### 집계

```bash
python analysis/summarize_metrics.py metrics/<tag>.jsonl --group stage --tasks 16
python analysis/summarize_metrics.py metrics/ --group model,stage --csv results.csv
```

논문 Figure 11 형식(단계별 시간·비중)에 토큰·재시도·파싱 실패(`parse_fail`)·형태 위반(`shape_fail`) 열을 더한 표가 나온다.

### 변경 사항

- `secagent/instrument.py` (신규) — 단계별 모델 라우팅, JSONL 메트릭, 프로바이더 판별, guided decoding 스키마
- `secagent/tool.py` — `api_request`에 stage·계측 추가, 3개 호출 지점 태깅, `_parse_policy` 신설, `check_tool_call` Z3 타이머, **모델 id 접두사 대신 프로바이더 기반 분기**(로컬 모델이 어떤 id로 서빙되든 동작)
- `agentdojo/.../models.py`, `agent_pipeline/agent_pipeline.py` — 에이전트 LLM용 `qwen-local` / `qwen-local-prompting` 추가
- `analysis/summarize_metrics.py`, `analysis/probe_models.py`, `run_sweep.sh` (신규)
- **업스트림 버그 수정**: `api_request`의 o1/o3 분기가 뒤따르는 `if/else`에 덮어써져 추론 모델이 API를 두 번 호출하고 첫 결과를 버리던 문제를 `elif`로 수정

## 트랙 2 — Conseca (gemini-cli)

논문 구현체가 아니라 Google이 실제로 출하한 구현체를 측정한다. 이쪽은 Gemini 백엔드가 필요하다.

### 활성화

`~/.gemini/settings.json`:

```json
{ "security": { "enableConseca": true } }
```

### 실행

```bash
cd gemini-cli
export CONSECA_METRICS_PATH="$PWD/metrics/conseca.jsonl"
export CONSECA_RUN_TAG=flash-llm-enforcer
npm start -- --debug
```

### 비교할 구성

| 구성 | 환경변수 |
|---|---|
| 기본(출하 상태) | 없음 — 생성·강제 모두 `gemini-2.5-flash` |
| 정책 모델 경량화 | `CONSECA_POLICY_MODEL=gemini-3.1-flash-lite` |
| 강제기만 경량화 | `CONSECA_ENFORCER_MODEL=gemini-3.1-flash-lite` |
| **결정론적 강제기(논문 설계)** | `CONSECA_ENFORCER=deterministic` |

결정론 모드는 생성기에게 `arg_constraints`(인자명 → 정규식)를 추가로 요구하고, 강제를 LLM 호출 없이 JS에서 평가한다. **툴 호출당 LLM 1회가 통째로 사라진다.** 기본값은 출하 상태이므로 LLM 강제기 측정에는 영향이 없다.

### 변경 사항

- `packages/core/src/safety/conseca/metrics.ts` (신규) — 단계별 지연·토큰 JSONL (Progent 측과 동일 스키마)
- `packages/core/src/safety/conseca/deterministic-enforcer.ts` (신규) + 테스트 9개
- `policy-generator.ts` / `policy-enforcer.ts` — 모델 오버라이드, 계측, 결정론 모드 분기
- `types.ts` — `ToolPolicy.arg_constraints?` 추가

기존 20개 + 신규 9개 = **테스트 29개 통과**, 타입체크·prettier 통과.

## 알려진 제약

1. **에이전트 LLM이 gpt-4o가 아니므로 논문 절대 수치와 직접 대조 불가.** M0 무방어 기준선으로 정규화해 상대 비교할 것.
2. **트랙 2는 Gemini 백엔드가 필요하다.** 로컬 모델로 대체하려면 `contentGenerator`를 갈아끼워야 하므로 범위 밖으로 둔다.
