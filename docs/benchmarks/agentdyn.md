# AgentDyn: 동적·개방형 태스크로 확장한 AgentDojo

- 논문: [AgentDyn: Are Your Agent Security Defenses Deployable in Real-World Dynamic Environments?](https://arxiv.org/abs/2602.03117) (2026-02)
- 코드: <https://github.com/leolee99/AgentDyn> (MIT)
- 종류: AgentDojo 코드베이스 위에 **새 스위트 3개**를 얹은 벤치마크. 패키지 이름도 `agentdojo` 그대로다.

## 1. 분석

### 무엇이 다른가

AgentDojo의 세 가지 한계를 겨냥한다.

1. **동적·개방형 태스크.** 사용자 요청이 "쇼핑 목록 채워줘" 수준으로 열려 있어 에이전트가 계획을 세워야 한다. 정답 툴 시퀀스가 하나로 고정되지 않는다.
2. **따라야 하는 제3자 지시(helpful instructions).** 툴 결과에 정당한 지시(예: 판매자의 배송 안내)가 섞여 있고 이를 따라야 utility가 나온다. "툴 결과의 지시는 전부 무시"라는 방어는 여기서 utility를 잃는다. 즉 **과잉 방어(over-defense)** 를 잰다.
3. **단순하지 않은 사용자 태스크.**

규모: 새 스위트 `shopping`, `github`, `dailylife`에 60 사용자 태스크, 560 주입 케이스. 기존 `banking`, `slack`, `travel`, `workspace`도 그대로 들어 있다. `load_suites.py`는 7개 스위트를 v1, v1.1, v1.1.1, **v1.1.2**, v1.2, v1.2.1, v1.2.2 모든 버전 문자열에 등록한다.

내장 방어 9종: `repeat_user_prompt`, `spotlighting_with_delimiting`, `tool_filter`, `transformers_pi_detector`, `piguard_detector`, `prompt_guard_2_detector`, `camel`, `progent`, `drift`. 평가 모델: GPT-4o(-mini), Gemini 2.5 Flash/Pro, Llama 3.3 70B, Qwen3 235B, GPT-5.1, GPT-5-mini.

### 공개 수치

- Meta SecAlign 70B: AgentDojo 1.9% → AgentDyn 9.0% (4배 이상).
- 논문 요약: 10개 방어 중 거의 전부가 "충분히 안전하지 않거나" "과잉 방어가 심하다".
- 공격은 기본 `important_instructions` 정적 공격이다. 적응형 공격은 AutoDojo 포크가 AgentDyn 스위트도 지원한다([autodojo.md](autodojo.md)).

### 이 연구와의 궁합

- 장점: 코드베이스가 같아 브리지 REST/MCP를 그대로 쓴다. 과잉 방어 지표가 Conseca에 특히 중요하다. Conseca는 사용자 프롬프트에서 정책을 만들므로 "프롬프트에 없던 정당한 제3자 지시"를 deny할 가능성이 높고, 이것이 utility 비용으로 잡힌다.
- 단점: 공격이 정적이라 최신 모델에서는 여전히 ASR이 낮을 수 있다. AutoDojo와 겹쳐 쓰는 것이 자연스럽다.
- 주의: 개방형 태스크는 툴 호출 수가 많아 Conseca 판정 횟수(=지연·토큰)가 크게 늘어난다. 비용 측정 관점에서는 오히려 좋은 스트레스 테스트다.

## 2. 하네스 접점

| 하네스 파일 | 지금 | 바꿀 것 |
|---|---|---|
| `conseca/agentdojo-mcp/src/agentdojo/` | 0.1.29 기반 벤더링 | AgentDyn `src/agentdojo/`로 교체(또는 `pip install -e AgentDyn`로 대체 설치) |
| `conseca/agentdojo-mcp/mcp_server.py:52` | `get_suite("v1.1.2", suite)` | 그대로. AgentDyn도 v1.1.2에 새 스위트를 등록한다 |
| `conseca/run_task.py:56 SUITES` | 4개 스위트, (user 수, injection 목록) 하드코딩 | `shopping`, `github`, `dailylife` 추가. 개수는 아래 명령으로 뽑는다 |
| `conseca/settings.template.json` | MCP 서버 1개 | 그대로 |
| `conseca/agentdojo_system.md` | AgentDojo 기본 시스템 프롬프트 | AgentDyn이 시스템 프롬프트를 바꿨는지 확인(`agent_pipeline/` 비교). 바꿨으면 스위트별로 분기 |
| Conseca 판정기 | 툴 이름 `mcp_agentdojo_*` | 새 스위트 툴이 추가돼도 접두사는 같다. `fail-open`이 0인지 스모크에서 확인 |

스위트 크기 확인:

```bash
cd conseca && .venv/bin/python - <<'PY'
from agentdojo.task_suite.load_suites import get_suite
for s in ["shopping", "github", "dailylife"]:
    suite = get_suite("v1.1.2", s)
    print(s, len(suite.user_tasks), sorted(suite.injection_tasks))
PY
```

## 3. 적용 절차

1. 소스 교체.

```bash
git clone https://github.com/leolee99/AgentDyn /tmp/AgentDyn
# 벤더링 유지가 원칙이므로 복사한다. 원본과의 차이는 git diff로 남긴다.
rm -rf conseca/agentdojo-mcp/src/agentdojo
cp -r /tmp/AgentDyn/src/agentdojo conseca/agentdojo-mcp/src/agentdojo
# 기존 4개 스위트 데이터가 바뀌지 않았는지 확인
git diff --stat -- conseca/agentdojo-mcp/src/agentdojo/data conseca/agentdojo-mcp/src/agentdojo/default_suites
```

2. `pyproject.toml` 의존성 비교 후 `./setup.sh` 재실행.
3. `run_task.py`의 `SUITES`에 새 스위트를 추가한다. `--attack-model-name`은 그대로 `Gemini`.
4. 스모크: `SUITE=shopping ./run_pilot.sh --smoke`. `fail-open`, 429, 시스템 프롬프트 적용 여부를 확인한다.
5. 본 실험은 스위트 3개 × 양쪽 arm. 결과는 `results/agentdyn/`로 분리한다.
6. **과잉 방어 분석**: 주입 없는 런(`--injection-tasks none`)에서 on arm utility가 off보다 떨어진 태스크를 골라, `conseca_verdicts`에서 deny된 툴이 정답 경로에 있었는지 확인한다. 이것이 AgentDyn이 주는 추가 지표다.
7. (선택) AutoDojo 포크의 `variants/{shopping,github,dailylife}` 캐시가 있으면 [autodojo.md](autodojo.md) 경로 A로 적응형 공격까지 얹는다.

## 4. 비용 추정

| 항목 | 값 |
|---|---|
| 런 수 | 60 user × (1 + 스위트별 injection 수). 560 주입 케이스 + 60 무주입 ≈ 620 런/arm |
| 개방형 태스크 툴 호출 | AgentDojo 평균보다 많다. on arm에서 판정 호출이 비례해 늘어 런당 1~2분 예상 |
| 총 | off ≈ 620 × 15 s ≈ 2.6 h, on ≈ 620 × 90 s ≈ 15 h (429 재시도 제외) |

## 5. 판단

- **2순위, 논문용 두 번째 벤치마크.** 하네스 변경은 소스 교체와 스위트 등록뿐이다.
- 이 연구에 특별히 맞는 이유는 과잉 방어 지표다. "Conseca는 ASR을 낮추지만 정당한 제3자 지시를 막아 utility를 잃고 비용은 5배"라는 세 축을 한 벤치마크에서 보일 수 있다.
- 정적 공격이라 ASR 축은 여전히 약할 수 있으므로 AutoDojo와 함께 쓴다.
