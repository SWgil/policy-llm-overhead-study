# 실험 하네스 실행 안내 — 다른 환경·다른 모델로 옮기기

[Policy_LLM_Overhead_Study.md](Policy_LLM_Overhead_Study.md)의 실측용 하네스. Progent의 정책 LLM을 **단계별(init / update_gate / update_gen)로 계측하고 단계마다 다른 모델을 배정**할 수 있게 만든 것이다.

이 문서는 **더 좋은 GPU와 더 좋은 모델이 있는 환경으로 옮겨 다시 돌리는 법**에 초점을 맞춘다. 8GB GPU에서 돌린 파일럿 결과와 그때 밟은 함정들은 리포트 §6에 있다.

---

## 1. 옮길 때 바꿔야 하는 것은 세 가지뿐이다

하네스는 **OpenAI 호환 엔드포인트 하나**만 알면 된다. 서버를 띄우고 아래 세 값만 바꾸면 그대로 돈다.

| 값 | 의미 | 예 |
|---|---|---|
| `LOCAL_BASE_URL` | 모델이 서빙되는 엔드포인트 | `http://127.0.0.1:8000/v1` |
| `LOCAL_MODEL` | **에이전트** 모델 id (스윕 내내 고정) | `Qwen/Qwen2.5-72B-Instruct` |
| `run_sweep.sh`의 2번째 인자 | **정책** 모델 id (스윕에서 바뀌는 변수) | `Qwen/Qwen2.5-7B-Instruct` |

```bash
LOCAL_BASE_URL=http://127.0.0.1:8000/v1 \
LOCAL_MODEL=Qwen/Qwen2.5-72B-Instruct \
  ./run_sweep.sh m3-auto-approve Qwen/Qwen2.5-7B-Instruct banking
```

모델 id는 서버에 등록된 이름과 **정확히** 일치해야 한다(`vllm serve <id>`에 준 값, 또는 `ollama list`의 이름).

> **에이전트와 정책 모델을 헷갈리지 말 것.** 이 연구가 바꾸는 변수는 정책 모델 하나다. 에이전트는 스윕 내내 고정해야 arm 간 비교가 성립한다.

---

## 2. 백엔드별 레시피

### vLLM (권장 — 진짜 guided decoding을 지원하는 유일한 선택지)

```bash
vllm serve Qwen/Qwen2.5-72B-Instruct \
  --port 8000 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --guided-decoding-backend xgrammar
```

- `--enable-auto-tool-choice --tool-call-parser hermes` — 에이전트가 네이티브 function calling을 쓰기 위해 필요. 없으면 에이전트 모델을 `qwen-local-prompting`으로 바꿀 것(`AGENT_MODEL=qwen-local-prompting`, 프롬프트 기반 툴 호출).
- `--guided-decoding-backend` — 정책 JSON 봉투를 **디코딩 단계에서** 강제한다. 이게 있어야 "형식 실패"와 "보안 추론 실패"가 분리된다(§5-①).

에이전트와 정책 모델을 **다른 크기로 쓰려면 서버를 둘 띄우고** 포트를 나눈다:

```bash
# 8000 = 에이전트(대형), 8001 = 정책(소형)
LOCAL_BASE_URL=http://127.0.0.1:8000/v1 \
LOCAL_MODEL=Qwen/Qwen2.5-72B-Instruct \
SECAGENT_POLICY_BASE_URL=http://127.0.0.1:8001/v1 \
  ./run_sweep.sh m3-auto-approve Qwen/Qwen2.5-7B-Instruct banking
```

`SECAGENT_POLICY_BASE_URL`을 따로 주면 정책 쪽만 다른 서버로 간다(주지 않으면 `LOCAL_BASE_URL`을 따라간다).

### Ollama (단일 GPU·Windows 등 vLLM이 안 되는 환경)

```bash
setx OLLAMA_MAX_LOADED_MODELS 2     # 에이전트+정책 동시 상주 (§5-③)
setx OLLAMA_CONTEXT_LENGTH 8192     # 기본 4096은 프롬프트를 자른다 (§5-②)
ollama pull qwen2.5:7b && ollama pull qwen2.5:0.5b
```

```bash
LOCAL_BASE_URL=http://127.0.0.1:11434/v1 LOCAL_MODEL=qwen2.5:7b \
  ./run_sweep.sh m3-auto-approve qwen2.5:0.5b banking
```

Ollama는 `guided_json`을 **무시**한다. 하네스가 자동으로 `json_schema`로 내려간다(§5-①).

### 호스티드 API (gpt-4o 등으로 논문 수치와 직접 대조하고 싶을 때)

정책 모델 id만 바꾸면 프로바이더가 자동 판별된다.

```bash
export OPENAI_API_KEY=sk-...
AGENT_MODEL=gpt-4o-2024-08-06 ./run_sweep.sh m3-auto-approve gpt-4o-2024-08-06 banking
```

- `gpt-*`/`o1`/`o3` → OpenAI, `claude*` → Anthropic, `gemini*` → **Vertex AI**(GCP 프로젝트와 ADC 필요, 단순 API 키 아님), 그 외 → 로컬.
- 자동 판별을 무시하려면 `SECAGENT_POLICY_PROVIDER=local|openai|anthropic|gemini`.
- **에이전트 모델은 열거형이라 임의 값을 못 넣는다.** 지원 목록은 `python -m agentdojo.scripts.benchmark --help` 참고. 로컬 서버는 `qwen-local`(네이티브 툴콜) / `qwen-local-prompting`(프롬프트 기반) 두 별칭을 쓴다.

---

## 3. 환경변수 레퍼런스

### 모델·엔드포인트

| 변수 | 기본값 | 용도 |
|---|---|---|
| `LOCAL_BASE_URL` | `http://127.0.0.1:8000/v1` | 에이전트·정책 공용 엔드포인트 |
| `LOCAL_MODEL` | `Qwen/Qwen3-8B` | 에이전트 모델 id |
| `AGENT_MODEL` | `qwen-local` | 에이전트 별칭(`qwen-local-prompting`도 가능) |
| `SECAGENT_POLICY_MODEL` | `LOCAL_MODEL` | 정책 모델(전 단계 공통) — `run_sweep.sh` 2번째 인자가 설정 |
| `SECAGENT_POLICY_MODEL_{INIT,UPDATE_GATE,UPDATE_GEN}` | — | **단계별 개별 지정.** M4 하이브리드의 핵심 |
| `SECAGENT_POLICY_BASE_URL` | `LOCAL_BASE_URL` | 정책 모델만 다른 서버에 둘 때 |
| `SECAGENT_POLICY_PROVIDER` | 자동 판별 | 프로바이더 강제 |

### 정책 출력 통제

| 변수 | 기본값 | 용도 |
|---|---|---|
| `SECAGENT_JSON_MODE` | `True`(스크립트) | 정책 봉투 강제 on/off |
| `SECAGENT_STRUCTURED_MODE` | `auto` | `guided_json`(vLLM) / `json_schema` / `ollama_format` / `json_object` / `off`. `auto`는 서버에 직접 물어본다 |
| `SECAGENT_MAX_POLICY_TOKENS` | `4096` | 정책 응답 상한. 폭주 방지용 안전장치(§5-④) |
| `SECAGENT_SEND_SEED` | `True` | `seed`를 거부하는 서버면 `False` |

### 실행 범위·계측

| 변수 | 기본값 | 용도 |
|---|---|---|
| `USER_TASKS` | 전체 | 공백 구분 부분집합 (`user_task_0 user_task_1`) |
| `INJECTION_TASKS` | 전체 | 공백 구분 부분집합 |
| `HEAVY_MODEL` | — | `m4-hybrid`에서 `update_gen`이 쓸 상위 모델 (필수) |
| `SECAGENT_METRICS_PATH` | `metrics/<tag>.jsonl` | 계측 출력 |

---

## 4. 모드

| 모드 | 의미 |
|---|---|
| `m0-nodefense` | 무방어 기준선. **반드시 먼저 확보할 것** |
| `m1-init-only` | 초기 정책만, 갱신 없음 ≈ **Conseca 설계** |
| `m2-auto-deny` | 갱신하되 권한 확대는 전부 거부 |
| `m3-auto-approve` | Progent 논문 기본값(최악 가정) |
| `m4-hybrid` | **본 연구의 핵심 가설** — 신뢰 컨텍스트 단계만 경량 모델 |

`m4-hybrid`는 `init`·`update_gate`(둘 다 비신뢰 데이터를 보지 않는다)를 경량 모델에, 실제로 툴 결과를 읽는 `update_gen`만 상위 모델에 배정한다:

```bash
HEAVY_MODEL=Qwen/Qwen2.5-72B-Instruct \
  ./run_sweep.sh m4-hybrid Qwen/Qwen2.5-7B-Instruct banking slack
```

> 비용의 대부분이 갱신 단계에 있고(파일럿 실측 82%), 그중 비신뢰 데이터를 읽는 것은 `update_gen` 하나뿐이라는 비대칭이 이 구성의 근거다. 논문들은 한 모델로 전 단계를 일괄 교체하는 실험만 했다.

---

## 5. 이식 전 점검표 — 파일럿에서 밟은 함정 5개

**전부 조용히 실패한다.** 에러가 나지 않고 수치만 틀리므로, 새 환경에서는 반드시 하나씩 확인할 것.

### ① 구조화 출력이 "수용"됐다고 "강제"된 것이 아니다

OpenAI 호환 서버는 모르는 요청 필드를 **거부하지 않고 조용히 버린다.** 그래서 "호출이 성공했다"는 아무것도 증명하지 않는다. vLLM용 `guided_json`을 Ollama에 보내면 통과하지만 아무 제약도 걸리지 않는다.

```bash
python analysis/probe_models.py <policy-model>
```

프로브는 **스키마를 거스르는 프롬프트**(산문 한 문장으로 답하라)를 각 모드에 걸어, 그래도 봉투가 나오는지로 강제 여부를 판정한다. `enforced=YES`가 붙은 모드만 실제로 동작한다.

> 이걸 확인하지 않으면 작은 모델의 실패가 "형식을 못 맞춘 것"인지 "보안 추론을 못한 것"인지 영원히 구분되지 않는다. 이 연구의 존재 이유가 그 구분이다.

### ② 컨텍스트가 조용히 잘린다

banking 툴 스키마만 약 **1,213 토큰**이고 여기에 시스템 메시지·대화 이력·툴 결과가 누적된다. Ollama 기본 `num_ctx`는 4096이라 초과분이 경고 없이 잘린다 — 유틸리티 저하가 "모델이 약해서"인지 "프롬프트가 잘려서"인지 구분 불가능해진다.

- Ollama: `OLLAMA_CONTEXT_LENGTH=8192` 이상
- vLLM: `--max-model-len`이 충분한지 확인
- 확인: `ollama ps`의 `CONTEXT` 열, 또는 메트릭의 `prompt_tokens`가 상한에 붙어 있는지

### ③ 모델 스왑이 지연 측정을 통째로 오염시킨다

에이전트와 정책 모델이 VRAM에 동시 상주하지 못하면 호출마다 스왑이 일어나고, 단계별 지연이 **추론이 아니라 모델 로딩**을 재게 된다.

- Ollama: `OLLAMA_MAX_LOADED_MODELS=2`, 확인은 `ollama ps`에 둘 다 `100% GPU`로 뜨는지
- vLLM: 서버를 둘 띄우고 `SECAGENT_POLICY_BASE_URL`로 분리
- 증상: `init`/`update_gate` 지연 분포가 이봉(bimodal)

### ④ 단계마다 기대하는 출력이 다르다

`update_gate`는 **"Yes/No"를 답하는 단계**이고 정책을 만들지 않는다. 여기에 정책 스키마를 걸면 모델이 만족시킬 수 없는 형태를 채우려다 폭주한다 — 파일럿에서 0.5B가 한 번의 호출에 **81,920 토큰 / 265초**를 썼고, 하마터면 그게 "갱신 비용"으로 보고될 뻔했다.

하네스는 정책 생성 단계(`init`, `update_gen`)에만 제약을 걸고 모든 정책 호출에 `SECAGENT_MAX_POLICY_TOKENS` 상한을 둔다. **직접 프롬프트를 손볼 때 이 구분을 깨지 말 것.**

### ⑤ "무방어"를 끄는 스위치가 직관과 다르다

`ENABLE_SECAGENT=False`는 **LangChain 미들웨어만** 막는다. AgentDojo에서는 태스크 스위트가 툴을 래핑하고 `generate_security_policy`가 무조건 호출되므로, 이것만으로는 방어가 꺼지지 않는다.

`SECAGENT_GENERATE=False`만 주는 것도 안 된다 — 스위트가 설치하는 **always-allowed 목록**만 남아 송금 계열이 전부 차단되고, 유틸과 ASR이 함께 0으로 내려가 "완벽한 방어"처럼 보인다.

`run_sweep.sh`의 `m0-nodefense`가 `SECAGENT_SUITE`를 **주지 않는 것**(툴 래핑 자체를 막음)까지 처리한다. 직접 돌린다면 그대로 따를 것.

**검증**: 올바른 무방어 arm은 **정책 이벤트를 하나도 남기지 않는다.** `metrics/m0-*.jsonl` 파일이 아예 생기지 않으면 정상이다.

### (보너스) thinking 모델을 정책 생성기로 쓰지 말 것

Qwen3처럼 기본이 thinking인 모델은 정책 1건에 1,000토큰 이상을 쓴다(`qwen3:4b` 11.0s / 1,195토큰 vs `qwen2.5:7b` 0.4s / 31토큰 — **더 작은데 27배 느리다**). 스키마 제약은 `content`에만 걸려 thinking을 막지 못하고, Ollama의 `think=False`는 OpenAI 호환 `/v1`에서 무시된다. **크기 사다리를 만들 때는 전 구간이 같은 계열이어야 한다** — 안 그러면 "크기 효과"와 "thinking 여부"가 섞인다.

---

## 6. 하네스가 믿을 만한지 먼저 확인하기

새 환경의 절대 수치는 에이전트 모델에 따라 달라진다. 하지만 **비용 구조는 재현돼야 한다.** 아래 셋이 맞으면 계측을 신뢰해도 된다(8GB GPU 파일럿에서 모두 재현됨):

| 확인 항목 | 기대값 | 근거 |
|---|---|---|
| 갱신이 policy LLM 시간에서 차지하는 비중 | **약 82%** | Progent v1 §5.3 |
| 무방어 대비 총 실행시간 | **약 2.9~3.0배** | 13.25s / 4.50s |
| Z3 결정론 검사 | 툴 호출당 **1ms 미만** | 0.002s |

```bash
python analysis/pilot_summary.py          # arm별 유틸·ASR·단계별 비용
python analysis/summarize_metrics.py metrics/<tag>.jsonl --group stage --tasks N
python analysis/summarize_metrics.py metrics/ --group model,stage --csv results.csv
```

`pilot_summary.py`는 `parse_fail`(파싱 실패)과 `shape_fail`(형태 위반)을 함께 낸다. **0이 아니면 그 arm의 ASR에는 fail-open 편향이 섞여 있으므로 반드시 병기할 것.**

---

## 7. 규모 키우기

파일럿은 유저 5 + injection 2로 잘라 돌렸다. 더 좋은 환경이라면:

```bash
unset USER_TASKS INJECTION_TASKS          # 스위트 전체
./run_sweep.sh m3-auto-approve <policy> banking slack travel workspace
```

| 스위트 | 유저 태스크 | injection | 보안 런 |
|---|---|---|---|
| banking | 16 | 9 | 144 |
| slack | 17 | 5 | 85 |
| travel | 20 | 7 | 140 |
| workspace | 33 | 14 | 462 |

- `--max-workers`는 기본 1이다. **단일 GPU에서는 올리지 말 것** — 경합이 지연 측정을 무의미하게 만든다. API 백엔드라면 올려도 된다.
- 결과는 `logdir` 기준으로 캐시되므로 중단 후 재실행하면 이어서 돈다. 설정을 바꿨다면 해당 `logs/<tag>` 디렉터리를 **지우고** 다시 돌릴 것(안 그러면 옛 결과를 재사용한다).
- 논문은 단일 실행 수치만 보고한다. 최종 구성은 **3회 반복해 분산을 병기**할 것.

---

## 8. 트랙 2 — Conseca (`gemini-cli`)

논문 구현체가 아니라 Google이 실제로 출하한 구현체를 측정한다. Gemini 백엔드가 필요하다.

> **AgentDojo로 on/off 오버헤드를 재는 하네스는 [conseca/README.md](conseca/README.md)에 있다.** stock gemini-cli 0.59.0을 headless로 호출하고 AgentDojo 툴을 MCP 브리지로 꽂는 방식이며, 소스 패치 없이 텔레메트리만으로 계측한다. 아래는 정책·강제 모델을 바꾸기 위한 패치 버전 안내다.

`~/.gemini/settings.json`:

```json
{ "security": { "enableConseca": true } }
```

```bash
cd gemini-cli
export CONSECA_METRICS_PATH="$PWD/metrics/conseca.jsonl"
npm start -- --debug
```

| 구성 | 환경변수 |
|---|---|
| 기본(출하 상태) | 없음 — 생성·강제 모두 `gemini-2.5-flash` |
| 정책 모델 교체 | `CONSECA_POLICY_MODEL=<model>` |
| 강제기만 교체 | `CONSECA_ENFORCER_MODEL=<model>` |
| **결정론적 강제기(논문 설계)** | `CONSECA_ENFORCER=deterministic` |

결정론 모드는 생성기에게 `arg_constraints`(인자명 → 정규식)를 추가로 요구하고 강제를 LLM 호출 없이 평가한다 — **툴 호출당 LLM 1회가 통째로 사라진다.** 기본값은 출하 상태이므로 LLM 강제기 측정은 오염되지 않는다.

---

## 9. 지금까지의 결과

리포트 [§6](Policy_LLM_Overhead_Study.md)에 8GB GPU 파일럿 결과가 있다. 요약하면 **오버헤드 구조는 재현되지만**(갱신 82%, 3.0배, Z3 무료), Qwen2.5 0.5B·7B 정책 모델은 **툴의 JSON 스키마를 되받아쓸 뿐 제약을 쓰지 못해** ASR이 전혀 떨어지지 않았다(무방어 90% → 방어 100%, 유틸 71%→29%).

**더 좋은 환경에서 먼저 해볼 것**, 우선순위 순:

1. **더 큰 정책 모델** (32B~72B). 파일럿의 0.5B↔7B 차이가 없었으므로, 실패가 용량 문제인지 자체가 확인 대상이다.
2. **소수샷 예시를 넣은 프롬프트.** 올바른 `enum` 제약 vs 스키마 되받아쓰기를 보여주면 실패가 프롬프트 문제인지 능력 문제인지 갈린다. 이게 가장 저렴한 다음 수다.
3. **M4 하이브리드.** 위 둘로 정책 품질이 확보된 뒤라야 의미가 있다.
4. **gpt-4o 대조군.** 논문 수치(banking ASR 2.78%)를 재현해 하네스를 절대 기준으로 검증.
