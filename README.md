# policy-llm-overhead-study

정책 강제(policy enforcing) 계열 IPI 방어 — **Progent**와 **Conseca** — 에서 정책 생성기 LLM이 차지하는 실제 비용을 재고, 경량 모델로 대체할 수 있는지 판정하는 스터디. 문헌 조사 3편과 실측 하네스 2개로 이루어져 있다.

## 바로 돌리기

새 환경에서 받아 바로 측정할 수 있는 것은 **Conseca 트랙**이다. Gemini 인증만 있으면 된다.

```bash
cd conseca
export GEMINI_API_KEY=...
./setup.sh                  # gemini-cli 0.59.0 + Python venv + AgentDojo 브리지
./run_pilot.sh --smoke      # 태스크 1개 × Conseca off/on, 비교표까지 출력
```

전체 절차·분석 방법·함정은 [conseca/README.md](conseca/README.md).

## 구성

| 경로 | 내용 |
|---|---|
| [`conseca/`](conseca/README.md) | **트랙 2 하네스.** stock gemini-cli를 headless로 호출해 AgentDojo에서 Conseca on/off 비용과 방어 효과를 잰다. 세팅·실행·분석 스크립트 포함 |
| [`EXPERIMENT_README.md`](EXPERIMENT_README.md) | **트랙 1 하네스 안내.** Progent의 정책 LLM을 단계별로 계측하고 단계마다 다른 모델을 배정하는 실험. 코드는 별도 저장소 [progent-policy-overhead](https://github.com/SWgil/progent-policy-overhead)에 있고 로컬/호스티드 LLM 엔드포인트가 필요하다 |
| [`Policy_LLM_Overhead_Study.md`](Policy_LLM_Overhead_Study.md) | 본 스터디 리포트. 문제 정의, 두 설계의 오버헤드 분해, 파일럿 결과(§6), 권고(§7) |
| [`IPI_LLM_Defense_Survey.md`](IPI_LLM_Defense_Survey.md) | 선행 조사: LLM 기반 IPI 방어 기법 전반 |
| [`IPI_Defense_Rebuttals.md`](IPI_Defense_Rebuttals.md) | 선행 조사: 위 추천 기법에 대한 반박 논문 정리 |

두 하네스는 독립적이다. Conseca 트랙은 이 저장소만으로 돈다. Progent 트랙은 `progent/`에 위 저장소를 클론해 두고 EXPERIMENT_README를 따른다(`progent/`와 `gemini-cli/`는 git 제외).
