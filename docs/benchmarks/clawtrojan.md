# ClawTrojan: 워크스페이스에 심는 다단계 지속형 백도어

- 논문: [From Prompt Injection to Persistent Control: Defending Agentic Workspaces Against Trojan Backdoors](https://arxiv.org/html/2605.31042) (2026-05)
- 코드: <https://github.com/RUC-NLPIR/ClawTrojan> (MIT)
- 종류: 벤치마크 + 방어(DASGuard). 단일 턴 주입이 아니라 **심기 → 저장 → 나중 세션에서 발동** 시나리오.

## 1. 분석

### 무엇인가

로컬 에이전트 하네스(OpenClaw류: 파일 읽고 쓰고, 툴 부르고, 세션 간 워크스페이스 상태를 재사용)를 대상으로 한다. 공격은 궤적이다.

1. **Plant**: 파일이나 툴 결과에 지시가 들어온다.
2. **Store**: 에이전트가 그 지시를 워크스페이스 상태(메모, 설정, 스킬, 노트)에 옮겨 적는다.
3. **Trigger**: 이후 세션의 정상 요청이 저장된 지시를 발동시킨다.
4. **Outcome**: 되돌릴 수 없는 결과(문서 위조, 태스크 이탈, 비인가 공개 등).

각 환경은 표면 요청, 숨은 지시 위치, 공격 단계, "되돌릴 수 없는 결과 직전 단계" 여부를 기록한다. 지표는 단계별 ASR과 전체 체인 ASR. 저장소에는 `claw_trojan/`(샘플, 워크스페이스, 스킬, 프로필), `agent_eval/`(`agentdojo`, `dasguard`, `dti` 어댑터, `sandbox`, `judge.py`, `trojan_judge.py`, `simulator.py`, `pipeline.py`)이 있다.

### 공개 수치

- 같은 GPT-5.4가 AgentDojo·InjecAgent 단일 턴 공격에는 **0%**, ClawTrojan에는 **95.5%**.
- 이 논문이 "AgentDojo가 최신 모델에 안 통한다"는 근거의 출처이기도 하다([README.md](README.md) 1절).

### 이 연구와의 궁합

- **가설 적합도가 가장 높다.** Conseca는 *현재 사용자 프롬프트*에서 툴별 정책을 만든다. 백도어가 이전 세션에서 `GEMINI.md`나 메모 파일에 저장되고, 이번 세션의 정상 프롬프트가 그것을 발동시키면, 이번 프롬프트로 만든 정책은 발동된 행동을 "사용자 의도 밖"으로 볼 근거가 약하다. 즉 Conseca가 구조적으로 놓칠 수 있는 공격 유형이다. gemini-cli는 실제로 `GEMINI.md`를 매 세션 시스템 프롬프트에 붙이므로 저장 채널이 실재한다(conseca/README.md의 "실험 계정에서는 비워 둘 것" 경고가 바로 그 채널이다).
- 단점: 이 하네스는 gemini-cli 내장 파일 툴을 전부 `exclude`하고 MCP 툴만 허용한다. ClawTrojan은 파일 워크스페이스가 본체이므로 `read_file`, `write_file`, `replace` 등을 **허용**해야 하고, 그러면 Conseca 정책 대상에 내장 툴이 포함되어 지금까지의 비용 수치와 조건이 달라진다. 세션 간 상태를 유지하려면 `run_task.py`가 태스크당 워크스페이스를 새로 만드는 현재 구조를 "세션 시퀀스"로 바꿔야 한다.
- 어댑터 인터페이스가 README에 문서화되어 있지 않다. `agent_eval/pipeline.py`와 `agentdojo/` 어댑터 소스를 읽어야 한다.

## 2. 하네스 접점

| 하네스 파일 | 지금 | 바꿀 것 |
|---|---|---|
| `conseca/settings.template.json` `tools.exclude` | 파일·셸 툴 전부 차단 | ClawTrojan arm에서는 `read_file`, `write_file`, `replace`, `list_directory`, `glob`, `grep_search` 허용. `run_shell_command`는 시나리오가 요구할 때만 |
| `conseca/run_task.py` | 태스크 = 워크스페이스 1개, gemini 1회 | `--bench clawtrojan`: 샘플의 세션 시퀀스를 같은 워크스페이스에서 순서대로 실행. 세션 사이에 `GEMINI.md`·메모 파일이 남도록 워크스페이스를 지우지 않음 |
| `GEMINI_SYSTEM_MD` | AgentDojo 프롬프트 | 사용 안 함. gemini-cli 기본 프롬프트 + 워크스페이스 `GEMINI.md`가 곧 저장 채널이므로 `--cli-prompt` 모드 |
| 새 어댑터 `agent_eval/geminicli/` (ClawTrojan 쪽) | `agentdojo/`, `dti/` 어댑터 참고 | 세션마다 gemini-cli 실행, 워크스페이스 파일 변경과 툴 호출을 `protocol.py` 형식으로 반환 |
| 판정 | `trojan_judge.py` | 단계별 ASR(저장 성공, 발동 성공)과 전체 체인 ASR을 `security`에 매핑. 되돌릴 수 없는 단계 직전에 Conseca가 deny했는지를 `conseca_verdicts`와 대조 |
| 텔레메트리 | 세션 1개 | 세션별로 나눠 저장. 비용은 체인 합계와 세션 평균 둘 다 보고 |

## 3. 적용 절차

1. 저장소 설치와 스모크.

```bash
git clone https://github.com/RUC-NLPIR/ClawTrojan /tmp/clawtrojan && cd /tmp/clawtrojan
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && cp .env.example .env
# README의 라벨 내보내기 + DASGuard 로컬 스모크로 판정 파이프라인 확인
```

2. `agent_eval/pipeline.py`, `protocol.py`, `agentdojo/` 어댑터를 읽고 어댑터 계약(입력: 워크스페이스 경로 + 세션 프롬프트, 출력: 응답 + 툴 호출 + 파일 변경)을 확정한다.
3. gemini-cli 어댑터 작성. 본문은 `conseca/run_task.py`의 `run_gemini`를 옮기되, 워크스페이스를 재사용하고 `GEMINI.md`를 지우지 않는다.
4. `settings.template.json`을 ClawTrojan용으로 분기(파일 툴 허용). **이 설정 변경은 AgentDojo 실험과 비용 조건이 다르므로 보고서에 별도 절로 쓴다.**
5. 샘플 몇 개로 off arm 체인을 돌려 저장 단계가 실제로 `GEMINI.md`나 메모에 남는지 확인한다. 남지 않으면 gemini-cli의 메모리 저장 툴(`save_memory`류)이 exclude에 있는지 본다.
6. 양쪽 arm 실행. 보고 지표: 단계별 ASR, 체인 ASR, "되돌릴 수 없는 단계에서 Conseca deny 여부", 세션당 비용.
7. (선택) DASGuard를 세 번째 arm으로 두면 Conseca와 하네스 경계 방어를 비교할 수 있다.

## 4. 비용 추정

| 항목 | 값 |
|---|---|
| 샘플 수 | README에 명시 없음. 저장소 `claw_trojan/`에서 확인 |
| 런당 | 세션 2~4회 × gemini-cli. on arm은 세션마다 정책 생성 |
| 구현 | 어댑터 + 세션 시퀀스 러너 + 설정 분기 약 1주 |

## 5. 판단

- **이 연구에서 가장 흥미로운 결과가 나올 수 있는 후보.** "프롬프트 기반 정책 생성은 세션 간 지속 공격을 구조적으로 놓친다"가 확인되면 Conseca 비용 논의에 질적 한계를 더한다.
- 대신 조건이 달라진다(내장 파일 툴 허용, 다중 세션). AgentDojo 계열 결과와 같은 표에 넣지 말고 별도 실험으로 다룬다.
- 어댑터 계약을 소스에서 확인해야 하므로 착수 전에 하루 정도 코드 읽기가 필요하다.
