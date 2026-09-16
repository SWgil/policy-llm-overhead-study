# RL·반복 최적화 공격기: PISmith, IterInject, Learning to Inject

AutoDojo([autodojo.md](autodojo.md))로도 off arm ASR이 0 근처에 머물 때 쓸 수 있는 더 강한 공격원이다. 셋 다 **AgentDojo 스위트를 그대로 쓰고 주입문만 바꾼다**는 점에서 하네스 접점은 AutoDojo와 같다(브리지 `/init_task`에 주입문을 넘기는 `attack="literal"` 경로). 차이는 공격문을 만드는 비용이다.

## PISmith

- 논문: [PISmith: Reinforcement Learning-based Red Teaming for Prompt Injection Defenses](https://arxiv.org/html/2603.13026) (COLM 2026)
- 코드: <https://github.com/albert-y1n/PISmith> (MIT)
- 방식: 공격자 LLM을 RL로 학습. 13개 데이터셋(QA, RAG, 장문) + InjecAgent + AgentDojo/AgentDyn. 타깃은 로컬 vLLM 또는 API(GPT-4o-mini 등 블랙박스 지원).
- 수치: Meta-SecAlign-8B 정적 0.04~0.07 → 0.87. InjecAgent GPT-5-nano 정적 0.00 → 0.95.
- 요구: Python 3.10, CUDA 12.9, GPU. **사전 학습된 공격자 체크포인트는 공개되지 않아 직접 학습해야 한다.**
- 적용: `scripts/eval_agentdojo.sh <checkpoint> <target>`이 API 타깃을 지원하므로, gemini-cli를 타깃으로 하려면 타깃 호출부를 이 하네스의 `run_one()`으로 바꾼다. 학습 중 타깃 호출이 수천 회라 gemini-cli 직접 타깃은 비현실적이다. 현실적 경로는 **API gemini-3.5-flash(원본 AgentDojo 파이프라인)를 타깃으로 학습한 뒤 gemini-cli에 전이**.

## IterInject

- 논문: [IterInject: Indirect Prompt Injection Against LLM Agents via Feedback-Guided Iterative Optimization](https://arxiv.org/html/2605.24659v1) (2026-05)
- 코드: 논문은 공개한다고 밝히나 URL을 확인하지 못했다. 저자 연락 필요.
- 방식: 규칙 기반 진단기가 실패 원인을 구조화된 라벨로 내고, LLM 최적화기가 전체 이력을 보며 주입문을 고친다. AutoDojo와 같은 계열이되 피드백이 더 풍부하다.
- 수치(AgentDojo 510 케이스):

| 모델 | 정적 | IterInject |
|---|---|---|
| GLM-5.1 | 11.6% | 17.5% |
| MiniMax-M2.7 | 16.1% | 26.5% |
| DeepSeek-V4-Flash | 32.9% | 47.8% |
| Qwen3.5-27B | 26.3% | 32.4% |

- 이 표가 **Qwen 27B급은 정적 공격에도 26%**라는 근거다. 이 하네스에서 Qwen ASR이 0 근처면 하네스 요인을 먼저 본다([README.md](README.md) 1.2절).
- Claude Code 확장 실험(§6.4)이 있어 CLI 에이전트 타깃 사례가 있다.

## Learning to Inject (AutoInject)

- 논문: [Learning to Inject: Automated Prompt Injection via Reinforcement Learning](https://arxiv.org/abs/2602.05746) (2026-02)
- 코드: URL 확인 못 함.
- 방식: RL로 학습한 접미사(suffix). AgentDojo에서 템플릿 공격, GCG, TAP, 적응형 탐색을 모두 이기고 Meta-SecAlign-70B도 뚫는다(McNemar p<0.05).
- 적용: 학습된 접미사가 공개되면 `important_instructions` 주입문 뒤에 붙이는 것만으로 쓸 수 있다. 공개 전에는 사용 불가.

## 참고: 논문들이 이미 보고한 "정적 vs 적응형" 격차

| 출처 | 조건 | 정적 | 적응형 |
|---|---|---|---|
| The Attacker Moves Second ([2510.09023](https://arxiv.org/html/2510.09023)) | AgentDojo, Spotlighting/Sandwich/MetaSecAlign | 1~2% | >95% |
| 같은 논문 | MELON | – | 76% (방어 미지) / 95% (방어 기지) |
| Google Lessons ([2505.14534](https://arxiv.org/html/2505.14534)) | Gemini 2.5, 이메일 유출 시나리오 | – | TAP 53.6%, Actor-Critic 40.8% |
| AutoDojo ([2606.15057](https://arxiv.org/html/2606.15057)) | PIGuard, GPT-4o-mini | 0% | 28% |
| PISmith | InjecAgent, GPT-5-nano | 0% | 95% |

## 판단

- AutoDojo 경로 B(직접 최적화)가 먼저다. RL 공격기는 GPU와 학습 시간이 들고 체크포인트가 없다.
- Qwen 실험을 계속한다면 IterInject 표가 직접 비교 대상이므로, 코드가 공개되면 우선 검토한다.
