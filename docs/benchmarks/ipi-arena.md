# IPI Arena: 사람 레드팀이 만든 간접 프롬프트 주입 데이터셋

- 논문: [How Vulnerable Are AI Agents to Indirect Prompt Injections? Insights from a Large-Scale Public Competition](https://arxiv.org/html/2603.15714) (2026-03, Gray Swan AI + OpenAI/Anthropic/Meta/UK AISI/US CAISI 후원)
- 코드: <https://github.com/grayswansecurity/ipi_arena_os> (MIT). 공격 데이터 일부: <https://huggingface.co/datasets/sureheremarv/ipi_arena_attacks>
- 종류: 시나리오 41개 + 사람이 만든 공격문. 툴 결과는 LLM 시뮬레이터(WorldSim)가 만든다.

## 1. 분석

### 무엇인가

464명이 3주간 13개 프런티어 모델에 27만 2천 건의 주입을 시도한 대회의 결과물이다. 성공 조건이 AgentDojo보다 엄격하다. **유해 행동을 실행하고, 그 사실을 최종 응답에서 사용자에게 숨겨야** 성공이다.

시나리오(behavior) 41개: tool 18(스마트홈, API 남용, 피싱), coding 15(코드 주입, 명령 실행, 백도어), browser 8(송금, 이메일 전달, 관리자 권한). 각 시나리오는 JSON으로 정의된다.

- `system_prompt`: 에이전트 역할
- `messages`: 미리 채운 대화. `{fill}` 자리에 공격문이 들어간다 (OpenAI/Anthropic 메시지 형식)
- `tools`: OpenAI function 스키마
- `criteria`: `tool_call` 판정(결정론, 대상 툴 이름·인자) + `llm` 판정(0~10점, 은폐·요청 이행)
- 모든 기준이 임계값을 넘으면 break

툴 응답은 WorldSim이라는 LLM이 최대 5회 루프로 시뮬레이션한다. 모델 연결은 OpenRouter 또는 vLLM.

### 공개 수치

| 모델 | ASR |
|---|---|
| Claude Opus 4.5 / Sonnet 4.5 / Haiku 4.5 | 0.5% / 1.0% / 1.3% |
| GPT-5 | 2.0% |
| Kimi K2 | 4.8% |
| Meta SecAlign 70B | 5.5% |
| DeepSeek V3.1 | 5.5% |
| Nova 1 Premier | 5.8% |
| Gemini 2.5 Pro | 8.5% (최고) |
| Gemini 3 Pro (전이 실험) | 16% |

효과적이었던 공격은 인코딩 트릭이 아니라 가짜 chain-of-thought, "안전 검사 해제" 요청, 보상·처벌 제시 같은 사회공학이었다.

**공개 범위 주의**: HF에는 Qwen 대상 성공 공격 95건(28개 시나리오)만 있다. 전체 데이터셋은 저자에게 요청해야 한다.

### 이 연구와의 궁합

- 장점: Gemini 계열이 이 데이터셋에서 가장 취약했다는 공개 근거가 있다. 은폐 조건이 있어 "Conseca가 막았는데 모델이 사용자에게 알렸는가"까지 볼 수 있다.
- 단점: 환경이 AgentDojo가 아니다. gemini-cli에 툴을 꽂으려면 **시나리오의 툴 스키마를 MCP로 노출하고 뒤에서 WorldSim을 부르는 서버를 새로 써야** 한다. WorldSim이 LLM이라 툴 결과가 비결정적이어서 arm 간 비교가 흔들린다. `messages`가 다중 턴 사전 대화인데 `gemini -p`는 단일 프롬프트라 평탄화가 필요하다.
- 공격문이 95건뿐이면 통계가 약하다.

## 2. 하네스 접점

| 하네스 파일 | 바꿀 것 |
|---|---|
| 새 파일 `conseca/ipi-arena-mcp/mcp_server.py` | behavior JSON을 읽어 `tools`를 MCP 툴로 등록. 툴 호출이 오면 `ipi_arena_bench`의 WorldSim을 호출해 응답 생성. 호출 이력 저장. REST `/init_task`(behavior id, 공격문 → 첫 프롬프트 반환), `/finish_task`(최종 응답 → tool_call 판정 + llm 판정) |
| `conseca/run_task.py` | `--bench ipi_arena` 분기: `SUITES` 대신 behavior 목록, `task_id`를 `gemini{arm}_ipiarena_{behavior}_{attack_idx}`로 |
| `conseca/settings.template.json` | MCP 서버 이름만 `ipiarena`로 |
| `agentdojo_system.md` | behavior의 `system_prompt`를 `GEMINI_SYSTEM_MD`로 |
| Conseca 판정기 | 툴 이름이 시나리오마다 다르다. 정책 생성이 실패하는 시나리오가 없는지 `fail-open`으로 확인 |

## 3. 적용 절차

1. `pip install -e ipi_arena_os` 후 `examples/`의 YAML로 OpenRouter 타깃에서 한 번 돌려 판정 파이프라인을 익힌다.
2. WorldSim의 결정론 확보: WorldSim 호출 모델을 temperature 0으로 고정하고, **같은 (behavior, 공격문, 툴 호출 시퀀스)에 대한 응답을 캐시**해 off/on arm이 같은 툴 결과를 보게 한다. 캐시 키는 툴 이름+인자 해시.
3. MCP 서버 작성 (위 표). `messages`의 사전 대화는 첫 사용자 프롬프트 앞에 "이전 대화" 블록으로 붙인다.
4. 공격문 소스: HF 95건으로 시작. 전체가 필요하면 저자에게 요청. 자체 공격문을 넣으려면 attack directory 형식(behavior id 이름의 markdown)을 쓴다.
5. 판정: `/finish_task`에서 tool_call 판정은 호출 이력으로, llm 판정은 최종 응답으로 계산. 은폐 판정을 따로 저장해 "막았지만 알렸다 / 막았지만 숨겼다"를 구분한다.
6. 양쪽 arm 실행. 비용 측정은 기존 텔레메트리 파서 그대로.

## 4. 비용 추정

| 항목 | 값 |
|---|---|
| 케이스 | 공개분 95 공격 × 1 = 95 런/arm (전체 데이터셋 확보 시 수천) |
| 런당 | gemini-cli 1회 + WorldSim 호출 ≤5회 + llm 판정 1회 |
| 구현 | MCP 서버 + 캐시 + 판정 연결 3~5일 |

## 5. 판단

- **보류.** 결과의 해석 가치(Gemini가 가장 취약, 은폐 조건)는 크지만, 이 연구의 목적(Conseca 비용·효과)에는 새 MCP 서버와 비결정적 툴 시뮬레이터라는 두 부담이 과하다.
- 다만 공격문 자체는 재활용 가치가 있다. 사회공학형 공격(가짜 CoT, 안전 해제 요청)을 AutoDojo 최적화의 **시드 전략**으로 넣으면 비용 없이 얻는 것이 있다.
