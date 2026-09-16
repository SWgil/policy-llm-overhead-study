# AgentDojo 이후: 이 하네스에 쓸 수 있는 공격·벤치마크 후보

이 디렉터리는 두 질문에 답한다.

1. **왜 gemini-cli(gemini-3.5-flash)나 Qwen3.8-27B에서 AgentDojo ASR이 거의 0으로 나오는가.**
2. **그 대신(또는 그 위에) 무엇을 돌려야 Conseca on/off의 방어 효과 차이를 잴 수 있는가.**

각 후보는 별도 문서에 "분석 → 하네스 접점 → 적용 절차 → 비용 → 판단" 순으로 정리했다. 조사 시점은 2026-09-16이다.

| 문서 | 종류 | 하네스 변경량 | 한 줄 요약 |
|---|---|---|---|
| [autodojo.md](autodojo.md) | AgentDojo 위의 **적응형 공격** | 브리지 1곳 | 같은 스위트, 주입문만 LLM이 최적화한 것으로 교체. 1순위 |
| [agentdyn.md](agentdyn.md) | AgentDojo **확장 스위트** | 브리지 소스 교체 + 스위트 등록 | shopping/github/dailylife 60태스크·560주입, 과잉 방어(over-defense)도 잰다. 2순위 |
| [ipi-arena.md](ipi-arena.md) | 사람 레드팀 공격 데이터셋 | MCP 서버 신규 작성 | 41개 시나리오, 은폐 조건 포함. 공격문은 일부만 공개 |
| [dtap.md](dtap.md) | MCP 기반 레드팀 플랫폼 | 에이전트 백엔드 1개 작성 | 환경이 HTTP MCP 서버라 gemini-cli와 구조가 같다. 자율 레드팀 에이전트 포함 |
| [clawtrojan.md](clawtrojan.md) | 워크스페이스 **지속형 백도어** | 파일 툴 허용 + 어댑터 | GEMINI.md 같은 영속 상태를 공격. Conseca의 "프롬프트 기반 정책" 약점을 직접 찌른다 |
| [livepi.md](livepi.md) | 실제 VM·실계정 라이브 벤치마크 | Docker 러너에 gemini-cli 추가 | 위협 모델이 가장 현실적. 설치 비용이 가장 크다 |
| [rl-attackers.md](rl-attackers.md) | RL·반복 최적화 공격기 | GPU 학습 필요 | PISmith / IterInject / Learning to Inject. AutoDojo로 부족할 때 |

## 1. AgentDojo ASR이 낮게 나오는 이유

### 1.1 문헌: 정적 `important_instructions` 공격은 2025년 하반기 모델부터 거의 통하지 않는다

| 출처 | 조건 | 모델 | 무방어 ASR |
|---|---|---|---|
| Meta SecAlign 논문 Table 5 ([arXiv 2507.02735](https://arxiv.org/html/2507.02735)) | AgentDojo 전체 | GPT-4o / Gemini-2.5-Flash | 20.4% / 27.9% |
| 같은 표 | 같은 조건 | GPT-5 / Gemini-3-Pro | 0.2% / 2.3% |
| ClawTrojan 논문 ([arXiv 2605.31042](https://arxiv.org/html/2605.31042)) | 4개 스위트 부분집합 | GPT-5.4 | 0% (InjecAgent도 0%) |
| aiAuthZ 논문 ([arXiv 2607.05518](https://arxiv.org/html/2607.05518)) | banking, important_instructions, AgentDojo 0.1.35 | Gemini 3 Flash | 0% |
| IterInject 논문 ([arXiv 2605.24659](https://arxiv.org/html/2605.24659v1)) | AgentDojo 510 케이스 | Qwen3.5-27B | 26.3% (정적) → 32.4% (적응형) |

- ClawTrojan 논문은 "AgentDojo·InjecAgent는 GPT-5.4, GLM-5.1 같은 최신 모델에 무방어로도 거의 0"이라고 명시하고, 단일 컨텍스트 공격이 너무 쉬워졌다고 진단한다.
- aiAuthZ 논문은 이 하네스와 같은 조건(banking, important_instructions)에서 Gemini 3 Flash가 0%라 "방어가 개선 여지를 보여줄 수 없었다"고 기록했다.
- ["Indirect Prompt Injections: Are Firewalls All You Need, or Stronger Benchmarks?"](https://arxiv.org/html/2510.05244v1)는 단순 sanitizer만으로 GPT-4o ASR이 0.02%까지 떨어진다며, 이는 방어의 강함이 아니라 벤치마크 공격의 약함이라고 주장한다.
- Google 자체 논문 ["Lessons from Defending Gemini Against Indirect Prompt Injections"](https://arxiv.org/html/2505.14534)는 "정적 평가셋에서 잘 되는 방어가 작은 변형에 뚫린다"고 쓰고, 적응형 공격(TAP 등)으로 Gemini 2.5를 53.6~94.6%까지 뚫었다.
- ["The Attacker Moves Second"](https://arxiv.org/html/2510.09023)는 AgentDojo에서 정적 공격 1~2%인 방어들이 적응형 공격에는 90% 이상 뚫린다고 보고한다.

**결론**: gemini-3.5-flash에서 0 근처는 모델 수준의 저항이 맞다. 정적 공격을 유지하는 한 Conseca on/off 차이는 잴 수 없다.

### 1.2 Qwen 27B급은 다르다: 하네스 요인을 먼저 의심할 것

공개 수치상 Qwen3.5-27B는 정적 공격에도 26%가 나온다. 이 하네스에서 Qwen까지 0 근처라면 다음을 먼저 확인한다.

| 요인 | 위치 | 조치 |
|---|---|---|
| 모든 MCP 결과가 `<untrusted_context>`로 감싸임 | conseca/README.md "함정" 절 | `python patch_cli.py --apply`로 제거하고 양쪽 arm에 동일 적용 |
| 주입문의 호칭이 비-Gemini 모델에서 "the AI language model" | `run_task.py --attack-model-name` | 모델명(예: `Qwen`)을 명시 |
| banking 한 스위트, 스모크 1건 | `run_pilot.sh` | `--pilot` 이상, 스위트 4개 |
| AgentDojo 시스템 프롬프트가 gemini-cli 기본 프롬프트를 대체 | `GEMINI_SYSTEM_MD` | 원본 파이프라인과 같은 조건이므로 유지. 단 `--cli-prompt` 결과도 병기 |

## 2. 후보 비교

| 기준 | AutoDojo | AgentDyn | IPI Arena | DTap | ClawTrojan | LivePI |
|---|---|---|---|---|---|---|
| 공개 시점 | 2026-06 | 2026-02 | 2026-03 | 2026-05 | 2026-05 | 2026-05 |
| 라이선스 | MIT | MIT | MIT | Apache-2.0 | MIT | MIT (데이터 별도) |
| 최신 모델 무방어 ASR | Gemini-2.5-Flash 대상 캐시 공개. 필터 0%→28% | Meta SecAlign 1.9%→9.0% | Gemini 2.5 Pro 8.5%, Gemini 3 Pro 전이 16% | 논문 본문 참조 | GPT-5.4 95.5% | 10.7~29.6% |
| 환경 형태 | AgentDojo 파이썬 툴 | AgentDojo 파이썬 툴 | JSON 시나리오 + LLM 툴 시뮬레이터 | Docker + **HTTP MCP 서버** | 파일 워크스페이스 | 실제 VM + 실계정 |
| 기존 MCP 브리지 재사용 | 그대로 | 소스만 교체 | 불가 (신규 MCP 서버) | 불필요 (환경이 이미 MCP) | 부분 | 불가 |
| Conseca on/off 비교에 필요한 것 | 주입문 캐시 고정 | 없음 | 툴 시뮬레이터 결정론 | 없음 | 세션 간 상태 유지 | 없음 |
| 공격의 적응성 | 있음 (LLM 최적화) | 없음 (정적) | 있음 (사람) | 있음 (DTap-Red) | 없음 (다단계 고정) | 없음 |
| 예상 준비 기간 | 반나절(전이) / 며칠(직접 최적화) | 1~2일 | 3~5일 | 3~5일 | 1주 | 1~2주 + 계정 |

## 3. 공정한 arm 비교를 위한 공통 규칙

어느 후보를 쓰든 다음을 지켜야 "Conseca 효과"만 분리된다.

1. **공격은 arm과 무관하게 고정한다.** 적응형 공격을 쓸 때는 무방어(off arm)를 타깃으로 최적화한 결과를 양쪽 arm에 동일하게 재생한다.
2. **Conseca를 타깃으로 한 적응형 최적화는 별도 arm**("adaptive-vs-on")으로 보고한다. 논문 방식(defense-aware)이며, 비용이 off 대비 약 5배다.
3. **utility는 주입 없는 런과 주입 있는 런을 나눠 보고한다.** AgentDyn처럼 "따라야 하는 제3자 지시"가 있는 벤치마크에서는 과잉 방어(정당한 지시를 deny)가 utility 하락으로 잡힌다. Conseca 판정 로그(`conseca_verdicts`)에서 deny된 툴이 정답 경로였는지 대조한다.
4. **태스크 등급을 나눈다.** AutoDojo 논문 기준 fully-specified / param-open / action-open. action-open("TODO 파일에 있는 일 처리해줘")에서 ASR이 훨씬 높다. Conseca는 사용자 프롬프트에서 정책을 만들므로 action-open에서 정책이 느슨해질 가능성이 큰데, 이것이 이 연구의 핵심 가설이 될 수 있다.
5. **`fail-open` = 0을 매 런 확인한다.** 새 벤치마크에서 툴 이름·인자 형식이 달라지면 Conseca 판정기가 실패해 fail-open이 늘 수 있다.
6. **`<untrusted_context>` 태그 상태를 보고서에 명시한다.** 원본 논문 수치와 비교할 때 이 태그는 off arm에도 약한 방어로 작용한다.

## 4. 권장 순서

1. **AutoDojo 전이 캐시**로 banking·slack·travel을 다시 잰다. 브리지 수정 한 곳이면 된다. 이걸로 off arm ASR이 0을 벗어나면 그 위에서 Conseca on/off를 비교한다.
2. 그래도 0 근처면 **AutoDojo 직접 최적화**(gemini-cli를 타깃으로)로 간다.
3. 논문용 두 번째 벤치마크로 **AgentDyn**을 추가한다. 코드베이스가 같아 브리지를 그대로 쓰고, 과잉 방어 지표를 얻는다.
4. gemini-cli의 실제 위협 모델(파일 워크스페이스, GEMINI.md)을 다루고 싶으면 **ClawTrojan**, MCP 생태계 전체를 다루고 싶으면 **DTap**을 검토한다.
5. IPI Arena와 LivePI는 결과 해석 가치는 높지만 이 연구 범위(방어 비용 측정)에는 준비 비용이 과하다. 여유가 있을 때만.
