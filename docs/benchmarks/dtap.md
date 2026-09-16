# DTap (DecodingTrust-Agent Platform): MCP 환경 기반 레드팀 플랫폼

- 논문: [DecodingTrust-Agent Platform (DTap): A Controllable and Interactive Red-Teaming Platform for AI Agents](https://arxiv.org/abs/2605.04808) (2026-05)
- 코드: <https://github.com/AI-secure/DecodingTrust-Agent> (Apache-2.0), `pip install decodingtrust-agent-sdk`. 결과 트래젝토리: <https://huggingface.co/datasets/AI-Secure/DTap-Bench-Agent-Trajectories>. 사이트: <https://decodingtrust-agent.com>
- 종류: 플랫폼 + 데이터셋(DTap-Bench) + 자율 레드팀 에이전트(DTap-Red)

## 1. 분석

### 무엇인가

14개 도메인(browser, code, crm, finance, legal, medical 등), 50개 이상 시뮬레이션 환경(Google Workspace, PayPal, Slack, Salesforce 등). **각 환경이 HTTP MCP 서버**로 떠 있고(`dt_arena/config/mcp.yaml`: `transport: http`, `command: ["uv","run","python","main.py"]`, 포트 지정), Docker로 격리된다. 태스크는 `dataset/<domain>/<benign|direct|indirect>/<n>/config.yaml`에 필요한 MCP 서버 목록과 환경 변수를 적고, `setup.sh`로 데이터를 시드한다.

- **DTap-Bench**: `benchmark/{benign,direct,indirect}.jsonl`. 태스크마다 보안 정책과 **검증 가능한 judge**가 붙어 공격 성공을 자동 판정한다. 이 연구에 해당하는 것은 `indirect`(툴 결과·문서·이메일 경유 주입).
- **DTap-Red**: 주입 벡터(프롬프트, 툴, 스킬, 환경, 조합)를 탐색하며 공격을 자동 발견하는 에이전트. 적응형 공격원.
- 에이전트 백엔드: `openaisdk`, `claudesdk`, `googleadk`, `langchain`, `strands`, `pocketflow`. 새 백엔드는 `agent/` 아래에 `Agent`를 서브클래싱해 등록한다. `build_agent()` 헬퍼로 기존 에이전트에 벤치마크 MCP 서버를 붙일 수도 있다.

실행: `python eval/task_runner.py --task-dir dataset/crm/benign/4 --agent-type openaisdk --model gpt-5.4`, 병렬은 `eval/evaluation.py --max-parallel`.

### 공개 수치

논문 요약에는 모델별 ASR이 없다. 트래젝토리 데이터셋과 사이트 리더보드에서 확인해야 한다.

### 이 연구와의 궁합

- 장점: **환경이 이미 HTTP MCP 서버**라 gemini-cli의 `mcpServers.httpUrl` 설정으로 직접 붙는다. 이 하네스가 AgentDojo에 한 일을 플랫폼이 이미 해 둔 셈이다. Conseca는 MCP 툴을 정책 대상으로 삼으므로 곧바로 동작한다. 도메인이 넓어 "Conseca 정책 생성이 어떤 도메인에서 실패하는가"도 볼 수 있다.
- 단점: Docker 의존. 환경 시드가 태스크마다 달라 셋업 시간이 길다. judge가 태스크별이라 하네스의 `utility/security` 두 값으로 환산하는 규칙을 정해야 한다. 툴 개수가 많은 환경에서는 Conseca 정책 생성 토큰이 크게 늘어 429가 잦을 수 있다.
- gemini-cli 백엔드가 없어 직접 써야 한다. 다만 백엔드는 "설정 파일 쓰고 CLI 실행하고 응답 반환"이라 이 하네스의 `run_task.py`를 거의 그대로 옮기면 된다.

## 2. 하네스 접점

| 위치 | 바꿀 것 |
|---|---|
| DTap `agent/geminicli/` (신규) | `Agent` 서브클래스. `run()`에서 (1) 태스크가 준 MCP 서버 URL 목록으로 `.gemini/settings.json` 생성(이 하네스 `write_workspace` 재사용, `mcpServers`를 다중으로), (2) `gemini --approval-mode yolo -o json -p <prompt>` 실행, (3) 응답과 툴 호출 이력을 DTap 형식으로 반환 |
| `conseca/settings.template.json` | `mcpServers`를 여러 개 받도록 템플릿화. `tools.exclude`는 그대로(내장 툴 차단) |
| `conseca/parse_telemetry.py` | 그대로. 텔레메트리 파일 경로만 백엔드에서 지정 |
| `conseca/compare_arms.py` | DTap judge 결과(pass/fail + 정책 위반 여부)를 `utility`(benign 태스크 성공), `security`(indirect 태스크에서 정책 위반 없음)로 매핑하는 어댑터 |
| Conseca | 정책 생성이 도메인별 툴 스키마를 읽는다. 툴 수가 많은 환경에서 정책 생성 토큰·지연을 따로 기록 |

## 3. 적용 절차

1. 플랫폼 설치와 기준 실행.

```bash
pip install "decodingtrust-agent-sdk[google]"
git clone https://github.com/AI-secure/DecodingTrust-Agent /tmp/dtap
cd /tmp/dtap && python eval/task_runner.py --task-dir dataset/crm/benign/4 --agent-type googleadk --model gemini-3.5-flash
```

`googleadk` 백엔드로 먼저 돌려 환경·judge가 동작하는지 본다. 이 결과는 "gemini-cli 없이 같은 모델" 참조점으로도 쓸 수 있다.

2. `agent/geminicli/` 백엔드 작성. 기존 `agent/googleadk/` 구조를 따르고, 본문은 `conseca/run_task.py`의 `write_workspace`, `run_gemini`를 옮긴다. Conseca on/off는 백엔드 옵션(`--agent-arg conseca=true`)으로.
3. MCP 서버가 HTTP라 gemini-cli의 `headers`가 필요 없다. 환경별 인증 토큰이 있으면 `env`로 넘긴다.
4. `benchmark/indirect.jsonl`에서 도메인을 골라(Workspace, Slack, finance가 AgentDojo와 대응) 소규모 파일럿. `benign.jsonl`의 대응 태스크로 utility.
5. 양쪽 arm 실행. judge 출력을 `utility/security`로 환산해 `compare_arms.py`에 넣는다.
6. (선택) DTap-Red를 off arm에 돌려 얻은 공격을 고정하고 양쪽 arm에 재생한다. 적응형 공격 arm은 별도 보고.

## 4. 비용 추정

| 항목 | 값 |
|---|---|
| 셋업 | Docker + 환경 시드. 백엔드 작성 포함 3~5일 |
| 런당 | 환경 부팅 수십 초 + gemini-cli. on arm은 툴 수에 비례해 정책 생성 토큰 증가 |
| 케이스 수 | `indirect.jsonl` 크기 확인 필요. 도메인 3개로 좁히면 수백 런/arm |

## 5. 판단

- **구조적으로 가장 잘 맞는 "새 벤치마크"다.** 환경이 MCP라 브리지가 필요 없고, Conseca의 정책 대상이 곧 벤치마크 툴이다.
- 부담은 Docker·시드·judge 매핑이다. AgentDojo/AgentDyn 결과가 나온 뒤 "MCP 생태계 전체로 일반화되는가"를 묻는 단계에서 도입하는 것이 순서에 맞다.
- DTap-Red는 AutoDojo와 같은 역할(적응형 공격)을 더 넓은 벡터(스킬, 환경)로 한다. gemini-cli의 스킬·확장 기능까지 위협 모델에 넣으려면 여기서만 가능하다.
