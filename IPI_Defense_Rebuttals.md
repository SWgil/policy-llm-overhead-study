# IPI 방어 추천 기법에 대한 반박 논문 정리

> **대상 문서**: [IPI_LLM_Defense_Survey.md](IPI_LLM_Defense_Survey.md)
> **목적**: 앞선 리포트에서 도입 후보로 추천한 기법들에 대해 **반박·우회·무력화를 주장하는 논문**을 찾아 정리하고, 그 결과 **원 권고안을 어떻게 수정해야 하는지** 판단한다.
> **작성일**: 2026-09-07

---

## 목차

- [0. 요약 — 반박 대응 현황 한눈에](#0-요약--반박-대응-현황-한눈에)
- [1. 조사 방법](#1-조사-방법)
- [2. 치명적 반박 (설계 전제가 무너지는 경우)](#2-치명적-반박-설계-전제가-무너지는-경우)
- [3. 심각한 반박 (조건부 무력화)](#3-심각한-반박-조건부-무력화)
- [4. 제한적 반박 (부분 약화·비용 문제)](#4-제한적-반박-부분-약화비용-문제)
- [5. 횡단적 반박 — 모든 기법에 공통 적용](#5-횡단적-반박--모든-기법에-공통-적용)
- [6. 반박 논문들이 제안한 대안 기법](#6-반박-논문들이-제안한-대안-기법)
- [7. 원 리포트 권고안 수정 사항](#7-원-리포트-권고안-수정-사항)
- [8. 결론](#8-결론)
- [9. 참고문헌](#9-참고문헌)

---

## 0. 요약 — 반박 대응 현황 한눈에

| 원 리포트 추천 기법 | 핵심 반박 논문 | 반박의 요지 | 심각도 | 권고 변경 |
|---|---|---|---|---|
| **CausalArmor식 인과 조건부 개입** | Influence Is Not Authority ([2608.29942](https://arxiv.org/abs/2608.29942)) | **인과성 ≠ 권한.** 정당한 툴 사용을 공격으로 오판. 24개 케이스 **전부**에서 오탐 발생 | 🔴 **치명적** | ⬇️ **강등** — 단독 사용 금지 |
| **Tool Filter** | ToolHijacker (NDSS 2026, [2504.19793](https://arxiv.org/abs/2504.19793)) | 툴 **선택 단계 자체**를 조작. MetaTool ASR **96.43%**, StruQ 하 **99.71%** | 🔴 **치명적** | ⚠️ **전제 조건 추가** |
| **Meta SecAlign (모델레벨 방어)** | PISmith ([2603.13026](https://arxiv.org/abs/2603.13026)) | RL 레드팀이 Meta-SecAlign-8B를 **ASR@10 = 1.0(100%)**, ASR@1 = 0.87로 격파 | 🔴 **치명적** | ⬇️ **단독 신뢰 금지** |
| **PIShield / Attention Tracker (내부표현)** | Evasive Injections ([2602.00750](https://arxiv.org/abs/2602.00750)) | multi-probe 회피 suffix로 **모든 레이어 probe 동시 회피**. Llama-3 8B **99.63%** | 🔴 **치명적** | ⚠️ **위협모델 한정** |
| **Prompt Guard 2 / 소형 분류기** | Bypassing LLM Guardrails ([2504.11168](https://arxiv.org/abs/2504.11168)) · Controlled-Release Prompting ([2510.01529](https://arxiv.org/abs/2510.01529)) | 유니코드 문자 주입으로 **최대 100% 회피**. 프로덕션 4개 플랫폼 우회 | 🟠 **심각** | ⚠️ **전처리 필수화** |
| **Spotlighting** | Domain-Camouflaged Injection ([2606.18530](https://arxiv.org/abs/2606.18530)) | **모델 의존적** — Llama 3.1 8B에서 **효과 없음**. 금융 도메인 잔존 ASR 26–33% | 🟠 **심각** | ⚠️ **모델별 검증** |
| **Instruction Hierarchy (역할 배치)** | Where Instruction Hierarchy Breaks ([2606.07808](https://arxiv.org/abs/2606.07808)) · ChatInject ([2509.22830](https://arxiv.org/abs/2509.22830)) | 추론 모델에서 IH가 3가지 메커니즘으로 붕괴. 적응형 공격 하 개선폭 **45%에 그침** | 🟠 **심각** | ⚠️ **보조 수단으로 격하** |
| **FIDES (정보흐름 통제)** | Ghost in the Agent 계열 ([2604.23374](https://arxiv.org/abs/2604.23374)) | **label creep** — 보수적 전파로 에이전트가 사용 불가해짐. 비교 평가에서 **F1 0.522** | 🟠 **심각** | ⚠️ **declassification 설계 필수** |
| **LlamaFirewall / AlignmentCheck** | Breaking and Fixing Control-Flow Hijacking ([2510.17276](https://arxiv.org/abs/2510.17276)) | "정합성" 정의가 취약하고 실행 컨텍스트 가시성이 불완전 → 우회 | 🟠 **심각** | ⚠️ **CFI 방식 병용** |
| **CaMeL** | Operationalizing CaMeL ([2505.22852](https://arxiv.org/abs/2505.22852)) | 신뢰 사용자 가정, 사이드채널 무시, **모델 호출 2배** | 🟠 **심각** | (이미 전면 도입 비추천) |
| **Progent (1순위)** | 자체 논문 적응형 공격 절 · SEAgent ([2601.11893](https://arxiv.org/abs/2601.11893)) · SoK ([2511.15203](https://arxiv.org/abs/2511.15203)) | 적응형 공격 시 ASR 4.0%. **툴 호출 단계에만 한정** — 텍스트 출력·멀티에이전트 위임 미커버 | 🟡 **제한적** | ✅ **1순위 유지** (범위 명시) |
| **MELON** | 자체 논문 한계 절 · SoK | 모델 호출 **2배** → API 비용 2배. 관련 툴만으로 공격 설계 시 우회 여지 | 🟡 **제한적** | ✅ 유지 |

### 가장 중요한 3가지 발견

1. **원 리포트가 "지연·유틸리티 최상위 후보"로 소개한 CausalArmor가 가장 강하게 반박당했다.** [Influence Is Not Authority](https://arxiv.org/abs/2608.29942)의 실험 설계가 특히 뼈아프다 — 권한 상태·행동·의도된 결과를 모두 고정한 채 **"필요한 값이 사용자 입력에서 오는가, 정당한 툴 결과에서 오는가"만 바꿨는데 24개 케이스 전부에서 인과 신호가 공격 영역으로 이동**했다. 유틸리티 보존이 최우선 기준인 상황에서 이는 채택 불가 판정에 가깝다.

2. **모델레벨 방어(Meta SecAlign)에 대한 반박이 예상보다 훨씬 강력하다.** 원 리포트는 Autonomy Tax(유틸리티 손상)를 근거로 경고했지만, PISmith는 **보안성 자체가 무너진다**는 것을 보였다. Dolly Closed QA 100 샘플만으로 학습한 RL 공격자가 12개 미학습 벤치마크에 일반화해 **ASR@10 = 1.0**을 달성했다.

3. **1순위 추천이었던 Progent는 반박을 견뎠다.** 발견된 반박들은 "설계 전제 붕괴"가 아니라 **"적용 범위의 한계"**(툴 호출 단계에 한정, 정책 작성자의 실수 의존)에 관한 것이다. **결정론적 정책 강제라는 방향성 자체는 반박되지 않았고**, 오히려 반박 논문들이 제안하는 대안(ControlValve, SEAgent)도 모두 같은 방향이다.

---

## 1. 조사 방법

- **대상**: 원 리포트의 시나리오별 추천 조합(§11.1)과 도입 로드맵(§11.3)에 포함된 12개 기법
- **검색 축**: ① 해당 기법을 명시적으로 공격/우회하는 논문, ② 해당 기법 **계열 전체**의 전제를 반박하는 논문, ③ 해당 기법 논문 자체의 한계(limitations) 절
- **심각도 기준**:
  - 🔴 **치명적** — 방어의 **설계 전제 자체**가 무너짐. 파라미터 조정으로 해결 불가
  - 🟠 **심각** — 특정 조건(모델 크기, 공격자 지식 수준, 도메인)에서 무력화. 조건을 통제하면 사용 가능
  - 🟡 **제한적** — 적용 범위·비용의 한계. 방어 자체는 유효

> **주의**: 반박 논문 역시 자가보고 수치를 제시하며, 방어 논문과 마찬가지로 유리한 설정을 선택했을 가능성이 있다. 특히 화이트박스 가정(모델 가중치·방어 구조를 공격자가 아는 경우)의 결과는 **자사 위협모델에 해당하는지 먼저 판단**해야 한다.

---

## 2. 치명적 반박 (설계 전제가 무너지는 경우)

### 2.1 CausalArmor식 인과 조건부 개입 → **Influence Is Not Authority**

**반박 논문**: *Influence Is Not Authority: When Causal Guardrail Signals Make Legitimate Tool Use Look Like an Attack in Tool-Using LLM Agents* — [arXiv:2608.29942](https://arxiv.org/abs/2608.29942)

#### 무엇을 반박하는가
원 리포트가 §7.2(5)와 Phase 4 권고에서 채택한 **인과 기여도(LOO attribution) 기반 조건부 개입** 계열 전체. CausalArmor의 핵심 신호인 "dominance shift"가 표적이다.

#### 핵심 논리
> **인과성(causality)과 권한(authorization)을 혼동하고 있다.**

인과 신호는 "무엇이 이 행동을 형성했는가"를 알려줄 뿐, **"이 행동이 승인된 것인가"를 신뢰성 있게 인코딩하지 못한다.** 사용자가 정당하게 승인한 행동이라도 필요한 값이 툴 결과에서 온다면, 그 툴 결과가 인과적으로 행동을 지배하게 된다 — 공격과 구분되지 않는다.

#### 실험 설계 (이 부분이 결정적)
**authorization-equivalence audit** — 24개 base case에서 96개 조건을 구성하되:
- **고정**: 권한 상태, 수행 행동, 의도된 효과
- **변경**: 필요한 값의 출처만 (사용자 입력 ↔ 정당한 툴 결과)

즉 **"똑같이 승인된 똑같은 행동"인데 데이터 위치만 옮긴 것**이다.

#### 결과
- Llama·Gemma 스코어러 **양쪽 모두에서, 24개 케이스 전부** 인과 신호가 "공격 영역"으로 이동
- **semantic monitor: 유틸리티 28%** (오탐 과다)
- **shadow-based guardrail: 승인된 실행의 29.2%가 자동 검사에 실패(오탐)**, 반대로 **미승인 실행의 57.5%는 통과(미탐)**

#### 평가
- **심각도: 🔴 치명적.** 파라미터 τ를 조정해 해결할 수 있는 문제가 아니다. 신호 자체가 판별하려는 속성을 담고 있지 않다.
- 특히 **오탐 29.2%**는 유틸리티 최우선 기준과 정면으로 충돌한다.
- CausalArmor 자가보고(유틸 70.96%, 지연 1.38×)와의 격차가 크므로, **자체 재현 없이는 절대 채택 불가**.

#### 권고 변경
> **Phase 4의 "CausalArmor식 조건부 판정"을 강등한다.** 조건부 개입이라는 **설계 원칙(항시 검사 대신 위험 시점에만 검사)은 유지**하되, **트리거 신호를 인과 기여도가 아니라 명시적 권한 메타데이터**(어떤 툴/인자가 사용자 승인 범위에 있는가)로 대체해야 한다. 이는 결국 Progent식 정책 강제와 같은 방향이다.

---

### 2.2 Tool Filter → **ToolHijacker**

**반박 논문**: *Prompt Injection Attack to Tool Selection in LLM Agents* (NDSS 2026) — [arXiv:2504.19793](https://arxiv.org/abs/2504.19793)

#### 무엇을 반박하는가
원 리포트가 §5.2(3)에서 **"비용이 마이너스인 방어"**(토큰 0.62×, 시간 0.89×)로 극찬하며 Phase 1 필수 항목으로 넣은 Tool Filter.

#### 핵심 논리
Tool Filter는 **"사용자 태스크에 필요한 툴만 남긴다"**는 전제 위에 서 있다. 그런데 **"필요한 툴"을 고르는 과정 자체가 공격 대상**이라면 이 전제가 무너진다.

#### 공격 방법 — ToolHijacker
- **위협 모델**: **no-box** — 공격자가 대상 에이전트의 retriever·LLM·툴 라이브러리 내부를 모른다 (현실적 가정)
- **방법**: 악성 **툴 문서(tool document)**를 툴 라이브러리에 주입. 툴 선택의 2단계(retrieval → selection) 양쪽을 겨냥한 **2단계 최적화 문제**로 정식화
- **효과**: 공격자가 지정한 타깃 태스크에 대해 에이전트가 **일관되게 악성 툴을 선택**하도록 강제

#### 결과
| 조건 | ASR |
|---|---|
| MetaTool, shadow LLM = Llama-3.3-70B, 타깃 = GPT-4o, gradient-free | **96.43%** |
| **StruQ 방어 적용 하** (gradient-free) | **99.71%** |

논문은 예방형 방어(StruQ, SecAlign)와 탐지형 방어(known-answer detection, DataSentinel, perplexity, windowed perplexity)를 모두 평가했고, **어느 것도 충분하지 않다**고 결론지었다.

#### 평가
- **심각도: 🔴 치명적** — 단, **툴 라이브러리가 오염 가능한 경우에 한한다.**
- 자사 툴셋이 **전부 내부에서 정의·관리되고 제3자 등록이 불가능하다면** 이 공격은 성립하지 않는다.
- 반대로 **MCP 서버, 서드파티 플러그인, 동적 툴 등록을 허용한다면 Tool Filter는 방어가 아니라 공격 표면**이 된다.

#### 권고 변경
> **Tool Filter 도입에 전제 조건을 추가한다**: ① 툴 문서·설명의 **무결성 검증**(서명·해시), ② 툴 등록 경로의 **화이트리스트화**, ③ 서드파티 MCP 툴은 별도 신뢰 등급으로 분리. 이 세 가지 없이 Tool Filter만 적용하면 **보안 효과가 없거나 오히려 악화**될 수 있다.

---

### 2.3 Meta SecAlign / 모델레벨 방어 → **PISmith**

**반박 논문**: *PISmith: Reinforcement Learning-based Red Teaming for Prompt Injection Defenses* — [arXiv:2603.13026](https://arxiv.org/abs/2603.13026)

#### 무엇을 반박하는가
원 리포트 §11.1 시나리오 B(오픈웨이트 self-host)의 **L0 베이스 레이어 = Meta-SecAlign-70B** 권고. 원 리포트는 이 카테고리를 "유틸리티 리스크"(Autonomy Tax) 관점에서 경고했으나, PISmith는 **보안성 자체를 반박한다.**

#### 공격 방법
- **블랙박스 RL 레드팀** — 공격 LLM을 학습시켜 방어된 모델에 질의하고 출력을 관찰하며 주입 프롬프트를 최적화
- **기술적 기여**: 극심한 보상 희소성(대부분의 주입이 차단됨)을 **적응형 엔트로피 정규화 + 동적 어드밴티지 가중**으로 해결해 희귀한 성공에서 학습을 증폭

#### 결과 — Meta-SecAlign-8B 대상
| 지표 | 값 |
|---|---|
| **ASR@10** (10회 시도) | **1.0 (100%)** |
| **ASR@1** (단 1회 시도) | **0.87 (87%)** |
| 학습 데이터 | Dolly Closed QA **100 샘플만** |
| 일반화 | **12개 미학습 벤치마크 전부** |
| 베이스라인 대비 (HotpotQA-Long) | PISmith 0.99/0.61 vs RL-Hammer 0.04/0.01 |

평가 대상 방어는 예방형(Sandwich, Instructional, PromptArmor, DataFilter), 필터형(PIGuard, PromptGuard, DataSentinel), 정렬형(Meta-SecAlign-8B)을 포괄한다.

**핵심 결론**: *"어떤 방어도 높은 유틸리티와 낮은 ASR을 동시에 달성하지 못했다"* — 근본적인 **utility-robustness trade-off**.

#### 보강 반박 (원 리포트에 이미 일부 수록)
| 논문 | 발견 |
|---|---|
| Architecture-Aware Attacks ([2507.07417](https://arxiv.org/abs/2507.07417)) | **역할 토큰 분리와 행동 선호 최적화에만 의존하는 방어는 화이트박스 위협모델에서 강건하지 않다.** SecAlign·StruQ 격파 |
| ToolHijacker ([2504.19793](https://arxiv.org/abs/2504.19793)) | StruQ 하 ASR **99.71%**, SecAlign도 방어 실패 |
| Checkpoint-GCG ([2505.15738](https://arxiv.org/abs/2505.15738)) | 파인튜닝 중간 체크포인트를 이용한 감사·공격 |
| Surface Heuristics ([2601.07185](https://arxiv.org/abs/2601.07185)) | 의미 이해가 아닌 표면 패턴만 학습 |
| The Autonomy Tax ([2603.19423](https://arxiv.org/abs/2603.19423)) | benign Step-1 실패율 3% → 47~77% |

#### 평가
- **심각도: 🔴 치명적.** 원 논문의 ASR 2.1%(AgentDojo)는 **정적 공격 세트 기준**이었다. 적응형 공격자를 상정하면 사실상 무방어에 가깝다.
- 다만 **PISmith는 8B 모델을 대상으로 했다.** 70B에서도 동일한지는 확인되지 않았으므로 그대로 외삽해선 안 된다. 그러나 **방어 원리가 같으므로 낙관할 근거도 없다.**

#### 권고 변경
> **시나리오 B에서 Meta SecAlign을 "베이스 레이어"라고 부르지 말 것.** 이는 **런타임 비용 0의 보너스 계층**일 뿐이며, 실질 방어선은 여전히 Progent식 정책 강제여야 한다. 원 리포트의 "파인튜닝 단독 채택 금지" 권고는 유지되며, **근거가 유틸리티 리스크에서 보안성 붕괴로 격상**된다.

---

### 2.4 PIShield / Attention Tracker (내부표현 기반 탐지) → **Evasive Injections**

**반박 논문**: *Bypassing Prompt Injection Detectors through Evasive Injections* — [arXiv:2602.00750](https://arxiv.org/abs/2602.00750)

#### 무엇을 반박하는가
원 리포트가 §4에서 **"지연 관점 최우수군"**으로 평가하고 시나리오 B의 L2로 추천한 activation/hidden-state 기반 탐지 계열.

#### 공격 방법 — Multi-Probe Evasion
- 오염된 입력에 **적대적으로 최적화된 suffix**를 덧붙인다
- **GCG(Greedy Coordinate Gradient) 변형**으로, **모든 레이어별 drift detector의 손실 gradient를 동시에 누적**해 **범용(universal) suffix** 하나를 최적화
- 목표: LLM의 내부 activation이 **benign 입력의 분포를 흉내내도록 강제**하면서 주입의 효력은 유지

#### 결과
| 모델 | 모든 탐지기 동시 회피 성공률 |
|---|---|
| Phi-3 3.8B | **93.91%** |
| Llama-3 8B | **99.63%** |

#### 평가
- **심각도: 🔴 치명적** — 단, **화이트박스 가정에 한한다.** 공격자가 모델 가중치와 probe 위치를 알아야 GCG 최적화가 가능하다.
- 아이러니: 내부표현 기반 탐지는 **self-host(가중치 보유)에서만 쓸 수 있는데**, 가중치가 유출되거나 오픈웨이트 모델을 쓰면 **공격자도 같은 접근권을 얻는다.** 오픈모델을 쓰면 이 가정은 자동으로 성립한다.
- 논문은 대응책으로 **adversarial suffix augmentation**(학습 시 무작위 suffix 다수 삽입)을 제안하나, GCG 계열 공방의 통상적 결과처럼 근본 해결은 아니다.

#### 권고 변경
> **오픈웨이트 모델(Llama 등) 사용 시 내부표현 탐지를 주 방어선으로 삼지 말 것.** 공격자가 동일 가중치를 다운로드해 회피 suffix를 최적화할 수 있다. **비공개 파인튜닝 모델**을 쓰는 경우에 한해 유효한 계층으로 취급한다.

---

## 3. 심각한 반박 (조건부 무력화)

### 3.1 Prompt Guard 2 / 소형 분류기 → **문자 주입 + Controlled-Release**

#### (1) *Bypassing LLM Guardrails: An Empirical Analysis of Evasion Attacks* (ACL LLMSec 2025) — [arXiv:2504.11168](https://arxiv.org/abs/2504.11168)

- **공격 1 — 문자 주입(Character Injection)**: 유니코드 조작으로 분류기가 인지하는 텍스트를 난독화
  - zero-width 문자 삽입, **homoglyph**(시각적 동일 문자) 치환, leetspeak, diacritics 추가, underline, **전각(full-width) 변환**, **양방향 텍스트(bidi)**
- **공격 2 — AML 회피**: TextAttack 라이브러리로 적대적 예제 생성
- **결과**: **Azure Prompt Shield와 Meta Prompt Guard를 포함한 6개 주요 보호 시스템**에서, 공격 효력을 유지한 채 **일부 경우 100% 회피 성공**

#### (2) *Bypassing Prompt Guards in Production with Controlled-Release Prompting* — [arXiv:2510.01529](https://arxiv.org/abs/2510.01529)

- **핵심 착안**: 경량 필터와 그것이 보호하는 대형 LLM 사이의 **계산 능력 격차**를 악용
- **방법**: **어떤 유계(bounded) 필터도 해독할 수 없지만 대상 LLM은 이해할 수 있는** 프롬프트를 생성. 모델 수정 불필요
- **결과**: **Google Gemini, DeepSeek Chat, xAI Grok, Mistral Le Chat** 등 프로덕션 플랫폼 4곳 우회 성공(베이스라인 방법들은 실패). Gemini에서 데이터 추출까지 시연. **14개 오픈웨이트 guard 모델 평가 결과, 추론 능력이 있는 필터조차 상당한 계산 오버헤드 없이는 탐지 실패**

#### 평가 및 권고 변경
- **심각도: 🟠 심각.** 원 리포트는 이미 소형 분류기를 "1차 필터로만" 쓰라고 했으므로 **방향은 유효하나 근거가 크게 강화**된다.
- 여기에 원 리포트에 있던 NotInject 과방어 문제(오픈소스 가드레일 과방어 정확도 60% 미만)를 더하면, **소형 분류기는 오탐과 미탐 양쪽에서 모두 취약**하다.

> **권고 추가**: 분류기 앞단에 **유니코드 정규화(NFKC), zero-width 문자 제거, homoglyph 정규화, 전각→반각 변환, bidi 제어문자 제거** 전처리를 **반드시** 넣는다. 이것 없이 Prompt Guard를 붙이는 것은 **보안 착시**다. 또한 **"경량 필터로 대형 LLM을 보호한다"는 구조 자체에 계산 비대칭 한계**가 있음을 인지하고, 필터를 최종 방어선으로 두지 않는다.

---

### 3.2 Spotlighting → **Domain-Camouflaged Injection**

**반박 논문**: *Evaluating Prompting-Based Defenses Against Domain-Camouflaged Injection Attacks* — [arXiv:2606.18530](https://arxiv.org/abs/2606.18530)

#### 무엇을 반박하는가
원 리포트가 Phase 1 필수 항목으로 넣고 "ASR >50% → <2%"라고 인용한 Spotlighting.

#### 실험 규모
**3,510 trials** × 3개 모델 계열(Claude Haiku, Llama 3.1 8B, Gemini 2.0 Flash) × 3개 배포 도메인, 합성 문서 기반

#### 결과
| 발견 | 내용 |
|---|---|
| **모델 의존성** | Spotlighting은 **Claude Haiku에서는 공격 성공률을 절반으로** 낮추지만, **Llama 3.1 8B에서는 아무런 이득이 없다** |
| **최고 성능 방어** | **Paraphrasing**이 모델에 따라 **55–84% 감소**로 가장 효과적 |
| **잔존 위험** | **금융 도메인이 가장 취약** — baseline ASR **26–33%** |
| **총평** | **약한 모델에서는 어떤 프롬프팅 기반 방어도 위협을 완전히 제거하지 못한다** |

#### 이 결과가 원 리포트와 충돌하는 지점
원 리포트는 §5.2 "고전 베이스라인(참고용)"에서 **Paraphrasing을 "유틸리티 손실이 커 실무 부적합"으로 배제**했다. 그런데 이 논문에서는 **paraphrasing이 최고 성능**이다. 도메인 위장 공격에 한정된 결과이나, **배제 판단을 재검토할 필요**가 있다.

#### 평가 및 권고 변경
- **심각도: 🟠 심각.** Spotlighting은 여전히 비용 대비 효과가 있지만 **"어느 모델에서나 통한다"는 가정은 틀렸다.**

> **권고 변경**: ① Spotlighting 효과는 **사용 모델별로 반드시 자체 측정**한다. 특히 소형 모델·비영어 환경에서는 효과 없음을 기본 가정으로 둔다. ② **금융·결제 등 고위험 도메인**은 프롬프팅 방어만으로 커버되지 않는다고 간주하고 정책 강제 계층을 필수화한다. ③ **RAG 검색 결과에 한해 paraphrasing 적용**을 재검토한다(유틸리티 영향은 자체 측정).

---

### 3.3 Instruction Hierarchy → **IH Breaks + ChatInject**

#### (1) *Where Instruction Hierarchy Breaks: Diagnosing and Repairing Failures in Reasoning Language Models* — [arXiv:2606.07808](https://arxiv.org/abs/2606.07808)

원 리포트는 §6.2(4)에서 **"메시지 역할만 올바르게 배치해도 비용 0으로 이득을 얻는다"**고 권고했다. 이 논문은 **추론 모델(reasoning LM)에서 그 전제가 깨진다**는 것을 보인다.

**3가지 실패 메커니즘**:
1. **지시 식별 실패** — 컨텍스트에서 관련 지시를 인식하지 못함
2. **충돌 해소 실패** — 경합하는 지시 간 우선순위 판단 실패
3. **응답 실현 실패** — **추론은 올바르게 했는데도 위반하는 출력을 생성**

**모델별로 지배적 실패 모드가 다르다** (Gemma-4-31B-IT, Qwen3.6-35B-A3B, Claude Sonnet 4.6에서 상이). 태스크와 컨텍스트 길이에 따라서도 달라진다.

**중요한 수치**: 저자들이 제안한 자체 모니터링 기법을 적용해도 **GPT-5.3 기준 정적 공격에서는 86% 감소하지만 적응형 공격에서는 45% 감소에 그친다.**

#### (2) *ChatInject: Abusing Chat Templates for Prompt Injection in LLM Agents* — [arXiv:2509.22830](https://arxiv.org/abs/2509.22830)
- **채팅 템플릿 자체를 악용**해 주입. 역할 구분이 결국 **텍스트 템플릿으로 구현**된다는 점을 공격
- → **"역할을 올바르게 배치하면 안전하다"는 가정의 구현 레벨 반박**

#### 평가 및 권고 변경
- **심각도: 🟠 심각.**

> **권고 변경**: Instruction Hierarchy 활용(역할 정확 배치)은 **비용이 0이므로 계속 유지**하되, **"방어 계층"이 아니라 "위생 수칙(hygiene)"으로 재분류**한다. Phase 1 목록에는 남기되 ASR 감소를 기대하지 않는다. 추가로 **채팅 템플릿 구분자 문자열이 사용자·툴 데이터에 그대로 들어가지 않도록 이스케이프**하는 처리를 넣는다.

---

### 3.4 FIDES / 정보흐름 통제 → **Label Creep**

**반박 문헌**: *Ghost in the Agent: Redefining Information Flow Tracking for LLM Agents* — [arXiv:2604.23374](https://arxiv.org/abs/2604.23374) 계열

#### 핵심 비판
1. **과도한 보수적 전파(over-tainting)** — FIDES는 라벨을 permissive하게 전파해 **응답이 모든 입력 메시지와 툴 선언에 의해 오염**된다. 이는 **건전(sound)하지만 지나치게 보수적**이다.
2. **Label creep** — 보수적 전파가 누적되면 **자동화되고 안전한 declassification 규칙을 설계하지 않는 한 에이전트가 사용 불가능해진다.**
3. **근본적 부적합** — 프로그램 메모리 상태를 위해 설계된 전통적 taint 분석은, **확률적 자연어 추론으로 데이터가 전파되는 LLM에는 원리적으로 맞지 않는다.** 지시·비공개 컨텍스트·검색 데이터·툴 관측·이전 출력이 **연속적 신경 연산 안에서 섞이는데**, 전통적 IFC 이론은 라벨이 LLM 호출을 어떻게 통과해야 하는지 규정하지 않는다.

#### 정량 비교 (⚠️ 재확인 권장)
후속 연구의 비교 평가에서 FIDES는 TaintBench 400개 시나리오 기준 **source-to-sink 전파 탐지 F1 = 0.522**(비교 기법 0.928), **false positive 106건 / false negative 92건**으로 보고된다. FP는 **source–sink 경로의 존재만으로 전파를 강하게 추정**하기 때문에 비전파 경로에서 대량 발생한다.

> **주의**: 이 수치는 경쟁 기법을 제안하는 논문의 비교 실험 결과이므로 **자기 유리 편향 가능성**이 있다. 도입 검토 시 자사 워크로드로 재현 필요.

#### 평가 및 권고 변경
- **심각도: 🟠 심각.** 특히 **유틸리티 보존이 최우선 기준**인 상황에서 label creep과 FP 106건은 무시할 수 없다.

> **권고 변경**: FIDES 도입 시 **declassification(라벨 해제) 규칙 설계가 성패를 좌우**한다. 도입 전에 반드시 ① 자사 워크플로우에서 어떤 경로가 declassify 되어야 하는지 목록화, ② 라벨 전파 시뮬레이션으로 **얼마나 많은 정상 흐름이 차단되는지 사전 측정**해야 한다. "라벨만 붙이면 된다"는 접근은 실패한다.

---

### 3.5 LlamaFirewall / AlignmentCheck → **Control-Flow Hijacking**

**반박 논문**: *Breaking and Fixing Defenses Against Control-Flow Hijacking in Multi-Agent Systems* — [arXiv:2510.17276](https://arxiv.org/abs/2510.17276)

#### 무엇을 반박하는가
**LlamaFirewall을 명시적으로 지목**한다. 대상은 *"에이전트 간 통신의 정합성 검사에 의존해, 모든 에이전트 호출이 원래 목표와 '관련되어 있고' 그것을 '진전시킬 가능성이 높은지' 확인하는"* 정렬 기반 방어 전체다.

#### 두 가지 근본 약점
1. **"정합성(alignment)" 정의의 취약성** — "관련 있음"과 "목표를 진전시킴"은 자연어 판단이며, 공격자가 그럴듯한 연결고리를 만들면 통과한다
2. **검사 시점의 실행 컨텍스트 가시성 불완전** — 판정기가 전체 실행 상태를 보지 못한다

#### 대안 제안 — ControlValve
제어 흐름 무결성(CFI)에서 착안. **허용된 제어 흐름 그래프를 생성**하고 모든 실행이 그래프를 준수하도록 강제하며, 각 에이전트 호출에 대해 **zero-shot으로 생성된 문맥 규칙**을 함께 적용한다.

#### 평가 및 권고 변경
- **심각도: 🟠 심각.** 원 리포트가 인용한 LlamaFirewall 자가보고 ASR 1.75%는 **SoK 재현치 8.28%**와 이미 격차가 있었는데, 이 논문이 그 원인을 설명해준다.

> **권고 변경**: AlignmentCheck 같은 **LLM 자연어 정합성 판정을 단독 게이트로 쓰지 말 것.** ControlValve/IPIGuard처럼 **구조적 제약(허용된 호출 그래프)**과 병용해야 한다. 이는 원 리포트의 "결정론적 계층 우선" 결론과 일치한다.

---

### 3.6 CaMeL → **Operationalizing CaMeL**

**반박 논문**: *Operationalizing CaMeL: Strengthening LLM Defenses for Enterprise Deployment* — [arXiv:2505.22852](https://arxiv.org/abs/2505.22852)

#### 지적된 3대 갭
1. **신뢰 사용자 가정** — CaMeL은 **초기 프롬프트가 benign하다고 전제**한다. 악의적 사용자 입력에 취약
2. **사이드채널 무시** — 간접적 공격 벡터를 다루지 않음
3. **성능 저하** — dual-LLM 구조가 운영 비효율을 만든다. **모델 호출 수가 사실상 2배**

#### 보강 지적
- 정책 관리의 복잡성, 인터프리터 언어 의미론의 한계
- SoK 재현 실측: **유틸 57.41%(무방어 80.41%), Travel 도메인 25.00%, 응답시간 18.81s**

#### 제안된 보완
프롬프트 스크리닝, 출력 감사(지시 유출 탐지), **계층적 위험 접근 모델**, 형식 증명이 가능한 검증된 중간 언어

#### 평가
- **심각도: 🟠 심각.** 원 리포트는 이미 **"CaMeL 전면 적용 비추천, 아이디어만 채택"**이라고 결론지었으므로 **권고 변경 없음.** 이 반박은 그 판단을 뒷받침한다.

---

## 4. 제한적 반박 (부분 약화·비용 문제)

### 4.1 Progent (1순위 추천) — 범위의 한계

원 리포트의 **1순위 추천이 가장 잘 버텼다.** 발견된 반박은 설계 전제가 아니라 **적용 범위**에 관한 것이다.

| 출처 | 지적 내용 |
|---|---|
| **Progent 논문 자체** (적응형 공격 절) | Progent 배포를 아는 공격자는 **정책 갱신 과정을 교란**하거나 **공격 태스크에 필요한 툴 호출을 정책에 포함시키도록 유도**할 수 있다. 다만 정책 생성 LLM에 대한 적응형 공격 하에서도 **ASR은 4.0%까지만 상승** |
| **Progent 논문 자체** (한계 절) | ① **결정론적 SMT 기반 검사를 쓰지만 사용자의 실수가 보안 보장을 훼손**할 수 있다 — 사용자가 권한 확대(widening) 갱신을 잘못 승인하거나 초기 태스크를 모호하게 주면 최소권한을 초과하는 정책이 허용된다. ② **툴 호출 단계에 집중** → **텍스트 출력을 겨냥한 공격은 미대응**. ③ **원자적 에이전트-툴 상호작용에 국한** → 더 넓은 공격 벡터를 놓친다 |
| **SoK** ([2511.15203](https://arxiv.org/abs/2511.15203)) | 6대 근본원인 중 **#1 툴 선택 접근제어 부정확, #2 툴 인자 접근제어 부정확, #5 정책 커버리지 부족**이 정책 강제 계열의 구조적 약점. **Semantic-Masquerading IPI**가 툴 선택·인자 결함을 노려 특정 프레임워크에서 **ASR 최대 4배 증가** |
| **SEAgent** ([2601.11893](https://arxiv.org/abs/2601.11893)) | 자연어 기반 과권한 툴 사용, **멀티에이전트 시스템 고유 취약점**, **confused deputy 문제 변종**을 권한 상승 벡터로 제시. ABAC + 정보흐름 그래프 기반 MAC를 대안으로 제안 |
| **ToolHijacker** ([2504.19793](https://arxiv.org/abs/2504.19793)) | 정책이 **"어떤 툴을 허용할지"를 툴 이름으로 지정**한다면, 악성 툴이 정당한 이름으로 등록될 때 우회 가능 |

#### 평가
- **심각도: 🟡 제한적.** 적응형 공격 하 ASR 4.0%는 다른 어떤 방어보다 좋은 수치다.
- **하지만 커버 범위를 명확히 인식해야 한다**: Progent는 **툴 호출 채널**을 지킨다. 다음은 지키지 못한다:
  - 텍스트 출력을 통한 정보 유출 (에이전트가 사용자에게 보여주는 응답에 민감정보를 담는 경우)
  - 멀티에이전트 간 위임 경로
  - 툴 라이브러리 자체의 오염
  - 정책 작성자의 판단 착오

#### 권고
> **1순위 추천 유지.** 단 문서에 **"Progent는 툴 호출 채널 방어이며, 출력 채널·멀티에이전트 위임·툴 라이브러리 무결성은 별도 통제가 필요하다"**를 명시한다. 출력 채널은 FIDES식 confidentiality 라벨로, 툴 라이브러리는 등록 화이트리스트로 보완한다.

---

### 4.2 MELON — 비용 2배와 회피 여지

| 출처 | 지적 |
|---|---|
| **MELON 논문 자체** | **instruction-seeking path 도입으로 필요한 모델 호출 수가 2배** → 무방어 대비 **API 비용 약 2배** |
| **MELON 논문의 관련 연구 논의** | 일부 방어는 **공격자가 사용자 태스크와 관련된 툴만으로 공격 태스크를 설계하면 우회 가능**하다 — MELON의 "마스킹 후 행동 유사성" 판정도 원리상 같은 회피에 노출된다 |
| **SoK 재현** | 토큰 53,247 (무방어 8,020 대비 **6.6배**), 응답시간 13.48s (**2.8배**) |

#### 평가
- **심각도: 🟡 제한적.** 보안 성능(SoK ASR 2.29%)은 좋지만 **비용 6.6배는 사용자의 비용 기준에서 부담**이다.
- 원 리포트에서 5위로 배치한 것은 타당했다. **주력이 아닌 고위험 경로 전용으로 한정** 사용.

---

### 4.3 Task Shield — (참고) 이미 비추천

SoK의 **Cascading IPI** 공격이 "판정 LLM의 오판"을 노려 **ASR을 거의 5배 증가**시킨다. 원 리포트가 비용(토큰 73.9배)을 이유로 이미 채택 제외했으므로 권고 변경 없음. **LLM 판정기 계열의 공통 약점**이라는 점만 기록한다.

---

## 5. 횡단적 반박 — 모든 기법에 공통 적용

### 5.1 "적응형 공격 하에서 살아남는 방어는 아직 없다"

| 논문 | 결론 |
|---|---|
| **PISmith** ([2603.13026](https://arxiv.org/abs/2603.13026)) | 13개 벤치마크, 7개 베이스라인 대비 우위. **"기존 방어들의 강건성 평가가 불충분하며 실제 LLM 애플리케이션에 거짓 안전감(false sense of security)을 만든다"** |
| **A Critical Evaluation** ([2505.18333](https://arxiv.org/abs/2505.18333)) | 적응형 공격 + 일반 능력 보존 두 축 누락 |
| **Adaptive Attacks Break Defenses** ([2503.00061](https://arxiv.org/abs/2503.00061)) | 8개 방어 전부 우회, ASR >50% |
| **SoK** ([2511.15203](https://arxiv.org/abs/2511.15203)) | 최신 프레임워크에서 6대 근본원인 + 3종 신규 공격 + 제로데이 |
| **Assessing Automated PI Attacks in Agentic Environments** ([2606.10525](https://arxiv.org/abs/2606.10525)) | 자동화 공격의 에이전트 환경 적용 평가 |
| **PI-Hunter** ([2606.12737](https://arxiv.org/abs/2606.12737)) | 자동 레드팀으로 주입 노출·위치 특정 |

### 5.2 utility-robustness trade-off는 근본적일 가능성

PISmith의 결론이 특히 무겁다:

> **"어떤 방어도 높은 유틸리티와 낮은 ASR을 동시에 달성하지 못했다."**

원 리포트 §9.2의 랭킹표에서 **Progent만이 이 trade-off를 벗어난 것처럼 보였는데**(ASR 0.00% + 토큰 0.97× + 지연 0.79×, 유틸 -7.8%p), 이는 **Progent가 "에이전트가 할 수 있는 일의 범위를 사전에 좁혔기 때문"**이다. Design Patterns 논문([2506.08837](https://arxiv.org/abs/2506.08837))의 통찰과 일치한다 — **"에이전트가 임의의 태스크를 풀 수 없도록 제한하는 것이 좋은 타협점"**.

즉 **trade-off를 없앤 것이 아니라 "자율성"이라는 제3의 축으로 대가를 옮긴 것**이다. 이는 원 리포트에서 명시적으로 다루지 않은 관점이며, **도입 시 "우리 에이전트가 얼마나 자유로워야 하는가"를 먼저 정의해야 한다**는 뜻이다.

### 5.3 계층 방어도 자동으로 안전하지 않다

원 리포트의 핵심 권고는 계층 방어였다. 이에 대한 반박은 직접적이지 않지만 다음을 유의해야 한다:
- LlamaFirewall(PromptGuard 2 + AlignmentCheck)은 **이미 2계층 조합인데도** [2510.17276](https://arxiv.org/abs/2510.17276)에 우회당했다
- 계층들이 **동일한 신호에 의존하면 상관된 실패**가 발생한다. 예: 소형 분류기와 LLM 판정기가 모두 "자연어 의미"에 의존 → 문자 주입 공격에 **동시 무력화**
- **서로 다른 원리에 기반한 계층**(구문 정규화 / 결정론적 정책 / 의미 판정)을 조합해야 실질적 다중화가 된다

---

## 6. 반박 논문들이 제안한 대안 기법

반박 논문 대부분은 대안을 함께 제시한다. **다음 라운드 검토 후보**로 기록한다.

| 대안 | 출처 | 아이디어 | 원 리포트 대비 위치 |
|---|---|---|---|
| **ControlValve** | [2510.17276](https://arxiv.org/abs/2510.17276) | 허용된 **제어 흐름 그래프** 생성 + 준수 강제 + 호출별 zero-shot 문맥 규칙 | AlignmentCheck 대체. IPIGuard와 유사 계열 |
| **SEAgent** | [2601.11893](https://arxiv.org/abs/2601.11893) | 정보흐름 그래프 기반 모니터링 + **ABAC** 강제 MAC. 낮은 FP와 무시할 만한 오버헤드 주장 | Progent 보완 (멀티에이전트·confused deputy 커버) |
| **NeuroTaint / Ghost in the Agent** | [2604.23374](https://arxiv.org/abs/2604.23374) | LLM 내부 전파 특성에 맞춘 정보흐름 추적 재정의 | FIDES 대체 후보 |
| **GIF** | [2606.23277](https://arxiv.org/abs/2606.23277) | Locally sound **기하학적** 정보흐름 통제 | FIDES 대체 후보 |
| **APPA** | [2607.24625](https://arxiv.org/abs/2607.24625) | **복구 가능(recoverable)** 정보흐름 통제 — label creep 완화 지향 | FIDES 보완 |
| **BASIS** | [2608.08027](https://arxiv.org/abs/2608.08027) | **Prefill attention probe** 기반 선택적 차폐 | Attention Tracker 후속 |
| **자체 모니터링 (IH 복구)** | [2606.07808](https://arxiv.org/abs/2606.07808) | 학습 불필요한 **병렬 입력 모니터 + 순차 출력 모니터**. 규칙 미준수 **81–99% 감소** | Instruction Hierarchy 보완 |
| **적대적 suffix 증강** | [2602.00750](https://arxiv.org/abs/2602.00750) | 학습 시 무작위 suffix 다수 삽입으로 probe 강건화 | PIShield 보완 |

---

## 7. 원 리포트 권고안 수정 사항

### 7.1 변경 요약

| 원 권고 | 변경 후 | 사유 |
|---|---|---|
| Phase 4 — **CausalArmor식 조건부 LLM 판정** | ⬇️ **삭제.** "조건부 개입" 원칙만 유지하고 **트리거를 권한 메타데이터로 대체** | 인과성 ≠ 권한. 승인된 실행 29.2% 오탐 |
| Phase 1 — **Tool Filter** | ⚠️ **전제 조건 3종 추가**(툴 문서 무결성 검증 / 등록 화이트리스트 / 서드파티 툴 신뢰 등급 분리) | ToolHijacker ASR 96.43% |
| Phase 1 — **Spotlighting** | ⚠️ **모델별 자체 검증 필수.** 소형·비영어 모델에서는 효과 없음을 기본 가정. 고위험 도메인은 프롬프팅만으로 불가 | 도메인 위장 공격에서 Llama 3.1 8B 이득 0 |
| Phase 1 — **메시지 역할 배치(IH)** | ⚠️ **"방어 계층" → "위생 수칙"으로 재분류.** ASR 감소 기대하지 않음. 템플릿 구분자 이스케이프 추가 | 추론 모델에서 IH 붕괴, ChatInject |
| Phase 2 — **Prompt Guard 2** | ⚠️ **유니코드 정규화 전처리 의무화**(NFKC, zero-width 제거, homoglyph 정규화, 전각→반각, bidi 제거) | 문자 주입으로 최대 100% 회피 |
| Phase 3 — **Progent** | ✅ **1순위 유지**, 단 **커버 범위 명시**(툴 호출 채널 한정). 출력 채널·멀티에이전트 위임·툴 라이브러리는 별도 통제 | 논문 자체 한계 절 + SoK |
| 시나리오 B — **Meta SecAlign 베이스 레이어** | ⬇️ **"베이스 레이어" 표현 삭제.** 런타임 비용 0의 **보너스 계층**으로 격하 | PISmith ASR@10 = 1.0 |
| 시나리오 B — **PIShield / Attention Tracker** | ⚠️ **오픈웨이트 모델 사용 시 주 방어선 금지.** 비공개 파인튜닝 모델에 한해 유효 | multi-probe 회피 99.63% |
| 시나리오 C — **FIDES** | ⚠️ **declassification 규칙 설계를 도입 전제로 격상.** 라벨 전파 시뮬레이션 사전 수행 | label creep, FP 106건 |
| — | ➕ **신규**: 계층 간 **원리 다양성** 요구 — 구문 정규화 / 결정론적 정책 / 의미 판정을 서로 다른 원리로 구성 | 상관된 실패 회피 |
| — | ➕ **신규**: Phase 0에 **"자율성 범위 정의"** 추가 — 에이전트가 임의 태스크를 풀 필요가 있는가? | utility-robustness trade-off는 자율성으로 상쇄됨 |

### 7.2 수정된 도입 로드맵

```
Phase 0  자체 평가 하네스 + baseline 측정
         ➕ [신규] 자율성 범위 정의 — 우리 에이전트가 풀어야 할 태스크 집합을 열거 가능한가?
         ➕ [신규] 툴 라이브러리 신뢰 모델 정의 — 누가 툴을 등록할 수 있는가?

Phase 1  비용 0 계층
         · 메시지 역할 배치 (위생 수칙 — ASR 감소 기대 안 함)
         · 채팅 템플릿 구분자 이스케이프                    ← 신규
         · 유니코드 정규화 전처리                           ← 신규 (Phase 2보다 먼저)
         · Spotlighting datamarking (모델별 효과 자체 측정)
         · Tool Filter (툴 무결성 통제 선행 조건부)

Phase 2  저비용 탐지 계층
         · Prompt Guard 2 (정규화 전처리 위에서만)
         · NotInject 스타일 오탐 세트로 임계값 튜닝
         · 문자 주입 회피 테스트 세트 추가                  ← 신규

Phase 3  결정론적 강제 계층  ★ 실질 방어선
         · Progent식 심볼릭 정책 (툴 호출 채널)
         · FIDES식 confidentiality 라벨 (출력 채널)        ← 범위 보완
         · declassification 규칙 사전 설계 + 시뮬레이션      ← 신규
         · 멀티에이전트 위임 경로 정책 (SEAgent/ControlValve 참고) ← 신규

Phase 4  고위험 경로 한정 검증
         · ~~CausalArmor식 인과 판정~~ → 삭제               ← 변경
         · 권한 메타데이터 기반 조건부 게이트로 대체          ← 변경
         · 필요 시 MELON (고위험 경로만, 비용 2배 감수)

Phase 5  적응형 레드팀 CI
         · SoK 3종 공격 + DataFlip + ToolHijacker
         · 문자 주입 / Controlled-Release 계열              ← 신규
         · PISmith 스타일 RL 레드팀 (여력이 되면)            ← 신규
```

---

## 8. 결론

### 8.1 반박 조사가 바꾼 것

1. **CausalArmor를 로드맵에서 제외했다.** 원 리포트에서 "2026년 저지연 계열 최신 후보"로 긍정 평가했으나, 인과 신호가 권한을 인코딩하지 못한다는 반박이 실험적으로 견고하다. **가장 큰 판단 수정이다.**

2. **Meta SecAlign에 대한 기대치를 낮췄다.** 원 리포트는 유틸리티 리스크만 경고했으나, PISmith가 **보안성 자체의 붕괴(ASR@10 = 1.0)**를 보였다. 모델레벨 방어는 "있으면 좋은 것"이지 방어선이 아니다.

3. **Tool Filter에 전제 조건이 붙었다.** "비용이 마이너스인 방어"라는 평가는 **툴 라이브러리가 신뢰 가능할 때만** 성립한다.

4. **전처리(유니코드 정규화)가 Phase 1로 올라왔다.** 원 리포트에는 아예 없던 항목인데, 문자 주입 공격이 분류기를 100% 우회한다는 결과를 보면 **가장 저렴하면서 누락 시 치명적인 항목**이다.

### 8.2 반박 조사가 바꾸지 않은 것

원 리포트의 **핵심 결론은 오히려 강화되었다**:

> **결정론적 정책 강제를 중심에 두고, 서로 다른 원리의 계층을 쌓는다.**

- **Progent는 반박을 견뎠다.** 지적된 것은 "커버 범위의 한계"이지 "설계 전제의 오류"가 아니다
- **반박 논문들이 제안하는 대안(ControlValve, SEAgent)도 모두 결정론적 구조 강제 방향**이다 — CFI, ABAC, 제어 흐름 그래프
- **확률적 판정(LLM judge, 인과 신호, 분류기)에 대한 반박이 압도적으로 많다.** 이는 "LLM의 판단을 신뢰하지 않는다"는 C6의 전제가 옳았음을 방증한다

### 8.3 최종 권고

> **"우리 에이전트가 할 수 있는 일의 목록을 명시적으로 좁힐 수 있는가?"** 이 질문에 예라고 답할 수 있다면 Progent식 정책 강제로 실용적 보안에 도달할 수 있다. 아니라면 — 즉 임의의 태스크를 자유롭게 수행하는 범용 에이전트를 목표로 한다면 — **현재 문헌상 유틸리티를 보존하면서 IPI를 막는 방법은 존재하지 않는다.** 이 경우 보안이 아니라 **피해 범위 제한**(권한 최소화, 되돌릴 수 있는 행동만 자동화, 고위험 행동에 사람 승인)으로 전략을 전환해야 한다.

---

## 9. 참고문헌

### 반박·공격 논문 (본 문서의 핵심 자료)

| 제목 | 표적 | 출처 |
|---|---|---|
| Influence Is Not Authority: When Causal Guardrail Signals Make Legitimate Tool Use Look Like an Attack | CausalArmor / 인과 기여도 가드레일 | [arXiv:2608.29942](https://arxiv.org/abs/2608.29942) |
| Prompt Injection Attack to Tool Selection in LLM Agents (ToolHijacker) | Tool Filter, StruQ, SecAlign, DataSentinel, KAD | NDSS 2026 · [arXiv:2504.19793](https://arxiv.org/abs/2504.19793) |
| PISmith: Reinforcement Learning-based Red Teaming for Prompt Injection Defenses | Meta-SecAlign, PromptArmor, DataSentinel, PromptGuard, PIGuard, Sandwich, Instructional | [arXiv:2603.13026](https://arxiv.org/abs/2603.13026) |
| Bypassing Prompt Injection Detectors through Evasive Injections | PIShield / activation 기반 탐지 | [arXiv:2602.00750](https://arxiv.org/abs/2602.00750) |
| Bypassing LLM Guardrails: An Empirical Analysis of Evasion Attacks | Prompt Guard, Azure Prompt Shield 외 6종 | ACL LLMSec 2025 · [arXiv:2504.11168](https://arxiv.org/abs/2504.11168) |
| Bypassing Prompt Guards in Production with Controlled-Release Prompting | Gemini, DeepSeek, Grok, Mistral Le Chat + 14개 오픈 guard | [arXiv:2510.01529](https://arxiv.org/abs/2510.01529) |
| Evaluating Prompting-Based Defenses Against Domain-Camouflaged Injection Attacks | Spotlighting, sandwiching, paraphrasing | [arXiv:2606.18530](https://arxiv.org/abs/2606.18530) |
| Where Instruction Hierarchy Breaks: Diagnosing and Repairing Failures in Reasoning LMs | Instruction Hierarchy | [arXiv:2606.07808](https://arxiv.org/abs/2606.07808) |
| ChatInject: Abusing Chat Templates for Prompt Injection in LLM Agents | 역할 기반 분리 | [arXiv:2509.22830](https://arxiv.org/abs/2509.22830) |
| Breaking and Fixing Defenses Against Control-Flow Hijacking in Multi-Agent Systems | **LlamaFirewall** / 정렬 기반 방어 | [arXiv:2510.17276](https://arxiv.org/abs/2510.17276) |
| Ghost in the Agent: Redefining Information Flow Tracking for LLM Agents | FIDES / 전통적 IFC | [arXiv:2604.23374](https://arxiv.org/abs/2604.23374) |
| Operationalizing CaMeL: Strengthening LLM Defenses for Enterprise Deployment | CaMeL | [arXiv:2505.22852](https://arxiv.org/abs/2505.22852) |
| Taming Various Privilege Escalation in LLM-Based Agent Systems (SEAgent) | 권한 통제 일반 / 멀티에이전트 | [arXiv:2601.11893](https://arxiv.org/abs/2601.11893) |
| May I have your Attention? Architecture-Aware Attacks | SecAlign, StruQ | [arXiv:2507.07417](https://arxiv.org/abs/2507.07417) |
| Checkpoint-GCG: Auditing and Attacking Fine-Tuning-Based Defenses | 파인튜닝 방어 | [arXiv:2505.15738](https://arxiv.org/abs/2505.15738) |
| Defenses Against Prompt Attacks Learn Surface Heuristics | 파인튜닝 방어 | [arXiv:2601.07185](https://arxiv.org/abs/2601.07185) |
| The Autonomy Tax: Defense Training Breaks LLM Agents | 파인튜닝 방어 (유틸리티) | [arXiv:2603.19423](https://arxiv.org/abs/2603.19423) |
| How Not to Detect Prompt Injections with an LLM (DataFlip) | Known-Answer Detection | [arXiv:2507.05630](https://arxiv.org/abs/2507.05630) |
| A Critical Evaluation of Defenses against Prompt Injection Attacks | 평가 방법론 전반 | [arXiv:2505.18333](https://arxiv.org/abs/2505.18333) |
| Adaptive Attacks Break Defenses Against IPI on LLM Agents | 8개 방어 | [arXiv:2503.00061](https://arxiv.org/abs/2503.00061) |
| SoK: Taxonomy, Evaluation and Exploitation of IPI-Centric Defense Frameworks | 프레임워크 전반 | [arXiv:2511.15203](https://arxiv.org/abs/2511.15203) |
| Assessing Automated Prompt Injection Attacks in Agentic Environments | 자동 공격 평가 | [arXiv:2606.10525](https://arxiv.org/abs/2606.10525) |
| PI-Hunter: Automated Red-Teaming for Exposing and Localizing Prompt Injections | 자동 레드팀 | [arXiv:2606.12737](https://arxiv.org/abs/2606.12737) |

### 대안 기법

| 제목 | 출처 |
|---|---|
| ControlValve (in Breaking and Fixing Control-Flow Hijacking) | [arXiv:2510.17276](https://arxiv.org/abs/2510.17276) |
| SEAgent (in Taming Various Privilege Escalation) | [arXiv:2601.11893](https://arxiv.org/abs/2601.11893) |
| GIF: Locally Sound Geometric Information Flow Control for LLMs | [arXiv:2606.23277](https://arxiv.org/abs/2606.23277) |
| APPA: Recoverable Information-Flow Control for Real-World LLM Agents | [arXiv:2607.24625](https://arxiv.org/abs/2607.24625) |
| BASIS: Breach-Aware Selective Prompt Injection Shielding with Prefill Attention Probes | [arXiv:2608.08027](https://arxiv.org/abs/2608.08027) |
| Securing AI Agents with Information-Flow Control (FIDES 원논문) | [arXiv:2505.23643](https://arxiv.org/abs/2505.23643) |

### 원 리포트에서 추천되어 반박 대상이 된 기법

| 기법 | 출처 |
|---|---|
| Progent | [arXiv:2504.11703](https://arxiv.org/abs/2504.11703) |
| CausalArmor | [arXiv:2602.07918](https://arxiv.org/abs/2602.07918) |
| Spotlighting | [arXiv:2403.14720](https://arxiv.org/abs/2403.14720) |
| Meta SecAlign | [arXiv:2507.02735](https://arxiv.org/abs/2507.02735) |
| LlamaFirewall | [arXiv:2505.03574](https://arxiv.org/abs/2505.03574) |
| MELON | [arXiv:2502.05174](https://arxiv.org/abs/2502.05174) |
| CaMeL | [arXiv:2503.18813](https://arxiv.org/abs/2503.18813) |
| PIShield | [arXiv:2510.14005](https://arxiv.org/abs/2510.14005) |
| Attention Tracker | [arXiv:2411.00348](https://arxiv.org/abs/2411.00348) |
| Design Patterns for Securing LLM Agents | [arXiv:2506.08837](https://arxiv.org/abs/2506.08837) |

---

## 부록. 수치 신뢰도 표기

본 문서의 수치는 모두 **반박 논문의 자가보고**이며, 방어 논문의 자가보고와 마찬가지로 **자기 유리 편향**을 감안해야 한다. 특히 다음을 유의한다:

| 항목 | 유의사항 |
|---|---|
| PISmith의 Meta-SecAlign ASR@10 = 1.0 | **8B 모델 대상**. 70B는 미검증 |
| Evasive Injections 99.63% | **화이트박스 가정**. 가중치 비공개 시 성립하지 않음 |
| ToolHijacker 96.43% | **툴 라이브러리 오염이 가능한 경우**에 한함 |
| FIDES F1 = 0.522 | **경쟁 기법 제안 논문의 비교 실험**. 재현 필요 |
| Influence Is Not Authority의 오탐 29.2% | shadow-based guardrail 대상. CausalArmor 원구현과의 동일성 재확인 필요 |

**공통 원칙**: 반박 논문의 위협모델이 **자사 환경에 해당하는지 먼저 판단**한 뒤 심각도를 재평가할 것. 화이트박스 공격 결과를 블랙박스 배포 환경에 그대로 적용하면 과도한 방어 투자로 이어진다.
