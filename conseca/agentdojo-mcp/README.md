# agentdojo-mcp

AgentDojo(v1.1.2)를 MCP 서버로 노출하는 브리지. [Progent](https://github.com/sunblaze-ucb/progent) 저장소의 `agentdojo-mcp/` 디렉터리를 그대로 가져온 것으로, 이 스터디의 Conseca 하네스(`../run_task.py`)가 gemini-cli에 AgentDojo 툴을 꽂기 위해 쓴다. Progent의 방어 코드(`secagent`)는 포함하지 않으며 import하지도 않는다.

원본에서 문서·노트북·테스트 디렉터리는 뺐고 런타임에 필요한 것만 남겼다: `mcp_server.py`, `pyproject.toml`, `src/agentdojo/`(AgentDojo 소스와 스위트 데이터). 라이선스는 원본의 MIT(`LICENSE`).

```bash
uv pip install --python <venv python> ./agentdojo-mcp
python mcp_server.py --api-port 9000 --mcp-port 9001 --results-dir ../mcp_results
```

| 포트 | 역할 |
|---|---|
| 9000 | REST. `POST /init_task`(환경 로드·주입 삽입, 사용자 프롬프트 반환), `POST /finish_task`(utility·security 채점) |
| 9001 | MCP(Streamable HTTP, stateless). HTTP 헤더 `task_id`로 어느 태스크 환경인지 고른다 |

`--results-dir`에는 태스크마다 툴 호출 이력과 채점 결과가 JSON으로 남는다. 태스크 id는 `<agent>_<suite>_<user_task_N>_<injection_task_N|noinjection>` 형태여야 파일이 정리된다.
