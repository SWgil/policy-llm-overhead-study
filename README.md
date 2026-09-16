# policy-llm-overhead-study

Google `gemini-cli`에 내장된 IPI 방어 **Conseca**를 켰을 때와 껐을 때의 비용(지연·호출 수·토큰)과 방어 효과(utility·ASR)를 AgentDojo로 재는 하네스.

## 바로 돌리기

Gemini 인증만 있으면 된다.

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
| [`conseca/`](conseca/README.md) | 하네스 본체. stock gemini-cli를 headless로 호출해 AgentDojo에서 Conseca on/off 비용과 방어 효과를 잰다. 공격은 AutoDojo 캐시 재생이 기본. 세팅·실행·분석 스크립트 포함 |
| [`conseca/agentdojo-mcp/`](conseca/agentdojo-mcp/README.md) | AgentDojo v1.1.2를 MCP로 노출하는 브리지(동봉) |
| [`docs/benchmarks/`](docs/benchmarks/README.md) | 최신 모델에서 AgentDojo ASR이 0 근처인 이유(문헌)와, 대신 쓸 공격·벤치마크 후보(AutoDojo, AgentDyn, IPI Arena, DTap, ClawTrojan, LivePI, RL 공격기)별 분석과 이 하네스 적용 절차 |
