# AutoDojo: AgentDojo 위의 적응형 블랙박스 공격

- 논문: [AutoDojo: Adaptive Black-Box Attacks Reveal the Limits of IPI Defenses and Task-Specification Effects in LLM Agents](https://arxiv.org/html/2606.15057) (2026-06)
- 코드: <https://github.com/xhOwenMa/AutoDojo> (MIT)
- 종류: **벤치마크가 아니라 공격**. AgentDojo(+AgentDyn) 스위트를 그대로 쓰고 주입문만 바꾼다.

## 1. 분석

### 무엇을 하는가

두 단계로 나뉜다.

1. **오프라인 최적화** (`agentdojo/variant_generation/optimize_variants.py`). 최적화 LLM(논문은 Gemini 3.1 Pro, OpenRouter 경유)이 (injection_task × 주입 벡터) 셀마다 주입문 후보를 만들고, 타깃 에이전트에 실제로 돌려 **성공/실패 신호만** 피드백으로 받아 다시 쓴다. 논문은 셀당 최대 6회 반복, 상위 5개 후보 리더보드. README 기본값은 `--iterations 8 --n-variants 5`.
2. **벤치마크 시 재생** (`attacks/autodojo_attack.py`). `AUTODOJO_CACHE`가 가리키는 `injections.json`에서 변형을 읽어 그 텍스트를 주입 벡터에 넣는다. 변형이 원본과 같으면 `important_instructions` 템플릿으로 감싸 정적 공격과 동일하게 동작한다.

캐시 스키마:

```json
{
  "suite": "banking",
  "n_variants": 5,
  "injection_tasks": {
    "injection_task_0": {
      "<vector_id>": {
        "original": "<원래 GOAL 문장>",
        "variants": ["<ASR 순 상위 변형 1>", "..."],
        "trajectory": [{"text": "...", "asr": 0.75, "iteration": 0}]
      }
    }
  }
}
```

캐시 경로 규칙: `variants/{suite}/{model}/{defense}/injections.json`. 저장소에 **banking·slack·travel × {openai/*, google/gemini-2.5-flash, anthropic/claude-haiku-4.5, deepseek/deepseek-v4-flash} × 10개 방어(no_defense 포함)** 조합이 커밋되어 있다. workspace 스위트는 없다.

### "전이 캐시"란

저자들이 **이미 만들어 커밋해 둔** `injections.json`을 말한다. 최적화 LLM(`google/gemini-3.1-pro-preview`)이 gemini-2.5-flash 무방어 에이전트를 타깃으로 6회 반복해 얻은 주입문이며, 다운로드해서 그대로 쓰면 된다. 별도 생성 작업은 없다. 다만 타깃이 gemini-2.5-flash였으므로 gemini-3.5-flash에 쓰면 "다른 모델용으로 최적화된 공격을 옮겨 쓰는" 전이 공격이 된다. 이 하네스의 모델을 타깃으로 새로 만드는 것이 아래 경로 B다.

공개 캐시의 실제 범위(2026-09-16, 파일을 내려받아 확인. `google/gemini-2.5-flash/no_defense`, 최적화 LLM `google/gemini-3.1-pro-preview`, 6회 반복, 변형 5개):

| 스위트 | 포함된 injection_task | 벡터 수 | 벡터 id가 번들 스위트(v1.1.2)와 일치 | variant 0이 최적화된 (user, injection) 쌍 |
|---|---|---|---|---|
| banking | 0~8 (전체) | 4 | 일치 | 120 / 144 |
| slack | 1~5 (전체) | 5 | 일치 | 105 / 105 |
| travel | 0~6 (전체) | 13 | 일치 | 140 / 140 |

즉 세 스위트의 **모든 injection_task**가 들어 있다. 다만 banking의 일부 셀은 최적화기가 정적 래퍼를 이기지 못해 `variants[0]`이 `original`과 같고, 이 경우 `autodojo_attack.py`가 `important_instructions` 래퍼로 후퇴한다. 사용자 태스크가 읽는 벡터가 전부 이런 셀이면 그 런은 정적 공격과 동일하므로, 이 저장소의 `run_task.py`는 기본적으로 건너뛴다(`--include-unoptimized`로 포함). banking에서는 24쌍이 여기에 해당하고, 특히 `user_task_0 × injection_task_0`(기존 스모크 쌍)이 그렇다.

## 2. 하네스 접점

| 하네스 파일 | 지금 | 바꿀 것 |
|---|---|---|
| `conseca/agentdojo-mcp/mcp_server.py:61` | `ImportantInstructionsAttack(...).attack(user_task, injection_task)` | attack 종류에 따라 캐시에서 `{vector_id: text}` 딕셔너리 생성 |
| `InitTaskRequest` | `attack_model_name`만 | `attack: str = "important_instructions"`, `attack_cache: str | None`, `attack_variant: int = 0` 추가 |
| `conseca/run_task.py` | `--attack-model-name` | `--attack {important_instructions,autodojo}`, `--attack-cache`, `--attack-variant` 추가해 `/init_task`에 전달 |
| `conseca/run_task.py task_id_for` | `gemini{arm}_{suite}_{ut}_{it}` | 결과 디렉터리를 공격별로 분리 (`--out results/autodojo` 등). task_id 정규식은 브리지가 파싱하므로 바꾸지 않는다 |
| `conseca/compare_arms.py` | arm별 표 | `--attack` 열 추가 (선택) |

브리지 쪽 핵심 로직(의사 코드):

```python
# mcp_server.py, ImportantInstructionsAttack 분기 옆
attack = ImportantInstructionsAttack(task_suite, BasePipelineElement)
if request.attack_model_name:
    attack.model_name = request.attack_model_name
if request.attack == "autodojo":
    cache = json.load(open(request.attack_cache))
    cell = cache["injection_tasks"].get(request.injection_task_id, {})
    task_injections = {}
    for vec in attack.get_injection_candidates(user_task):
        variants = cell.get(vec, {}).get("variants", [])
        text = variants[request.attack_variant] if len(variants) > request.attack_variant else None
        if text is None or text == cell.get(vec, {}).get("original"):
            # 최적화 개선이 없던 셀은 원본과 같이 important_instructions로 감싼다
            task_injections[vec] = attack.attack(user_task, injection_task)[vec]
        else:
            task_injections[vec] = yaml_escape(text)   # 원본 attack()과 같은 YAML 이스케이프
else:
    task_injections = attack.attack(user_task, injection_task)
```

`yaml_escape`는 AutoDojo `autodojo_attack.py`의 것을 그대로 옮긴다(줄바꿈·따옴표·역슬래시). 이 하네스는 툴 결과를 `tool_result_to_str` YAML로 내보내므로 이스케이프를 빼면 주입문이 깨진다.

## 3. 적용 절차

**경로 A는 `autodojo-only` 브랜치에 구현되어 있다.** 캐시 세 개가 `conseca/attacks/autodojo/<suite>/injections.json`에 동봉되어 있고 `run_task.py`의 기본 공격이 `autodojo`다. 아래는 그 구현이 한 일이다.

### 경로 A: 공개 캐시 전이 재생 (반나절)

```bash
git clone https://github.com/xhOwenMa/AutoDojo /tmp/AutoDojo
mkdir -p conseca/attacks/autodojo
cp -r /tmp/AutoDojo/agentdojo/variant_generation/variants/{banking,slack,travel} conseca/attacks/autodojo/
```

1. 위 브리지 패치와 `run_task.py` 옵션을 넣는다.
2. 스위트 데이터 일치 확인: 두 소스 트리의 `default_suites/v1_1_2` (또는 해당 버전) 스위트 파일과 `injection_tasks`의 vector_id 집합을 비교한다. 다르면 `agentdojo-mcp/src/agentdojo`를 AutoDojo 포크로 교체한다(스위트 등록 버전 문자열은 `load_suites.py`에서 확인).
3. 스모크:

```bash
cd conseca
CACHE=attacks/autodojo/banking/google/gemini-2.5-flash/no_defense/injections.json
for arm in off on; do
  .venv/bin/python run_task.py --arm $arm --suite banking --model gemini-3.5-flash \
    --attack autodojo --attack-cache $CACHE --attack-variant 0 \
    --user-tasks user_task_0 --injection-tasks injection_task_0 --out results/autodojo
done
.venv/bin/python compare_arms.py --suite banking --out results/autodojo
```

4. `--attack-variant 0..4`를 모두 돌려 셀당 최고 ASR(ASR@5)과 variant 0 단독(ASR@1)을 둘 다 보고한다. 논문의 ASR은 최적화 타깃에 대한 값이므로 전이에서는 ASR@k가 더 공정하다.
5. 같은 캐시를 **양쪽 arm에 동일하게** 쓴다. 캐시는 무방어 gemini-2.5-flash 타깃이므로 이 조건은 자동으로 만족한다.

### 경로 B: gemini-cli를 타깃으로 직접 최적화 (며칠)

`optimize_variants.py`의 `DojoASREvaluator`는 in-process `AgentPipeline`을 만들어 `pipeline.query()`를 부르고 `security` 불리언만 쓴다. 이 부분을 이 하네스의 `run_one()` 호출로 바꾼다.

1. `DojoASREvaluator._eval_single(user_task, injection_task, injection_text)`를 다음으로 대체한다.
   - `/init_task`에 `attack="literal"`, `attack_injections={vector_id: injection_text}`를 넘기는 REST 필드를 브리지에 추가 (경로 A의 확장).
   - `run_task.run_one(...)`을 호출하고 `result["security"]`를 반환.
   - `classify_failure()`가 쓰는 툴 호출 이력은 브리지가 `mcp_results/<agent>/<suite>/<user_task>/<injection_task>.json`에 남기므로 그 파일에서 `functions_stack_trace`를 읽어 넘긴다.
2. reachability 필터는 무방어 파이프라인으로 돈다. off arm(`--arm off`)을 쓰면 된다.
3. 실행:

```bash
cp .env.example .env    # OPENROUTER_API_KEY (최적화·분석 LLM), 타깃은 gemini-cli라 불필요
python agentdojo/variant_generation/optimize_variants.py \
  --suite banking --n-variants 5 --iterations 8 --eval-asr \
  --target-model gemini_cli --target-model-id gemini-3.5-flash \
  --analyzer-prompt analyzer_banking \
  --injection-prompt injection_task_iterative_banking
```

4. 생성된 `variants/banking/gemini_cli/gemini-3.5-flash/no_defense/injections.json`을 경로 A와 같은 방식으로 양쪽 arm에 재생한다.
5. (선택) `--defense conseca --run-defense`에 해당하는 것은 `--arm on`을 타깃으로 최적화하는 것이다. 결과는 별도 arm "adaptive-vs-on"으로 보고한다.

## 4. 비용 추정

| 항목 | 값 | 근거 |
|---|---|---|
| gemini-cli 1회 (off, banking) | 약 10 s, 입력 5k 토큰 | conseca/README.md 6절 |
| gemini-cli 1회 (on) | 약 53 s, 입력 33k 토큰 | 같은 곳 |
| banking 정적 전이 재생 (경로 A, 1 variant) | 16 user × 9 injection = 144 런/arm | `run_task.py SUITES` |
| 경로 A, 5 variants, 양쪽 arm | 144 × 5 × (10 s + 53 s) ≈ 12.6 h | 위 합산 |
| 경로 B 최적화 (off 타깃) | 반복 8 × 셀 수 × 셀당 user_task 수 × 10 s. banking에서 수백~천 회, 3~4 h | 논문 389 케이스 총량 기준 |
| 최적화 LLM | `run_cost.json`에 OpenRouter 비용 자동 기록 | README |

`--parallel-eval`은 상태 없는 방어 전용이라 gemini-cli 타깃에는 쓰지 말 것(MCP 서버가 task_id별 환경을 들고 있으므로 병렬 자체는 가능하지만 429 재시도가 늘어 비용 측정이 오염된다).

## 5. 판단

- **1순위.** 하네스 변경이 가장 적고, Conseca 효과 측정에 필요한 "0이 아닌 off arm ASR"을 가장 싸게 얻는다.
- 전이 캐시로도 0에 머물면 그것 자체가 "Gemini 3.5 세대는 LLM 최적화 전이 공격에도 저항한다"는 결과이며, 경로 B로 넘어간다.
- 논문이 시스템 수준 방어(Progent, DRIFT)는 적응형 공격에도 버틴다고 보고했으므로, Conseca가 같은 결과를 내면 "방어 효과는 유지되는데 비용은 5배"라는 이 연구의 서사와 맞는다.
