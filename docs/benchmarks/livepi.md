# LivePI: 실제 VM과 실계정으로 도는 라이브 벤치마크

- 논문: [LivePI: More Realistic Benchmarking of Agents Against Indirect Prompt Injection](https://arxiv.org/abs/2605.17986) (2026-05)
- 코드: <https://github.com/leizhao7/livepi> (코드 MIT, 데이터 `LICENSE-DATA` 별도). 사이트: <https://leizhao7.github.io/livepi/>
- 종류: 실제 VM + 라이브(테스트 통제) 채널. 시뮬레이션이 아니다.

## 1. 분석

### 무엇인가

에이전트가 실제 Gmail, Slack, Telegram, WhatsApp, 로컬 문서, 저장소 링크, Gist 등 **7개 입력 표면**에서 주입을 받는다. 공격 렌더링 12종, 악성 목표 5종(보호 정보 유출, 보안 설정 변경, 안전하지 않은 코드 실행, 받은편지함 요약 유출, 암호화폐 송금). 모델당 실행 가능한 케이스 169개.

지원 하네스: OpenClaw, Hermes(Nous), Codex CLI, Claude Code. `--agent <name>`으로 선택하고 `scripts/run_in_docker.sh`가 실행을 추상화한다. 모델은 `--base-model`로 OpenRouter 경유.

요구 사항: Ubuntu 24.04+, Docker, Python 3.10+, `secrets.env`에 Gmail·Slack·Telegram·WhatsApp·Solana 지갑·GitHub·API 키. 원격 VPS 배포 옵션.

### 공개 수치

| 모델 | 총 ASR |
|---|---|
| GPT-5.3-Codex | 10.7% (최저) |
| Claude Opus 4.6, Gemini 3.1 Pro, Kimi K2.5 | 그 사이 |
| GLM-5 | 29.6% (최고) |

### 이 연구와의 궁합

- 장점: **gemini-cli의 실제 사용 위협 모델과 가장 가깝다.** 다른 CLI 에이전트(Codex CLI, Claude Code)가 이미 하네스로 들어가 있어 gemini-cli 추가는 같은 틀에 맞추면 된다. Conseca가 실제 툴(Gmail MCP, 파일, 셸)에서 어떻게 동작하는지 볼 수 있다.
- 단점: 실계정과 지갑이 필요하다. 비용 측정에는 네트워크·서비스 지연이 섞여 Conseca 지연을 분리하기 어렵다. 케이스마다 외부 상태를 초기화해야 재현이 된다. 라이브 채널은 arm 간 동일 조건을 보장하기 어렵다.
- 이 저장소의 AgentDojo 브리지와 공유하는 코드가 없다. 텔레메트리 파서만 재사용된다.

## 2. 하네스 접점

| 위치 | 바꿀 것 |
|---|---|
| LivePI `--agent geminicli` (신규) | Codex CLI / Claude Code 러너를 본떠 gemini-cli 설치·실행 스크립트 작성. Conseca on/off는 컨테이너 안 `~/.gemini/settings.json`로 |
| gemini-cli 툴 | LivePI가 요구하는 채널(Gmail, Slack 등)을 gemini-cli에 어떻게 노출할지 결정. LivePI가 하네스별로 어떻게 연결하는지 저장소에서 확인 필요(MCP 서버인지, 셸 도구인지) |
| `conseca/parse_telemetry.py` | 컨테이너 밖으로 텔레메트리 파일을 꺼내 그대로 사용 |
| 비용 지표 | 벽시계 대신 **텔레메트리의 `conseca ms`와 토큰**을 1차 지표로. 외부 서비스 지연은 분리 불가 |

## 3. 적용 절차

1. 저장소를 읽어 Codex CLI 러너가 채널을 어떻게 붙이는지 파악한다(MCP면 gemini-cli도 같은 설정으로 붙는다).
2. 테스트 계정 준비: 실험 전용 Gmail, Slack 워크스페이스, Telegram/WhatsApp 번호, 소액 Solana 지갑, GitHub 저장소. **실사용 계정을 쓰지 않는다.**
3. `--agent geminicli` 러너 작성, `secrets.env` 채우기, `scripts/run_in_docker.sh`로 케이스 1개 스모크.
4. 케이스 간 외부 상태 초기화 스크립트(받은편지함 비우기, 지갑 잔액 확인 등)를 확인하고 없으면 추가한다.
5. 양쪽 arm 실행. 케이스 169 × 2. 시간대·서비스 상태에 따른 편차를 줄이려면 arm을 케이스 단위로 교차(off, on, off, on)한다.
6. 보고: 목표별·표면별 ASR, Conseca deny 위치, 텔레메트리 기반 비용.

## 4. 비용 추정

| 항목 | 값 |
|---|---|
| 준비 | 계정·지갑·Docker·러너 작성 1~2주 |
| 런당 | 실서비스 왕복 포함 수 분. on arm은 툴 수에 따라 정책 생성이 커짐 |
| 총 | 169 × 2 arm × 수 분 ≈ 1~2일 실행 |

## 5. 판단

- **가장 현실적이지만 이 연구 범위에서는 마지막 순위.** 비용 측정의 통제 조건(결정론, 동일 입력)을 라이브 환경이 깨뜨린다.
- "AgentDojo에서 잰 Conseca 비용이 실제 도구 환경에서도 유지되는가"를 묻는 후속 연구 소재로 적합하다.
- 착수한다면 정책 생성 토큰·판정 횟수 같은 텔레메트리 지표만 비교하고 벽시계는 보조로 둔다.
