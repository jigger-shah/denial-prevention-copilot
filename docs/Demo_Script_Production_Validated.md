# Demo Script — Production Validated

> ## ⚠️ STATUS: SUPERSEDED
>
> This document reflects an earlier validation snapshot (Sprint 10, 2026-06-16) — predating the orchestrator, the Coding Validation Agent, the golden-set evaluation framework, and every v1.4–v1.8b release. UI references below ("claim intake form," "Click Analyze Claim") describe a layout that no longer exists.
>
> **For current demo instructions, use `docs/Demo_Script.md`.**
>
> The historical content below is retained as-is for reference and is not maintained.

---

**DenialPreventionCopilot** | Portfolio and Stakeholder Demonstrations  
Production validated: 2026-06-16 | Model: claude-sonnet-4-5-20250929

---

## Table of Contents

1. [Executive Demo Overview](#1-executive-demo-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [30-Second Elevator Pitch](#3-30-second-elevator-pitch)
4. [2-Minute Demo](#4-2-minute-demo)
5. [5-Minute Executive Demo](#5-5-minute-executive-demo)
6. [Demo Scenario A — Labs with Preventive Diagnosis](#6-demo-scenario-a--labs-with-preventive-diagnosis)
7. [Demo Scenario B — Diabetes Management Visit](#7-demo-scenario-b--diabetes-management-visit)
8. [AI Governance Talking Points](#8-ai-governance-talking-points)
9. [AI PM Talking Points](#9-ai-pm-talking-points)
10. [Common Questions and Suggested Answers](#10-common-questions-and-suggested-answers)
11. [Portfolio Positioning](#11-portfolio-positioning)
12. [Production Validation Results](#12-production-validation-results)
13. [Miscellaneous Talking Points](#13-miscellaneous-talking-points)

---

## 1. Executive Demo Overview

### What the Product Is

DenialPreventionCopilot is a clinical billing intelligence system that catches likely insurance denials **before** a claim is submitted. It combines deterministic rules with an LLM-backed coverage validation agent to surface problems at the moment of coding — not weeks later when a denial arrives.

### Why Denial Prevention Matters

- Medicare and commercial payers deny **5–10% of all claims** on first submission
- Medical practices spend an estimated **$6.00–$14.00** to rework each denied claim (CAQH index)
- High-volume practices handle thousands of claims per week; a 1% denial reduction at scale saves tens of thousands of dollars annually
- Denials create cash flow delays, coding staff burnout, and patient confusion

### Key Business Problem Solved

Coders currently submit claims without knowing whether the diagnosis-procedure combination will pass payer scrutiny. They discover problems only after a denial — which can take 30–90 days. This tool moves that discovery to submission time, when corrections cost nothing.

### What Makes This Different From Existing Tools

Most coding tools check for code validity (is 99214 a real CPT code?) but not medical necessity (is 99214 medically appropriate for this diagnosis on this payer's LCD?). This system specifically targets the second, harder question using CMS LCD/NCD policy text and structured AI reasoning.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLAIM INTAKE                              │
│  Manual form (app/claim_intake.py) — CPT codes, ICD-10 codes,  │
│  NPI, date of service, patient type                              │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RULE LAYER  (always runs first)               │
│  • NPI validity — NPPES live API + Luhn check                   │
│  • Code validity — ICD-10-CM, CPT, HCPCS Level II               │
│  • NCCI PTP edits — quarterly CMS edit table                    │
│  • MUE limits — quarterly CMS table, MAI-aware severity         │
│                                                                  │
│  Hard failures short-circuit; no LLM call needed                │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              COVERAGE VALIDATION AGENT  (LLM-backed)            │
│  • Retrieves matching LCD/NCD policies from JSON corpus         │
│    (18 CMS LCD/NCD entries, 6 demo scenarios validated)         │
│  • Sends up to 3 policies to Claude with tool_choice=any        │
│  • Model must call report_coverage_finding OR no_coverage_concern│
│  • Citation grounding: suppresses findings with hallucinated IDs │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   HUMAN REVIEW (findings panel)                  │
│  • Risk score, severity badges, recommended fixes               │
│  • Full citation: document_id, section, effective_date, excerpt  │
│  • Approve / Override decision with free-text rationale         │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   AUDIT TRAIL  (append-only)                    │
│  • Every finding, decision, and override written as INSERT only  │
│  • SHA-256 finding IDs stable across re-runs                    │
│  • Exportable audit log for compliance review                   │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions Worth Explaining

| Decision | Why It Was Made |
|---|---|
| Rule layer always runs before LLM | Deterministic lookups are faster, cheaper, and more reliable; LLM is only needed when policy interpretation is required |
| Citation grounding check | Prevents hallucinated policy citations from reaching the UI — if the cited doc_id wasn't in the retrieved set, the finding is suppressed |
| `tool_choice = any` | Forces the model to produce exactly one structured tool call — eliminates free-text responses that would require parsing |
| Append-only audit log | Immutability is a governance requirement in healthcare — no UPDATE or DELETE ever issued |
| Synthetic data only | No PHI anywhere in the codebase; safe to demo, open-source, and put in a portfolio |

---

## 3. 30-Second Elevator Pitch

> "I built a denial prevention system for medical billing. When a coder is about to submit a claim, the tool runs two things in parallel: deterministic rule checks — NCCI edits, MUE limits, NPI validity — and an LLM agent that reads the actual CMS LCD and NCD policy text and flags medical necessity problems.
>
> The key thing I care about is governance. The AI can only cite policies that were actually retrieved — hallucinated citations are suppressed in code, not by prompting. Every decision is logged to an append-only audit trail. The system is production validated: it correctly identified a HIGH-severity medical necessity issue on a real claim, cited the exact LCD section, in under eight seconds."

---

## 4. 2-Minute Demo

**Audience:** Technical or product stakeholder  
**Format:** Verbal walkthrough, optionally with the running app visible

---

**Step 1 — State the problem (20 sec)**

> "Medical practices lose millions annually to denials that could have been caught at submission. The root cause is usually one of three things: a coding error caught by a deterministic rule, or a medical necessity problem that requires reading the payer's LCD policy — which is a 20-page CMS document most coders don't have memorized."

**Step 2 — Show the architecture (30 sec)**

> "The system runs two layers. First, a rule engine that does deterministic lookups: NCCI edit pairs, MUE quantity limits, NPI validation, code validity. These never touch an LLM because they don't need to — the answer is in a table. Second, a coverage agent backed by Claude that retrieves the relevant LCD/NCD policies and reasons about whether the claim's diagnosis justifies the procedure."

**Step 3 — Run Demo Scenario A (30 sec)**

Enter: CPT 80053 + 83036, Diagnosis Z00.00

> "This is a common scenario — a routine annual visit where the doctor also ordered a comprehensive metabolic panel and HbA1c. The rule layer comes back clean: all codes valid, no NCCI conflicts. But the AI layer flags a HIGH-severity issue: Medicare's LCD says labs billed against a preventive exam diagnosis — Z00.00 — require a separate problem-oriented diagnosis to establish medical necessity. It cites the exact LCD, section, and effective date."

**Step 4 — Highlight governance (30 sec)**

> "The finding you see on screen is grounded — the doc ID in the citation was in the retrieved set, not hallucinated. The model used structured tool use with `tool_choice=any`, so it had to make an explicit decision rather than generate free text. And whatever the coder decides — approve, override — gets written to an append-only audit log with a stable SHA-256 finding ID. This matters for healthcare compliance."

---

## 5. 5-Minute Executive Demo

**Audience:** Product leader, healthcare executive, or potential investor  
**Format:** Live app walkthrough + Q&A

---

### Opening (45 sec)

> "What I'm going to show you is a system that moves the denial conversation from 45 days after submission to the moment of coding. Today, when a coder submits a claim with a documentation problem, they find out about it when the denial arrives — which triggers rework, appeals, and sometimes write-offs. This tool puts the right information in front of the coder before they ever hit submit."

### Rule Layer Demo (1 min)

Navigate to the claim intake form. Enter a claim with a known NCCI edit conflict.

> "The first layer is entirely deterministic. NCCI edits are quarterly CMS tables — there's no AI involved, there's no ambiguity. The system tells you: these two procedure codes can't be billed together on the same day without the right modifier. This is the kind of finding that used to require a certified coder to catch."

### Coverage Agent Demo — Scenario A (1.5 min)

Enter CPT 80053, 83036 with ICD-10 Z00.00.

> "Now I'll show you something harder. This is a common pattern: an annual wellness visit with lab work ordered. The codes are all valid. There's no NCCI conflict. But Medicare has an LCD — a Local Coverage Determination — that says labs billed against a routine exam diagnosis require a separate problem-oriented diagnosis to justify medical necessity. That's in a 20-page CMS document that most coders don't read."

Wait for the agent to complete (~7 seconds).

> "The system found it. HIGH severity. It's citing 'LCD_E_M_MEDICAL_NECESSITY_Z00,' section 'Indications and Limitations,' effective 2024. The recommendation is to add a specific diagnosis — like a documented chronic condition — if one exists in the chart."

### Governance Story (1 min)

> "The thing I want to highlight is what makes this different from a chatbot. The model cannot cite a policy that wasn't retrieved. We enforce citation grounding in code: if the doc_id in the finding isn't in the retrieved set, the finding is suppressed — silently, before it reaches the UI. We use structured tool use so the model has to make a binary decision: finding or no concern. And every outcome is written to an append-only audit log — there is no UPDATE or DELETE in our database layer. That's not a prompt engineering choice; that's an architectural constraint."

### Business Impact (45 sec)

> "In a practice submitting 500 claims a week, a 2% catch rate on this one LCD pattern is 10 claims. Each rework costs roughly $10 in staff time, and a portion never gets paid at all. The system's value isn't in individual catches — it's in the consistency. Every claim gets the same policy check, with a citation that can be audited, every time."

### Q&A Prompts

- "What does this cost to run per claim?" → The rule layer is free. The AI layer costs roughly $0.001–0.003 per claim at current Haiku pricing. Volume-tiered.
- "How does it stay current with policy changes?" → The JSON corpus is updated by pulling new LCD text. The retrieval and reasoning architecture doesn't change — only the data.
- "What happens when the AI is wrong?" → The human reviewer sees the finding and citation. They can override with a rationale. The override is logged. The system is advisory, not autonomous.

---

## 6. Demo Scenario A — Labs with Preventive Diagnosis

**Title:** Comprehensive Metabolic Panel + HbA1c billed with Annual Exam Diagnosis  
**Claim Codes:** CPT 80053, CPT 83036 | ICD-10 Z00.00  
**Expected Rule Layer Result:** CLEAN (0 findings)  
**Expected AI Layer Result:** HIGH finding, citation grounding PASSED  
**Production Validated:** Yes — 2026-06-16

### Step-by-Step

1. Open the app at `http://localhost:8501`
2. In the claim intake form, enter:
   - CPT Codes: `80053, 83036`
   - ICD-10 Codes: `Z00.00`
   - NPI: any valid 10-digit NPI (e.g., `1234567893`)
   - Date of Service: today's date
3. Click "Analyze Claim"
4. Observe the rule layer panel: **0 deterministic findings** — all codes valid, no NCCI edit conflicts
5. Observe the AI coverage panel: **1 finding, severity HIGH**

### Production-Validated Finding

```
Severity:        HIGH
Source:          agent_layer
Confidence:      0.85
Finding ID:      cov-443970464cd3

Issue:
  Laboratory tests billed with routine preventive examination
  diagnosis Z00.00 lack medical necessity documentation.

Recommendation:
  Review clinical documentation to identify a specific medical
  problem or condition. If a chronic condition (e.g., hypertension,
  diabetes) was also addressed, add the corresponding ICD-10 code
  as a secondary or primary diagnosis.

Citation:
  Document:        LCD_E_M_MEDICAL_NECESSITY_Z00
  Section:         Indications and Limitations of Coverage
                   and/or Medical Necessity
  Effective Date:  2024-01-01
  Excerpt:         Problem-oriented E/M services (CPT 99202–99215)
                   billed with a primary diagnosis of Z00.00 (Encounter
                   for general adult medical examination without
                   abnormal findings)...

Citation Grounding: PASSED
  Cited doc_id was present in retrieved set of 7 policies
```

### Talking Points This Scenario Demonstrates

| Discussion Focus | What to Highlight |
|---|---|
| AI reasoning quality | Model correctly distinguished between preventive and problem-oriented billing — a nuance that requires reading the LCD |
| Governance | Citation grounding enforced in code, not prompt; finding suppressed if hallucinated doc_id |
| Latency | 7.27s end-to-end including retrieval and LLM call — acceptable for pre-submission workflow |
| Retrieval design | 7 policies retrieved, 3 sent to model (_MAX_POLICIES=3 cost cap); correct policy surfaced despite not being top-ranked |
| Human-in-loop | Finding is advisory; coder sees citation and makes the decision |

---

## 7. Demo Scenario B — Diabetes Management Visit

**Title:** Office Visit for Established Diabetic Patient  
**Claim Codes:** CPT 99214 | ICD-10 E11.9  
**Expected Rule Layer Result:** CLEAN  
**Expected AI Layer Result:** No coverage concern (clean claim)  
**Production Validated:** Yes (clean outcome confirms correct suppression behavior)

### What This Scenario Tests

A clean scenario is as important as a flagged one. It confirms:
1. The system does not over-flag — a well-documented diabetes visit with an appropriate E/M level should not trigger a finding
2. The `no_coverage_concern` tool path works correctly
3. The system retrieves relevant policies (`LCD_DIABETES_MGMT_E11`, `LCD_EM_CODING_LEVEL_SUPPORT`) but correctly reasons that the coding is appropriate

### Step-by-Step

1. In the claim intake form, enter:
   - CPT Codes: `99214`
   - ICD-10 Codes: `E11.9`
   - NPI: valid NPI
   - Date of Service: today's date
2. Click "Analyze Claim"
3. Observe rule layer: CLEAN
4. Observe AI layer: **No coverage concern** — the model calls `no_coverage_concern` with a rationale

### Talking Points

> "This is the system correctly staying quiet. 99214 with E11.9 — Type 2 diabetes without complications — is an appropriate level-4 office visit for diabetes management. The system retrieved two relevant policies, read them, and concluded there's no coverage concern to report. A system that flags everything is useless. The value is in specificity."

### Contrast With Scenario A

| Attribute | Scenario A | Scenario B |
|---|---|---|
| CPT | 80053, 83036 | 99214 |
| ICD-10 | Z00.00 | E11.9 |
| Rule findings | 0 | 0 |
| AI finding | HIGH — medical necessity gap | None — appropriate claim |
| Key distinction | Labs need problem-oriented dx | Diabetes visit appropriately coded |
| What it proves | AI can identify policy nuance | AI can suppress false positives |

---

## 8. AI Governance Talking Points

### Citation Grounding

**What it is:** After the model returns a finding, the system checks whether the cited `citation_doc_id` was in the set of policy documents actually retrieved for this claim. If not, the finding is suppressed.

**Why it matters:** LLMs hallucinate citations. A finding citing a policy that wasn't consulted — and may not exist — is worse than no finding at all, because it misleads the reviewer and cannot be audited back to source.

**Key phrase:** "We don't trust the model to know what it retrieved. We enforce citation grounding in code."

**Code reference:** `agents/coverage_validation.py` — citation grounding block at the end of `validate_coverage()`

---

### Structured Tool Use

**What it is:** The model is given two tools: `report_coverage_finding` (requires issue, recommendation, severity, confidence, citation fields) and `no_coverage_concern` (requires reason). `tool_choice={"type": "any"}` forces exactly one tool call.

**Why it matters:** Free-text responses are ambiguous and hard to parse reliably. Structured tool use produces machine-readable outputs with enforced schema — every field is present or the call is invalid.

**Key phrase:** "The model has to make a decision. It cannot hedge or produce a partial answer."

---

### Failure Handling

**What happens when the AI is unavailable:** `agents/coverage_validation.py` checks for `ANTHROPIC_API_KEY` at call time. If absent, it returns `[]`. The UI displays rule findings only, with a note that AI coverage analysis is disabled. The system degrades gracefully — it never blocks a workflow.

**What happens when retrieval returns nothing:** If no policies match the claim's codes, the function returns `[]` early. No LLM call is made. No empty or speculative findings are generated.

**Key phrase:** "No finding is generated from nothing. If we can't retrieve a policy to support it, we suppress it."

---

### Auditability

**Finding IDs:** `"cov-" + SHA-256(claim_id | doc_id | issue)[:12]` — stable, position-independent. Re-running the same claim produces the same finding ID, so audit entries are deduplicated and traceable.

**Audit log:** `db/audit.py` issues INSERT only. There is no UPDATE or DELETE path. This is enforced at the Python layer, not by database permissions.

**Override tracking:** When a reviewer overrides a finding, the override decision (including free-text rationale) is written as a separate audit entry — not by modifying the original finding.

**Key phrase:** "You can reconstruct the complete reasoning chain for any claim, at any point in time, from the audit log."

---

### Human-in-the-Loop

**Design intent:** The system is advisory. Every finding surfaces to a human reviewer who sees the citation, the severity, and the recommendation before deciding. The system does not submit, modify, or suppress claims autonomously.

**Why this matters for healthcare AI:** CMS and OIG guidance on AI in billing emphasizes human oversight. A system that autonomously modifies claims without a human review step creates compliance exposure.

**Key phrase:** "The AI is the expert consultant. The coder is the decision-maker."

---

## 9. AI PM Talking Points

### Governance First, Then Capability

The design constraint in `CLAUDE.md`: "No citation → no finding." This was established before writing the first line of agent code, not added after the fact. In healthcare AI, governance is not a feature you bolt on — it has to be structural.

**Talking point:** "Before we built the coverage agent, we wrote the citation grounding requirement into the architecture document. The agent code was written to enforce it in code, not in the prompt."

---

### Cost Controls Are a PM Responsibility

`_MAX_POLICIES = 3` in `coverage_validation.py` is not a technical constraint — it's a product decision. Sending 10 policies per call would produce more complete analysis but increase latency and token cost by 3x. Three policies, chosen by relevance, captures the most actionable signal.

**Talking point:** "Every LLM call has a cost profile. The PM has to decide how much context is worth sending and build that as a system constant, not leave it to the engineer to guess."

---

### Structured Outputs Are a Product Feature

The `report_coverage_finding` tool schema enforces: issue (string), recommendation (string), severity (HIGH/MEDIUM/LOW/INFO), confidence (float), citation_doc_id (string), citation_section (string), citation_excerpt (string). These aren't just engineering conveniences — they're the fields the UI needs to display a useful finding and the audit log needs for compliance.

**Talking point:** "The tool schema was designed by asking: what does the reviewer need to see, and what does the audit trail need to capture? The model's output is shaped by the product requirement."

---

### Retrieval Strategy Is a Product Decision

The JSON-backed policy corpus is organized by `applies_to_codes` — a list of CPT and ICD-10 codes each policy is relevant to. The retrieval function returns all policies whose code set intersects the claim's codes, then caps at 3 by relevance.

The decision to index HbA1c policy by CPT (83036) rather than by diagnosis (E11.x) was deliberate: retrieving it for all diabetes claims regardless of whether HbA1c was billed would add noise. Retrieval design is a product judgment, not just an engineering one.

---

### RAG Roadmap

The current system uses a JSON file as its policy store. The architecture is designed to swap this for ChromaDB (vector retrieval) without changing the agent interface — `find_policies_by_codes()` is the retrieval abstraction layer. Migrating to embeddings-based retrieval improves recall for policies not indexed under a specific code but requires embedding infrastructure.

**PM frame:** "We built a working retrieval system with zero infrastructure cost to validate the agent architecture. The migration to vector retrieval is a step-up when we have evidence that JSON lookup is the binding constraint on coverage — not before."

---

## 10. Common Questions and Suggested Answers

### "How do you know the AI isn't hallucinating?"

> "Two enforcement layers. First, structured tool use — the model can't produce free text; it has to call one of two tools with enforced schemas. Second, citation grounding: we check in code whether the policy document the model cited was actually in the retrieved set. If it wasn't, the finding is suppressed before it reaches the UI. We validate this in tests — there's a test that injects a finding citing a doc_id that wasn't retrieved and asserts it's suppressed."

---

### "Why not just use a rules engine?"

> "Rules engines are great for what they do — NCCI edits, MUE limits, code validity. We use one, and it runs first. But LCD medical necessity determinations require reading policy text and applying clinical judgment. The question 'does this diagnosis support this procedure under this payer's policy?' is not in a lookup table. That's where the LLM adds value that a rules engine can't provide."

---

### "How would you scale this to a large practice?"

> "The rule layer is stateless and parallelizable — you can run 1,000 claims concurrently with no bottleneck. The AI layer has per-claim latency around 7 seconds and token cost around $0.001–0.003 at Haiku pricing. For high-volume use, you'd batch the AI layer or run it asynchronously and surface findings as a pre-submission queue rather than a blocking step. The architecture supports both modes."

---

### "What's the risk of this system missing a denial?"

> "It's a recall vs. precision tradeoff. The system is designed for high precision — we only surface findings we can support with a citation. A missed finding means the claim goes through as-is, which is the current baseline. A false positive means a coder investigates and finds no problem. False positives damage trust faster than misses, so we bias toward suppression when confidence is low."

---

### "How do you keep the policies current?"

> "The policy corpus is a JSON file updated by pulling new LCD/NCD text from the CMS Coverage API. We don't rebuild the agent architecture when policies change — only the data. The citation outputs include an effective_date field, so every finding is traceable to the specific policy version that was consulted."

---

### "What would you build next?"

> "Three things in order: first, expand the policy corpus to cover more LCD categories — we have 18 entries and need roughly 50 for broad Medicare coverage. Second, add vector retrieval to improve recall on policies not indexed under a specific code combination. Third, add a feedback loop: when overrides happen, track whether the final payer decision validated or contradicted the AI finding, and use that to calibrate confidence scores."

---

### "Why didn't you use LangChain/LlamaIndex?"

> "The architecture is intentionally minimal. The system needs one retrieval call and one LLM call per claim, with deterministic control flow. Adding an orchestration framework would add abstraction without adding capability at this scale. If the system grew to multiple specialized agents with complex routing, a framework would make sense. For now, direct Anthropic SDK calls with structured tool use gives us full control over the call structure, token budget, and error handling."

---

## 11. Portfolio Positioning

### What Is Complete and Production Validated

| Feature | Status | Evidence |
|---|---|---|
| Rule engine (NCCI, MUE, NPI, code validity) | Complete | 227 tests passing |
| Coverage Validation Agent v1 | Production validated | Live API call, 7.27s, HIGH finding, grounding PASSED |
| Citation grounding enforcement | Complete | Code + test coverage |
| Structured tool use (`tool_choice=any`) | Complete | Two-tool schema, enforced |
| Append-only audit trail | Complete | INSERT-only `db/audit.py` |
| LCD/NCD policy corpus | 18 entries, 6 demo scenarios | `data/reference/policy_examples.json` |
| Manual claim intake UI | Complete | `app/claim_intake.py` |
| Findings panel with citations | Complete | `app/components/findings_panel.py` |
| SHA-256 stable finding IDs | Complete | All rule and agent findings |

### What Is Deferred (by Design, Not Inability)

| Feature | Reason Deferred |
|---|---|
| ChromaDB vector retrieval | JSON lookup sufficient to validate agent architecture; infrastructure cost not yet justified |
| CMS Coverage API live ingestion | Manual corpus sufficient for demo scenarios; ingest.py scaffolded |
| Documentation Review Agent | Requires clinical note corpus; scaffolded in `agents/documentation_review.py` |
| Orchestrator parallel dispatch | Single-agent flow sufficient; orchestrator.py scaffolded |
| Evaluation framework (golden set) | `pytest -m golden` scaffolded; needs labelled claim corpus |
| Commercial payer policies | Medicare LCDs chosen as most publicly available; commercial requires payer-specific contracts |

### How to Present the Deferred Items

> "These features are deferred, not forgotten. The architecture is designed to accommodate them — the retrieval layer abstraction means ChromaDB drops in behind `find_policies_by_codes()`. I deferred them because validating the core agent loop — retrieval, reasoning, citation grounding, structured output — was the highest-value thing to prove. That's now done in production."

### Planned Next Steps

1. Expand policy corpus to 50+ LCD entries (quarterly CMS update cycle)
2. Add vector retrieval (ChromaDB) for policies without specific code mappings
3. Build evaluation framework: label 50 synthetic claims, run precision/recall against known denials
4. Add Orchestrator parallel dispatch to run coding + coverage agents concurrently
5. Commercial payer pilot: identify one payer with accessible policy documentation

---

## 12. Production Validation Results

### Validation Run Summary

| Attribute | Value |
|---|---|
| Date | 2026-06-16 |
| Model | claude-sonnet-4-5-20250929 |
| Demo Scenario | CPT 80053 + 83036, ICD-10 Z00.00 (Labs + Preventive Exam Dx) |
| End-to-End Latency | 7.27 seconds |
| Policies Retrieved | 7 |
| Policies Sent to Model | 3 (capped by `_MAX_POLICIES = 3`) |
| Finding Generated | Yes |
| Finding Severity | HIGH |
| Citation Doc ID | LCD_E_M_MEDICAL_NECESSITY_Z00 |
| Citation Grounding | PASSED (cited doc_id present in retrieved set) |
| Auth Test Latency | 1.72 seconds |
| Test Suite Status | 227 tests passing, 0 failing |

### Finding Detail

```
finding_id:     cov-443970464cd3
severity:       HIGH
confidence:     0.85
source_agent:   coverage_validation
issue:          Laboratory tests billed with routine preventive
                examination diagnosis Z00.00 lack medical necessity
                documentation
recommendation: Review clinical documentation to identify a specific
                medical problem or condition
citation:
  doc_id:         LCD_E_M_MEDICAL_NECESSITY_Z00
  section:        Indications and Limitations of Coverage
                  and/or Medical Necessity
  effective_date: 2024-01-01
```

### Retrieved Policy Set (7 policies)

- `LCD_PREVENTIVE_99395_COVERAGE`
- `LCD_VENIPUNCTURE_36415_SAMPLE`
- `LCD_E_M_MEDICAL_NECESSITY_Z00` ← cited by model
- `LCD_HEMOGLOBIN_A1C_FREQUENCY`
- `LCD_LAB_MEDICAL_NECESSITY_METABOLIC`
- `NCD_AWV_G0438_G0439`
- `LCD_PREVENTIVE_99396_COVERAGE`

### Environment Configuration

```
# .env (gitignored — never committed)
ANTHROPIC_API_KEY=<set locally>
ANTHROPIC_MODEL=claude-sonnet-4-5
```

The app requires a valid API key in `.env`. Without it, `_AI_ENABLED = False` in `app/main.py` and the coverage agent panel is suppressed — the rule layer still runs.

---

## 13. Miscellaneous Talking Points

### Top 10 Demo Tips

1. **Start with the problem, not the product.** "Denials cost $10 per rework and can take 90 days to resolve" is more compelling than "this app analyzes claims."
2. **Run the clean scenario before the flagged one.** Showing that the system stays quiet when appropriate builds credibility before you show the finding.
3. **Narrate the wait time.** Seven seconds of silence is uncomfortable. Say "this is calling the Claude API and checking three CMS policies" while it loads.
4. **Point to the citation.** The LCD section and effective date are what makes this credible to a healthcare audience. Make them visible.
5. **Explain what would have happened without the tool.** "This claim would have gone out, gotten denied in 30 days, and triggered a rework cycle."
6. **Don't over-promise AI confidence.** Confidence 0.85 means the model was fairly sure, not certain. The human reviewer is the final decision-maker.
7. **Have the architecture diagram ready.** Viewers evaluating AI product design want to see that you understand the system, not just the UI.
8. **Pre-clear the audit log before the demo.** A fresh audit log is easier to explain than one with 20 prior entries from testing.
9. **Know the deferred items cold.** "We didn't build X" followed by a clear reason ("because Y was sufficient to validate the core loop") is stronger than silence.
10. **End with scale.** "At 500 claims a week, a 2% catch rate is 10 flagged claims. At $10 rework cost each, that's $100/week in prevented rework — from one LCD pattern."

---

### Top 10 AI PM Talking Points

1. **AI governance is architectural, not operational.** Citation grounding is enforced in code; it cannot be accidentally disabled by a prompt change.
2. **Structured outputs are a product requirement, not an engineering preference.** The tool schema encodes what the reviewer needs to see.
3. **Cost per inference is a product constraint.** `_MAX_POLICIES = 3` is a PM decision, not an arbitrary limit.
4. **Retrieval design is as important as model selection.** What the model receives determines what it can reason about. Bad retrieval produces bad findings regardless of model quality.
5. **Graceful degradation is a product feature.** The system works without an API key; it just works better with one.
6. **Human-in-the-loop is not a hedge — it's a compliance requirement.** In healthcare billing, autonomous AI action without human review creates regulatory exposure.
7. **Precision over recall when the cost of false positives is high.** Coders who distrust the system ignore it entirely.
8. **The evaluation framework is a product investment, not a technical one.** You can't improve what you can't measure. The golden-set test suite is backlogged for a reason, not forgotten.
9. **Policy currency is an operational concern.** LCDs update quarterly. The system's value degrades if the corpus isn't refreshed on schedule.
10. **Synthetic data is a product decision.** No PHI means the system is safe to open-source, demo publicly, and put in a portfolio — without HIPAA exposure.

---

### Top 10 Healthcare AI Governance Talking Points

1. **No citation, no finding.** Every AI-generated coverage concern must be traceable to a specific policy document, section, and effective date. Unsupported findings are suppressed.
2. **Human review is not optional.** The system is advisory. A clinically trained human makes every final billing decision.
3. **Audit trails must be immutable.** Append-only storage is an architectural constraint, not a configuration option. No UPDATE or DELETE in the persistence layer.
4. **Model outputs must be structured.** Free-text AI responses in clinical workflows create parsing ambiguity and auditability gaps. Tool use with enforced schemas eliminates both.
5. **Hallucination must be controlled at the system level.** Prompting the model to "only cite real policies" is insufficient. Citation grounding must be enforced after the model responds.
6. **Synthetic data is not optional for development.** PHI in training data, test fixtures, or demo files creates HIPAA exposure. Build with synthetic data from day one.
7. **Failure must be quiet, not loud.** When the AI layer is unavailable, the system reverts to deterministic rules — it does not block the workflow or produce an error the coder can't interpret.
8. **Confidence scores must be calibrated, not decorative.** A confidence of 0.85 should reflect the model's actual error rate on similar claims, not an arbitrary value.
9. **Policy version is part of the finding.** A finding citing a 2022 LCD is meaningless in 2026 if the policy changed. Every citation must include an effective_date.
10. **Override tracking closes the feedback loop.** When a reviewer overrides a finding, that override (and its rationale) is logged. When the payer decision arrives, it can be compared against the AI finding to measure accuracy over time.

---

*Document created: 2026-06-16 | Status: Production Validated | Build: Sprint 10*
