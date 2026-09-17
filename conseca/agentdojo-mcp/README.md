# agentdojo-mcp

AgentDyn(AgentDojo 0.1.35 포크; shopping/github/dailylife + banking/slack/travel/workspace)을 MCP 서버로 노출하는 브리지. 이 하네스(`../run_task.py`)가 gemini-cli에 벤치마크 툴을 꽂기 위해 쓴다. 런타임에 필요한 것만 들어 있다: `mcp_server.py`, `pyproject.toml`, `src/agentdojo/`(AgentDyn 소스와 스위트 데이터, `defenses/` 제외). 라이선스는 MIT(`LICENSE`).

```bash
uv pip install --python <venv python> ./agentdojo-mcp
python mcp_server.py --api-port 9000 --mcp-port 9001 --results-dir ../mcp_results
```

| 포트 | 역할 |
|---|---|
| 9000 | REST. `POST /init_task`(환경 로드·주입 삽입, 사용자 프롬프트 반환), `POST /finish_task`(utility·security 채점) |
| 9001 | MCP(Streamable HTTP, stateless). HTTP 헤더 `task_id`로 어느 태스크 환경인지 고른다 |

`/init_task` 필드: `task_id`, `suite_name`, `user_task_id`, `injection_task_id`(없으면 무주입), `benchmark_version`(기본 `v1.2.2`; AgentDojo 스위트를 main 브랜치와 같게 돌리려면 `v1.1.2`), `agent_model`(주입 텍스트의 모델명을 upstream `MODEL_NAMES`로 유도), `attack_model_name`(모델명 직접 지정). 응답에 `benchmark_version`과 실제 쓰인 `attack_model_name`이 돌아온다.

`--results-dir`에는 태스크마다 툴 호출 이력과 채점 결과가 JSON으로 남는다. 태스크 id는 `<agent>_<suite>_<user_task_N>_<injection_task_N|noinjection>` 형태여야 파일이 정리된다.

upstream과 다른 점은 `mcp_server.py` 안에만 있다: 파이프라인 없이 공격을 만들기 위한 `BridgeImportantInstructionsAttack`, 숫자 결과를 위한 `structured_content` 명시, 채점 입력을 content block으로 감싸는 부분.
