# gemini-cli Conseca 구현 분석 (코드 레벨)

Google `gemini-cli`에 내장된 보안 옵션 **Conseca**(`security.enableConseca`, UI 라벨 "Enable Context-Aware Security")를 소스 코드 기준으로 분석한 문서다. 구현 디자인, 사용하는 LLM, 두 LLM의 프롬프트 전문, 입력과 출력, 실패 처리, 텔레메트리, 그리고 코드에서 드러나는 설계상 특징을 다룬다.

| 항목 | 값 |
|---|---|
| 분석 대상 | `google-gemini/gemini-cli` 저장소 `main` (`9c1b0a6`, 2026-09-11), `v0.59.0` 태그(`fb0d535`)와 대조 |
| 버전 차이 | `packages/core/src/safety/conseca/*`, `conseca.toml`, `config.ts`의 Conseca 관련 코드는 v0.59.0과 main이 **동일** |
| 도입 커밋 | `dde844db` "feat(security): Introduce Conseca framework (#13193)", 2026-02-23, Rishabh Khandelwal |
| 후속 변경 | `28af4e12`(import 정리), `de656f01`(AgentLoopContext 마이그레이션), `2194da2b`(텔레메트리에서 `logPrompts` 플래그 존중) |
| 코드 규모 | 구현 4개 파일 534줄 (`conseca.ts` 174, `policy-generator.ts` 178, `policy-enforcer.ts` 164, `types.ts` 18) + 테스트 4개 파일 588줄 |

경로는 모두 `packages/core/src/` 기준이다. 문서 끝의 [부록 A](#부록-a-파일-색인)에 파일 색인이 있다.

---

## 1. 한 줄 요약

Conseca는 gemini-cli의 **안전 검사기(Safety Checker) 프레임워크에 꽂히는 인프로세스 체커**다. 사용자 프롬프트 1개당 **정책 생성 LLM 호출 1회**로 툴별 자연어 정책(`allow | deny | ask_user` + 제약 문장)을 만들고, 이후 **모든 툴 호출마다 정책 강제 LLM 호출 1회**로 해당 툴 호출이 정책을 지키는지 판정한다. 두 호출 모두 `gemini-2.5-flash`(코드 상수 `DEFAULT_GEMINI_FLASH_MODEL`)를 사용하며, 메인 에이전트와 같은 `ContentGenerator`(같은 인증·쿼터)를 공유한다. LLM 오류·파싱 실패는 **fail-open(allow)**, 체커 타임아웃(30초)만 **fail-closed(deny)** 다.

---

## 2. 구현 디자인

### 2.1 구성 요소

```
settings.json  security.enableConseca: true
      │  (cli/config/config.ts:1124 → CoreConfig params.enableConseca)
      ▼
Config (core/config/config.ts:1318~1352)
  ├─ this.enableConseca = params.enableConseca ?? false
  ├─ ContextBuilder(this)                         ← 히스토리/환경 컨텍스트 생성
  ├─ CheckerRegistry(targetDir)                   ← 'allowed-path', 'conseca' 인프로세스 체커 보유
  ├─ CheckerRunner(contextBuilder, registry, {timeout: 30000})
  ├─ PolicyEngine(policyEngineConfig, checkerRunner)
  └─ if (enableConseca) ConsecaSafetyChecker.getInstance().setContext(this)

policy/policies/conseca.toml (기본 정책 디렉터리, 항상 로드됨)
  [[safety_checker]] toolName="*" priority=100 checker={type="in-process", name="conseca"}
      │
      ▼
PolicyEngine.check()  ──▶  CheckerRunner.runChecker()  ──▶  ConsecaSafetyChecker.check()
                                                               ├─ generatePolicy()   (LLM #1, 프롬프트당 1회)
                                                               └─ enforcePolicy()    (LLM #2, 툴 호출당 1회)
```

| 구성 요소 | 파일 | 역할 |
|---|---|---|
| `ConsecaSafetyChecker` | `safety/conseca/conseca.ts` | 싱글턴. `InProcessChecker` 인터페이스(`check(input)`) 구현. 정책 캐시와 두 LLM 호출의 오케스트레이션 |
| `generatePolicy()` | `safety/conseca/policy-generator.ts` | LLM #1. 사용자 프롬프트 + 툴 선언 → `SecurityPolicy` |
| `enforcePolicy()` | `safety/conseca/policy-enforcer.ts` | LLM #2. 툴별 정책 + 툴 호출 → `SafetyCheckResult` |
| `SecurityPolicy`, `ToolPolicy` | `safety/conseca/types.ts` | 정책 자료형 |
| `conseca.toml` | `policy/policies/conseca.toml` | 모든 툴(`*`)에 conseca 체커를 붙이는 안전 검사기 규칙 |
| `CheckerRegistry` | `safety/registry.ts` | 이름 `conseca` → 싱글턴 인스턴스 해석 |
| `CheckerRunner` | `safety/checker-runner.ts` | 체커 실행, 컨텍스트 조립, 타임아웃 |
| `ContextBuilder` | `safety/context-builder.ts` | Gemini 대화 히스토리를 `ConversationTurn[]`으로 변환 |
| `SafetyCheckInput/Result/Decision` | `safety/protocol.ts` | 체커 프로토콜(v1.0.0) |
| `PolicyEngine` | `policy/policy-engine.ts` | 규칙 판정 뒤 안전 검사기 실행 |
| 텔레메트리 | `telemetry/conseca-logger.ts`, `telemetry/types.ts` | `conseca_policy_generation`, `conseca_verdict` 이벤트 |

### 2.2 활성화 경로

1. `packages/cli/src/config/settingsSchema.ts:2007` — `security.enableConseca` (boolean, 기본 `false`, 재시작 필요, 설정 다이얼로그에 노출).
2. `packages/cli/src/config/config.ts:1124` — `enableConseca: settings.security?.enableConseca` 로 core `Config` 파라미터에 전달.
3. `core/config/config.ts:1318` — `this.enableConseca = params.enableConseca ?? false`.
4. `core/config/config.ts:1349~1352` — 켜져 있으면 싱글턴에 `setContext(this)`(Config가 `AgentLoopContext`를 구현)로 `config`, `toolRegistry`, `geminiClient` 접근 경로를 부여.

중요한 점은 **`conseca.toml`은 옵션과 무관하게 항상 로드된다**는 것이다. `policy/config.ts`의 `getPolicyDirectories()`가 `DEFAULT_CORE_POLICIES_DIR`(= `policy/policies/`)의 모든 TOML을 읽으므로 `[[safety_checker]] toolName = "*"` 규칙은 항상 `PolicyEngine.checkers`에 들어간다. 옵션이 꺼져 있으면 체커 자체는 매 툴 호출마다 호출되지만 `ConsecaSafetyChecker.check()`가 첫 분기에서 즉시 `ALLOW`("Conseca is disabled")를 돌려주고 끝난다(`conseca.ts:71~77`). 즉 off 상태의 비용은 함수 호출 1회 + `ContextBuilder.buildFullContext()`의 히스토리 변환뿐이다.

### 2.3 정책 엔진과의 결합 지점

`PolicyEngine.check()` (`policy/policy-engine.ts:600~914`)의 순서:

1. `rules`(TOML/설정/"항상 허용" 등)를 우선순위대로 매칭해 `ALLOW | DENY | ASK_USER`를 정한다. 매칭이 없으면 YOLO 모드는 `ALLOW`, 그 외는 `defaultDecision`.
2. `ALLOW`인 경우 추가 강등 조건(샌드박스 외부 경로, 빌드 파일 편집)을 검사.
3. **안전 검사기 단계** (`:861~908`): `decision !== DENY`이고 `checkerRunner`가 있으면 `checkers`를 순회하며 `ruleMatches()`로 매칭되는 체커를 순차 실행.
   - 체커가 `DENY` → 즉시 `{decision: DENY, rule: matchedRule}` 반환.
   - 체커가 `ASK_USER` → `decision = ASK_USER`로 강등하고 다음 체커 계속.
   - 체커가 예외를 던지면 → `DENY`.
   - 체커가 `ALLOW` → 아무 것도 바꾸지 않음.

따라서 Conseca는 **규칙 판정을 오버라이드하지 않고 오직 강등(allow→ask_user, 어떤 결정→deny)만 할 수 있다.** 규칙이 `DENY`면 Conseca는 아예 호출되지 않고, YOLO(`--approval-mode yolo`)로 규칙이 전부 `ALLOW`여도 Conseca는 실행된다. `conseca.toml`에 `modes` 제한이 없으므로 모든 승인 모드에 적용된다.

### 2.4 툴 호출 1건의 전체 흐름

```
Scheduler.validateAndSchedule (scheduler/scheduler.ts:649)
  └─ checkPolicy(toolCall, config, subagent)                     scheduler/policy.ts:53
       └─ PolicyEngine.check({name, args}, serverName, annotations, subagent)
            ├─ rules 매칭 → decision
            └─ for checkerRule of checkers:                       policy-engine.ts:861
                 └─ CheckerRunner.runChecker(toolCall, {type:'in-process', name:'conseca'})
                      └─ runInProcessChecker                      checker-runner.ts:88
                           ├─ registry.resolveInProcess('conseca') → 싱글턴
                           ├─ contextBuilder.buildFullContext()   ← 대화 히스토리 → turns[]
                           ├─ input = {protocolVersion:'1.0.0', toolCall, context, config: undefined}
                           └─ executeWithTimeout(checker.check(input))   30 s
                                └─ ConsecaSafetyChecker.check(input)      conseca.ts:58
                                     ├─ context 없음 → ALLOW ("Config not initialized")
                                     ├─ enableConseca false → ALLOW ("Conseca is disabled")
                                     ├─ userPrompt = history.turns.at(-1).user.text
                                     ├─ trustedContent = JSON.stringify(toolRegistry.getFunctionDeclarations(), null, 2)
                                     ├─ if userPrompt: getPolicy(userPrompt, trustedContent)   ← 캐시 히트면 LLM 호출 없음
                                     │       └─ generatePolicy()  → LLM #1 → currentPolicy 갱신 + 텔레메트리
                                     ├─ if !currentPolicy → ALLOW ("No security policy generated.", error 포함)
                                     ├─ else enforcePolicy(currentPolicy, toolCall)  → LLM #2
                                     └─ logConsecaVerdict(...) → 결과 반환
            ← DENY 면 즉시 반환 / ASK_USER 면 강등
  ├─ DENY → CoreToolCallStatus.Error, "Tool execution denied by policy." (POLICY_VIOLATION)
  └─ ASK_USER → resolveConfirmation() → 사용자 확인 UI
```

### 2.5 상태 관리와 정책 캐시

`ConsecaSafetyChecker`는 프로세스 전역 싱글턴이며 세 가지 상태를 가진다.

| 필드 | 의미 |
|---|---|
| `context: AgentLoopContext` | `setContext()`로 주입된 Config. 없으면 항상 ALLOW |
| `activeUserPrompt: string` | 마지막으로 정책을 생성한 사용자 프롬프트 원문 |
| `currentPolicy: SecurityPolicy` | 툴 이름 → `ToolPolicy` 맵 |

캐시 규칙(`getPolicy`, `conseca.ts:127~152`): `activeUserPrompt === userPrompt && currentPolicy`이면 재사용, 아니면 재생성. 즉 **프롬프트 문자열 완전 일치**가 캐시 키다.

정책이 "프롬프트당 1회"만 생성되는 실제 메커니즘은 `extractUserPrompt`와 `ContextBuilder`의 조합에 있다.

- `ContextBuilder.convertHistoryToTurns()`는 `geminiClient.getHistory()`의 `Content[]`를 `{user:{text}, model:{text, toolCalls}}` 턴으로 접는다. `role: 'user'`인 Content의 텍스트 파트만 이어 붙여 `user.text`를 만든다.
- Gemini 대화에서 **함수 응답(functionResponse)도 `role: 'user'` Content**로 히스토리에 들어가며 텍스트 파트가 없다. 그래서 첫 툴 호출 직후부터는 마지막 턴의 `user.text`가 빈 문자열이 되고, `extractUserPrompt`는 빈 문자열을 falsy로 보아 `null`을 반환한다.
- `null`이면 `getPolicy`를 건너뛰고(`conseca.ts:88~94`) 기존 `currentPolicy`로 강제만 수행한다.

결과적으로 한 사용자 턴 안에서 정책 생성은 첫 툴 호출 시점에 1회, 이후 같은 턴의 툴 호출은 모두 강제만 한다. 저장소의 [conseca/README.md](conseca/README.md) 검증 실행(정책 1회, 판정 11회)이 이 동작과 일치한다. 다음 사용자 턴에서 마지막 턴의 `user.text`가 새 프롬프트가 되면 정책을 다시 만든다.

헤드리스(`-p`) 모드에서 히스토리가 비어 있으면 `ContextBuilder`가 `config.getQuestion()`(CLI 인자로 받은 프롬프트)을 첫 턴으로 밀어 넣어 같은 경로를 탄다(`context-builder.ts:36~45`).

주의할 점 두 가지:

- 상태가 싱글턴에 있으므로 **서브에이전트 호출과 메인 에이전트가 같은 정책 캐시를 공유**한다. 서브에이전트의 툴 호출도 `subagent` 인자만 다를 뿐 같은 `check()`를 탄다.
- 캐시 키가 프롬프트 원문이므로 사용자가 같은 문장을 다시 보내면 툴 목록이 바뀌어도 정책을 재생성하지 않는다.

### 2.6 판정 매핑과 실패 처리 요약

| 상황 | 반환 | 방향 | 위치 |
|---|---|---|---|
| `setContext` 안 됨 | ALLOW "Config not initialized" | fail-open | `conseca.ts:63` |
| `enableConseca=false` | ALLOW "Conseca is disabled" | fail-open | `conseca.ts:71` |
| 정책이 아직 없음(생성 실패 포함) | ALLOW + `error: 'No security policy generated.'` | fail-open | `conseca.ts:98` |
| 정책 생성: ContentGenerator 없음 / 빈 응답 / JSON·스키마 파싱 실패 / 예외 | `policy: {}` + error → 위 항목으로 ALLOW | fail-open | `policy-generator.ts:109,146,159,170` |
| 강제: ContentGenerator 없음 | ALLOW + error | fail-open | `policy-enforcer.ts:63` |
| 강제: `toolCall.name` 없음 | ALLOW + error | fail-open | `policy-enforcer.ts:73` |
| 강제: 빈 응답 / 파싱 실패 / 예외 | ALLOW + error | fail-open | `policy-enforcer.ts:121,151,159` |
| 강제 LLM이 `allow`/`ask_user`/`deny` 응답 | 그대로 매핑. 알 수 없는 값은 `deny` (스키마로 enum 강제되므로 실제로는 도달 어려움) | — | `policy-enforcer.ts:132~143` |
| 체커 전체가 30초 초과 | `executeWithTimeout` reject → `runInProcessChecker` catch → **DENY** | fail-closed | `checker-runner.ts:108~117`, `config.ts:1329` |
| 체커가 예외 throw | DENY | fail-closed | `policy-engine.ts:897` |

`ALLOW` 결과의 `error` 필드는 텔레메트리(`CONSECA_ERROR`)로만 나가고 사용자에게는 보이지 않는다.

### 2.7 사용자에게 도달하는 것

- **DENY**: 스케줄러가 `getPolicyDenialError()`로 `"Tool execution denied by policy."`를 만든다. `denyMessage`는 매칭된 *규칙*의 것이므로 Conseca가 만든 `reason`은 사용자·모델 어느 쪽에도 전달되지 않는다. 이유는 `debugLogger`와 텔레메트리에만 남는다.
- **ASK_USER**: 일반 확인 다이얼로그가 뜬다. 비대화형(`-p`)에서는 `checkPolicy`가 `"requires user confirmation, which is not supported in non-interactive mode"` 에러를 던져 툴이 실패한다(`scheduler/policy.ts:95~101`).
- **ASK_USER 경로의 2중 호출**: 확인 다이얼로그를 띄우기 위해 `BaseToolInvocation.shouldConfirmExecute()`가 `getMessageBusDecision()`으로 `TOOL_CONFIRMATION_REQUEST`를 메시지 버스에 발행하고(`tools/tools.ts:208, 296`), `MessageBus.publish()`가 다시 `policyEngine.check()`를 호출한다(`confirmation-bus/message-bus.ts:105`). 이 두 번째 호출에서도 체커가 돌아가므로 **ASK_USER로 판정된 툴 호출은 강제 LLM이 2회 실행**된다(정책은 캐시 히트).

---

## 3. Conseca가 사용하는 LLM

| 항목 | 정책 생성기 (LLM #1) | 정책 강제기 (LLM #2) |
|---|---|---|
| 모델 | `DEFAULT_GEMINI_FLASH_MODEL` | `DEFAULT_GEMINI_FLASH_MODEL` |
| 상수 값 | `'gemini-2.5-flash'` (`config/models.ts:68`) | 동일 |
| 호출 API | `config.getContentGenerator().generateContent(request, promptId, role)` | 동일 |
| `promptId` | `'conseca-policy-generation'` | `'conseca-policy-enforcement'` |
| `role` | `LlmRole.SUBAGENT` (`'subagent'`) | `LlmRole.SUBAGENT` |
| 응답 형식 | `responseMimeType: 'application/json'` + `responseSchema` (zod → OpenAPI 3) | 동일 |
| 시스템 인스트럭션 | 없음. 프롬프트 전체가 `role: 'user'` 단일 파트 | 동일 |
| 온도·토큰 등 기타 설정 | 지정 없음 (모델 기본값) | 동일 |
| 호출 빈도 | 사용자 프롬프트당 1회 | 툴 호출당 1회 (ASK_USER 경로는 2회) |

세부 사항:

- **모델은 설정으로 바꿀 수 없다.** 코드에 상수로 박혀 있고 `settings.model.name`이나 `--model`은 메인 에이전트에만 적용된다. 다만 `DEFAULT_GEMINI_FLASH_MODEL`은 `let`이며 `setFlashModels()`(`models.ts:77~80`)가 백엔드의 Gemini 3.5 Flash GA 접근 여부에 따라 `'gemini-3.5-flash'` 또는 `'gemini-3-flash'`로 바꿀 수 있다. 어느 값이 실제로 쓰였는지는 텔레메트리 `api_response` 이벤트의 `model` 필드로 확인해야 한다.
- **메인 에이전트와 같은 `ContentGenerator`**를 쓰므로 인증 방식(OAuth/API 키/Vertex)과 쿼터를 공유한다. Conseca의 호출도 `api_request`/`api_response` 텔레메트리 이벤트를 발생시키며, `role: 'subagent'`와 위 `prompt_id`로 메인 호출과 구분된다.
- "시스템 프롬프트"라는 표현을 쓰지만 구현상 `systemInstruction` 필드는 사용하지 않는다. 아래 4장과 5장의 프롬프트가 사용자 턴 텍스트로 통째로 들어간다.
- 템플릿 치환은 `safeTemplateReplace()`(`utils/textUtils.ts:155`)로 **단일 패스**만 수행한다. 사용자 프롬프트 안에 `{{trusted_content}}` 같은 플레이스홀더가 있어도 재치환되지 않는다(테스트 `policy-generator.test.ts:94`).

---

## 4. LLM #1 — 정책 생성기 (`policy-generator.ts`)

### 4.1 프롬프트 전문

`CONSECA_POLICY_GENERATION_PROMPT` (`policy-generator.ts:17~72`). `{{user_prompt}}`와 `{{trusted_content}}`가 치환된다.

````text
You are a security expert responsible for generating fine-grained security policies for a large language model integrated into a command-line tool. Your role is to act as a "policy generator" that creates temporary, context-specific rules based on a user's prompt and the tools available to the main LLM.

Your primary goal is to enforce the principle of least privilege. The policies you create should be as restrictive as possible while still allowing the main LLM to complete the user's requested task.

For each tool that is relevant to the user's prompt, you must generate a policy object.

### Output Format
You must return a JSON object with a "policies" key, which is an array of objects. Each object must have:
- "tool_name": The name of the tool.
- "policy": An object with:
  - "permissions": "allow" | "deny" | "ask_user"
  - "constraints": A detailed description of conditions (e.g. allowed files, arguments).
  - "rationale": Explanation for the policy.

Example JSON:
```json
{
  "policies": [
    {
      "tool_name": "read_file",
      "policy": {
        "permissions": "allow",
        "constraints": "Only allow reading 'main.py'.",
        "rationale": "User asked to read main.py"
      }
    },
    {
      "tool_name": "run_shell_command",
      "policy": {
        "permissions": "deny",
        "constraints": "None",
        "rationale": "Shell commands are not needed for this task"
      }
    }
  ]
}
```

### Guiding Principles:
1.  **Permissions:**
    *   **allow:** Required tools for the task.
    *   **deny:** Tools clearly outside the scope.
    *   **ask_user:** Destructive actions or ambiguity.

2.  **Constraints:**
    *   Be specific! Restrict file paths, command arguments, etc.

3.  **Rationale:**
    *   Reference the user's prompt.

User Prompt: "{{user_prompt}}"

Trusted Tools (Context):
{{trusted_content}}
````

### 4.2 입력

| 플레이스홀더 | 출처 | 내용 |
|---|---|---|
| `{{user_prompt}}` | `ConsecaSafetyChecker.extractUserPrompt()` | 대화 히스토리 마지막 턴의 `user.text` (텍스트 파트 연결). 헤드리스면 `config.getQuestion()` |
| `{{trusted_content}}` | `toolRegistry.getFunctionDeclarations()`를 `JSON.stringify(..., null, 2)` | **현재 활성화된 모든 툴**의 `FunctionDeclaration[]` (이름, 설명, 파라미터 JSON 스키마). 내장 툴과 MCP 툴(`mcp_<server>_<tool>`) 모두 포함 |

"Trusted"라는 이름과 달리 툴 선언에는 MCP 서버가 제공하는 설명 문자열이 그대로 들어간다. 사용자 프롬프트 역시 큰따옴표로만 감싸져 있고 이스케이프되지 않는다.

입력 크기는 툴 수에 비례한다. 툴이 수십 개면 선언 JSON만 수만 자가 되므로 정책 생성 1회의 입력 토큰이 강제 호출보다 훨씬 크다.

### 4.3 요청 구성

```ts
contentGenerator.generateContent(
  {
    model: DEFAULT_GEMINI_FLASH_MODEL,
    config: {
      responseMimeType: 'application/json',
      responseSchema: zodToJsonSchema(SecurityPolicyResponseSchema, { target: 'openApi3' }),
    },
    contents: [{ role: 'user', parts: [{ text: <치환된 프롬프트> }] }],
  },
  'conseca-policy-generation',
  LlmRole.SUBAGENT,
);
```

### 4.4 출력

모델에 전달되는 `responseSchema` (zod 정의를 실제 변환한 결과):

```json
{
  "type": "object",
  "properties": {
    "policies": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "tool_name": { "type": "string" },
          "policy": {
            "type": "object",
            "properties": {
              "permissions": { "type": "string", "enum": ["allow", "deny", "ask_user"] },
              "constraints": { "type": "string" },
              "rationale": { "type": "string" }
            },
            "required": ["permissions", "constraints", "rationale"],
            "additionalProperties": false
          }
        },
        "required": ["tool_name", "policy"],
        "additionalProperties": false
      }
    }
  },
  "required": ["policies"],
  "additionalProperties": false
}
```

후처리(`policy-generator.ts:143~158`):

1. `getResponseText()`로 첫 후보의 텍스트 파트(thought 제외)를 이어 붙인다.
2. `JSON.parse` → `SecurityPolicyResponseSchema.parse` (zod 검증).
3. 배열을 `{ [tool_name]: { permissions, constraints, rationale } }` 맵(`SecurityPolicy`)으로 변환한다. 같은 `tool_name`이 두 번 나오면 뒤의 것이 덮어쓴다.
4. 반환형은 `{ policy: SecurityPolicy, error?: string }`. 실패 시 `policy: {}`.

내부 정책 자료형 (`safety/conseca/types.ts`):

```ts
interface ToolPolicy {
  permissions: SafetyCheckDecision;   // 'allow' | 'deny' | 'ask_user'
  constraints: string;                // 자연어 제약
  rationale: string;
}
type SecurityPolicy = Record<string, ToolPolicy>;  // tool_name → ToolPolicy
```

`constraints`가 **자유 형식 문자열**이라는 점이 핵심이다. 정규식이나 구조화된 인자 제약이 아니므로 결정론적으로 평가할 수 없고, 그래서 강제 단계에 두 번째 LLM이 필요하다.

---

## 5. LLM #2 — 정책 강제기 (`policy-enforcer.ts`)

### 5.1 프롬프트 전문

`CONSECA_ENFORCEMENT_PROMPT` (`policy-enforcer.ts:19~40`). `{{policy}}`와 `{{tool_call}}`이 치환된다.

```text
You are a security enforcement engine. Your goal is to check if a specific tool call complies with a given security policy.

Input:
1.  **Security Policy:** A set of rules defining allowed and denied actions for this specific tool.
2.  **Tool Call:** The actual function call the system intends to execute.

Security Policy:
{{policy}}

Tool Call:
{{tool_call}}

Evaluate the tool call against the policy.
1. Check if the tool is allowed.
2. Check if the arguments match the constraints.
3. Output a JSON object with:
   - "decision": "allow", "deny", or "ask_user".
   - "reason": A brief explanation.

Output strictly JSON.
```

### 5.2 입력

| 플레이스홀더 | 출처 | 내용 |
|---|---|---|
| `{{policy}}` | `JSON.stringify(policy[toolName] \|\| {}, null, 2)` | **해당 툴 하나의** `ToolPolicy`. 정책에 그 툴이 없으면 `{}` |
| `{{tool_call}}` | `JSON.stringify(toolCall, null, 2)` | `{ name, args }` — 스케줄러가 넘긴 함수 호출 전체. `args`에는 파일 경로, 셸 명령, 쓸 내용 등이 그대로 들어감 |

정책 생성기와 달리 **전체 정책이 아니라 해당 툴의 항목만** 보낸다. 다른 툴의 정책이나 사용자 프롬프트는 강제기에 주어지지 않으므로, 강제기는 "이 호출이 사용자 의도에 맞는가"를 직접 볼 수 없고 오직 생성기가 써 놓은 `constraints` 문장에 의존한다.

정책에 없는 툴이면 `{}`를 넣고도 LLM을 호출한다. 프롬프트는 빈 정책을 어떻게 다루라는 지시가 없으므로 결과는 모델 판단에 맡겨진다(테스트 `policy-enforcer.test.ts:108`은 이 경우를 "fail-open/check behavior"로 명시하고 allow 응답을 모킹한다).

### 5.3 요청 구성

```ts
contentGenerator.generateContent(
  {
    model: DEFAULT_GEMINI_FLASH_MODEL,
    config: {
      responseMimeType: 'application/json',
      responseSchema: zodToJsonSchema(EnforcementResultSchema, { target: 'openApi3' }),
    },
    contents: [{ role: 'user', parts: [{ text: <치환된 프롬프트> }] }],
  },
  'conseca-policy-enforcement',
  LlmRole.SUBAGENT,
);
```

### 5.4 출력

`responseSchema`:

```json
{
  "type": "object",
  "properties": {
    "decision": { "type": "string", "enum": ["allow", "deny", "ask_user"] },
    "reason": { "type": "string" }
  },
  "required": ["decision", "reason"],
  "additionalProperties": false
}
```

후처리(`policy-enforcer.ts:130~146`): `JSON.parse` → zod 검증 → `decision`을 `SafetyCheckDecision` enum으로 매핑(`allow`→ALLOW, `ask_user`→ASK_USER, `deny` 및 그 외→DENY). 반환형은 프로토콜의 `SafetyCheckResult`:

```ts
{ decision: 'allow', reason?: string, error?: string }
| { decision: 'deny', reason: string }
| { decision: 'ask_user', reason: string }
```

이 결과가 2.3절의 정책 엔진 규칙에 따라 최종 `PolicyDecision`으로 합쳐진다.

---

## 6. 체커 프로토콜과 컨텍스트

Conseca는 외부 프로세스 체커와 같은 `SafetyCheckInput`을 받지만(`safety/protocol.ts`), 실제로 사용하는 필드는 `toolCall`과 `context.history.turns.at(-1).user.text`뿐이다.

```ts
interface SafetyCheckInput {
  protocolVersion: '1.0.0';
  toolCall: FunctionCall;                       // { name, args }
  context: {
    environment: { cwd: string; workspaces: string[] };   // Conseca는 사용 안 함
    history?: { turns: ConversationTurn[] };              // 마지막 턴의 user.text만 사용
  };
  config?: unknown;                              // conseca.toml에 config 없음 → undefined
}
```

`ContextBuilder.buildFullContext()`는 매 체커 호출마다 전체 히스토리를 변환한다. `conseca.toml`에 `required_context`가 없으므로 항상 전체 컨텍스트가 만들어지지만, 툴 선언은 이 입력이 아니라 `this.context.toolRegistry`에서 직접 가져온다.

---

## 7. 텔레메트리

| 이벤트 | 시점 | 필드 |
|---|---|---|
| `conseca_policy_generation` (OTel: `gemini_cli.conseca.policy_generation`) | `getPolicy()`가 생성기를 호출할 때마다 (캐시 히트 시 없음) | `user_prompt`, `trusted_content`, `policy`(JSON 문자열), `error?` |
| `conseca_verdict` (OTel: `gemini_cli.conseca.verdict`) | `check()`가 결과를 낼 때마다 (disabled·context 없음 분기는 제외) | `user_prompt`, `policy`, `tool_call`, `verdict`, `verdict_rationale`, `error?` |
| `api_request` / `api_response` | 두 LLM 호출마다 | `role: 'subagent'`, `prompt_id: 'conseca-policy-generation' \| 'conseca-policy-enforcement'`, 토큰 수, 지연 |

- Clearcut(Google 내부 로깅) 키: `CONSECA_POLICY_GENERATION=159`, `CONSECA_VERDICT=160`, `CONSECA_GENERATED_POLICY=161`, `CONSECA_VERDICT_RESULT=162`, `CONSECA_VERDICT_RATIONALE=163`, `CONSECA_TRUSTED_CONTENT=164`, `CONSECA_USER_PROMPT=165`, `CONSECA_ERROR=166` (`telemetry/clearcut-logger/event-metadata-key.ts:654~679`).
- `2194da2b` 이후 `user_prompt`, `trusted_content`, `policy`, `tool_call`, `verdict_rationale`는 `telemetry.logPrompts`가 켜져 있을 때만 기록된다. `verdict`와 `error`는 항상 기록된다.
- `docs/cli/telemetry.md:862`는 `gemini_cli.conseca.verdict`의 속성을 `decision: "accept" | "reject" | "modify"`로 적고 있는데, 이는 구현(`verdict: allow|deny|ask_user`)과 맞지 않는 **문서 오류**다.
- 이 저장소의 `conseca/parse_telemetry.py`는 위 `role`과 `prompt_id`로 에이전트 비용과 Conseca 비용을 분리한다.

---

## 8. 코드에서 드러나는 설계상 특징과 한계

### 8.1 설계 선택

1. **두 단계 모두 LLM.** 원 논문(Conseca, "contextual security")의 결정론적 강제기와 달리, 출하 구현은 제약을 자연어로 두고 강제도 LLM에 맡긴다. 이 저장소의 `EXPERIMENT_README.md` §8이 설명하는 `CONSECA_ENFORCER=deterministic` 패치는 gemini-cli 본체에는 없다.
2. **정책은 프롬프트 스코프, 강제는 호출 스코프.** 생성기는 사용자 프롬프트와 툴 목록만 보고, 강제기는 툴별 정책과 호출만 본다. 대화 히스토리, 툴 실행 결과, 이전 호출은 어느 쪽에도 주어지지 않는다. 따라서 "이메일을 읽은 뒤 그 내용대로 송금"과 같은 다단계 주입은 첫 프롬프트에서 예상되지 않았던 툴을 요구할 때만 잡힌다.
3. **강등 전용.** 정책 엔진 규칙보다 관대해질 수 없다. 사용자의 "항상 허용"이나 YOLO도 Conseca의 deny를 막지 못한다.
4. **fail-open 기본.** LLM 오류(429 포함), 빈 응답, JSON 파싱 실패는 모두 allow. 유일한 fail-closed는 30초 타임아웃과 체커 예외다. 무료 티어에서 429가 잦으면 보호가 조용히 사라지고 `error` 필드로만 흔적이 남는다.

### 8.2 구현상 관찰

| 관찰 | 근거 |
|---|---|
| deny 사유가 사용자·모델에게 전달되지 않음 | `policy-engine.ts:883~890`은 `result.reason`을 버리고 `matchedRule`만 반환. `getPolicyDenialError`는 규칙의 `denyMessage`만 사용 |
| ASK_USER 판정 시 강제기 2회 호출 | `tools.ts:208` → `message-bus.ts:105` 재검사 |
| 헤드리스에서 ask_user는 곧 실패 | `scheduler/policy.ts:95` |
| 정책에 없는 툴도 LLM 호출 | `policy-enforcer.ts:79` `policy[toolName] \|\| {}` |
| 프롬프트 텍스트 완전 일치 캐시 | `conseca.ts:132` |
| 정책 생성 실패 시 이후 모든 툴이 무검사 통과 | `currentPolicy = {}`는 truthy이므로 `enforcePolicy({}, ...)`가 호출되긴 하나 정책이 `{}`. 생성 자체가 예외로 실패해도 `policy: {}`가 저장되어 다음 프롬프트까지 재시도하지 않음 |
| 툴 선언 전체가 매 정책 생성에 포함 | `conseca.ts:82~86`. 필터링 없음 |
| 서브에이전트와 상태 공유 | 싱글턴 + `subagent` 무시 |
| 프롬프트 주입 표면 | 사용자 프롬프트는 생성기 프롬프트에, 툴 인자(MCP 응답에서 유래할 수 있음)는 강제기 프롬프트에 이스케이프 없이 삽입. `safeTemplateReplace`는 `{{...}}` 재치환만 막음 |
| off 상태 비용 | 체커 진입 + 히스토리 변환만. LLM 호출 없음 |

### 8.3 테스트 커버리지

`conseca.test.ts`(11개), `policy-generator.test.ts`(3개), `policy-enforcer.test.ts`(5개), `integration.test.ts`(1개)는 모두 `ContentGenerator`를 모킹한다. 실제 모델 응답 품질을 검증하는 테스트는 없으며, 검증 대상은 싱글턴, 캐시, 분기별 fail-open 동작, 템플릿 재치환 방지, 텔레메트리 호출 여부다.

---

## 9. 오버헤드 관점 정리

이 저장소의 측정 하네스([conseca/README.md](conseca/README.md))와 맞물리는 사항만 요약한다.

| 항목 | 값 |
|---|---|
| 프롬프트당 추가 LLM 호출 | 1회 (정책 생성). 입력 = 프롬프트 + 전체 툴 선언 JSON |
| 툴 호출당 추가 LLM 호출 | 1회 (강제). ASK_USER 판정이면 2회 |
| 모델 | `gemini-2.5-flash` 고정 (백엔드에 따라 3.5 Flash로 치환 가능) |
| 직렬성 | 체커는 스케줄러의 정책 검사 단계에서 `await`되므로 툴 실행 전에 완전히 끝나야 함. 병렬 툴 호출도 각각 순차 검사 |
| 텔레메트리 식별 | `role=subagent`, `prompt_id=conseca-policy-generation` / `conseca-policy-enforcement` |
| 실패 시 비용 | 오류 응답도 왕복 시간은 소모하되 결정은 allow |

---

## 부록 A. 파일 색인

`packages/core/src/` 기준. 줄 번호는 main `9c1b0a6`.

| 파일 | 핵심 위치 |
|---|---|
| `safety/conseca/conseca.ts` | `check()` 58–125, `getPolicy()` 127–152, `extractUserPrompt()` 157–164 |
| `safety/conseca/policy-generator.ts` | 프롬프트 17–72, zod 스키마 77–90, `generatePolicy()` 100–178 |
| `safety/conseca/policy-enforcer.ts` | 프롬프트 19–40, zod 스키마 45–48, `enforcePolicy()` 53–164 |
| `safety/conseca/types.ts` | `ToolPolicy`, `SecurityPolicy` |
| `safety/protocol.ts` | `SafetyCheckInput`, `SafetyCheckDecision`, `SafetyCheckResult` |
| `safety/registry.ts` | `InProcessCheckerType.CONSECA` 등록 24–34 |
| `safety/checker-runner.ts` | `runInProcessChecker()` 88–117, `executeWithTimeout()` 297–310 |
| `safety/context-builder.ts` | `buildFullContext()` 25–58, `convertHistoryToTurns()` 81–127 |
| `policy/policies/conseca.toml` | 전체 6줄 |
| `policy/types.ts` | `InProcessCheckerType` 92–95, `SafetyCheckerRule` 195–245 |
| `policy/policy-engine.ts` | 안전 검사기 루프 860–908 |
| `policy/config.ts` | `getPolicyDirectories()` 108–130 (기본 정책 디렉터리 항상 포함) |
| `config/config.ts` | `enableConseca` 745, 786, 1318; 안전 인프라 생성 1320–1329; 등록 1348–1352 |
| `config/models.ts` | `DEFAULT_GEMINI_FLASH_MODEL` 68, `setFlashModels()` 77–80 |
| `scheduler/policy.ts` | `checkPolicy()` 53–108, 비대화형 ask_user 에러 95–101 |
| `scheduler/scheduler.ts` | 정책 검사 호출과 DENY 처리 649–675 |
| `confirmation-bus/message-bus.ts` | 확인 요청 시 정책 재검사 104–150 |
| `tools/tools.ts` | `shouldConfirmExecute()` 191, `getMessageBusDecision()` 286 |
| `telemetry/conseca-logger.ts` | `logConsecaPolicyGeneration()`, `logConsecaVerdict()` |
| `telemetry/types.ts` | `ConsecaPolicyGenerationEvent` 956, `ConsecaVerdictEvent` 1010 |
| `telemetry/clearcut-logger/event-metadata-key.ts` | Conseca 키 654–679 |
| `telemetry/llmRole.ts` | `LlmRole.SUBAGENT` |
| `utils/textUtils.ts` | `safeTemplateReplace()` 155–166 |
| `packages/cli/src/config/settingsSchema.ts` | `security.enableConseca` 2007–2016 |
| `packages/cli/src/config/config.ts` | 설정 → core 전달 1124 |
| `docs/cli/settings.md`, `docs/reference/configuration.md`, `docs/cli/telemetry.md` | 사용자 문서 (telemetry.md의 속성 설명은 구현과 불일치) |
