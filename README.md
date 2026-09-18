# policy-llm-overhead-study

Google `gemini-cli`에 내장된 IPI 방어 **Conseca**를 켰을 때와 껐을 때의 비용(지연·호출 수·토큰)과 방어 효과(utility·ASR)를 재는 하네스. 이 브랜치는 [AgentDyn](https://github.com/SaFo-Lab/AgentDyn)(shopping/github/dailylife) 스위트를 돌리는 버전이며, AgentDojo 4개 스위트도 함께 돈다(main 브랜치는 AgentDojo 전용).

## 바로 돌리기

Gemini 인증만 있으면 된다.

```bash
cd conseca
export GEMINI_API_KEY=...
./setup.sh                  # gemini-cli 0.59.0 + Python venv + AgentDojo 브리지
./run_pilot.sh --smoke      # 태스크 1개 × Conseca off/on, 비교표까지 출력
SUITE=shopping ./run_pilot.sh --smoke   # AgentDyn 스위트
MODEL=gemini-2.5-flash SUITE=shopping ./run_pilot.sh --smoke   # 다른 모델. 결과는 runs/<model>/에 따로 남는다
./smoke_models.sh gemini-3.1-flash-lite gemini-2.5-flash        # 모델마다 smoke 1건씩 돌리고 모델 비교표 출력
.venv/bin/python results_table.py       # 모든 모델·스위트·arm 결과를 한 표로
```

전체 절차·분석 방법·함정은 [conseca/README.md](conseca/README.md).

## 구성

| 경로 | 내용 |
|---|---|
| [`conseca/`](conseca/README.md) | 하네스 본체. stock gemini-cli를 headless로 호출해 AgentDyn/AgentDojo에서 Conseca on/off 비용과 방어 효과를 잰다. 세팅·실행·분석 스크립트 포함. AgentDyn 관련 차이는 [§8](conseca/README.md#8-agentdyn) |
| [`conseca/agentdojo-mcp/`](conseca/agentdojo-mcp/README.md) | AgentDyn(AgentDojo 0.1.35 포크)의 7개 스위트를 MCP로 노출하는 브리지(동봉) |
