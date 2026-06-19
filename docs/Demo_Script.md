# Demo Script
## Denial Prevention Copilot

**App URL (local):** `http://localhost:8501`  
**Launch command:** `source .venv/bin/activate && streamlit run app/main.py`

> **Update (Phase 4, Session 1D):** The Coverage Validation Agent now actually queries ChromaDB first, exactly as line ~422 below describes — that section was written ahead of implementation and is now accurate as the *first* retrieval step. However, the vector store ships unseeded (no bulk CMS corpus was loaded as part of Phase 4, by design), so in the demo as currently configured the agent falls through to the JSON policy corpus described elsewhere in this script every time. The demo flow, talking points, and expected findings below are unchanged. See `docs/Architecture_Decisions.md` ADR-013 for the fallback design.

---

## Audience Quick Reference

| Audience | Lead with | Emphasize | Skip |
|---|---|---|---|
| Product Management | Problem + PRD decisions | Prioritization, user stories, human-in-loop | Technical architecture |
| Director of Product | Business impact + scope | Why built this way, what's next, tradeoffs | Code details |
| AI Product Management | Architecture decisions | Rule-before-LLM, RAG design, governance | Business market stats |
| Healthcare AI / Compliance | Governance controls | Citation requirement, audit trail, append-only, override reason | Product strategy |

---

## No-API-Key Demo Path (Public / Default)

Public users cloning this repository should not need an `ANTHROPIC_API_KEY` to see the system work — and should not trigger any paid API call by accident. This path covers the deterministic rule engine end to end, plus a preview of representative AI output via pre-generated cached artifacts. Nothing below requires a key.

#### 1. Deterministic-only scenario (clean claim)

- **Claim:** Sample Claim mode → `CLM-003` (CPT 99213 + 80053 + 80048, ICD-10 I10, Medicare)
- Click "Review Claim (rule layer only)"
- **Expected:** NCCI bundling finding (80048 bundled into 80053) — no API call made, no AI section shown beyond the "⚠ AI Agents Disabled" notice.

#### 2. Invalid NPI scenario (short-circuit)

- **Mode:** Manual Claim Entry → enter NPI `1234567890` (fails the Luhn check digit), any CPT/ICD-10 pair
- Click "Review Claim"
- **Expected:** A single HIGH `npi_invalid` finding. "⚡ NPI short-circuit" notice appears; `checks_run` narrows to the NPI check only — NCCI, MUE, and code validity never run, by design (see `agents/orchestrator.py:_rule_layer_short_circuited`).

#### 3. NCCI / MUE / modifier scenario

- **Claim:** Sample Claim mode → `CLM-001` (PRD worked example)
- Click "Review Claim (rule layer only)"
- **Expected:** Three rule findings — NCCI PTP bundling (80048/80053, HIGH), Z00.00 diagnosis-procedure conflict (HIGH), missing modifier 25 (MEDIUM). See Step 2 below for the full walkthrough.

#### 4. ICD-10 invalid / unspecified scenario

- **Claim:** Sample Claim mode → `CLM-002` (CPT 99213 + 85025, ICD-10 J06.9)
- Click "Review Claim (rule layer only)"
- **Expected:** MEDIUM finding — J06.9 (acute upper respiratory infection, unspecified) flagged as an unspecified diagnosis against the real CMS ICD-10-CM order file (`rules/icd10.py`).

#### 5. Optional: AI-enabled scenario — *requires your own `ANTHROPIC_API_KEY`*

- Add your key to `.env` (see README "AI features"), restart the app — sidebar switches to "✅ AI enabled"
- Run "Run Full Review" on any sample claim to see live Coverage and Coding agent findings with real-time citations.

#### Pre-generated AI demo artifacts (no key needed)

Three sample claims have pre-generated AI findings captured from a real agent run, stored in `data/synthetic/cached_ai_demo_artifacts.json`. With no `ANTHROPIC_API_KEY` set, selecting one of these claims and clicking "🚀 Run Full Review" (or "Review Claim (rule layer only)") shows these findings inline, under a clearly labeled **"📋 Pre-generated demonstration results"** banner — read-only, no Accept/Override controls, since they weren't produced by a live run of the current session:

| Claim | Scenario | What it shows |
|---|---|---|
| `CLM-001` | Multi-finding scenario | Rule findings (NCCI, dx conflict, modifier 25) *and* cached Coverage + Coding agent findings together |
| `CLM-002` | Coding finding scenario | Cached Coding agent finding only (CBC vs. unspecified URI diagnosis) |
| `CLM-005` | Coverage finding scenario | Cached Coverage agent finding (Medicare non-covered preventive exam) |

These cached findings are never shown once a real `ANTHROPIC_API_KEY` is present — live agent output always takes priority.

---

## 30-Second Version

> "This is a pre-submission claim review copilot for healthcare revenue cycle teams.
>
> Before a claim is submitted, the system checks it for denial risks — bundled codes, diagnosis conflicts, missing modifiers — and returns findings with severity ratings and the exact policy citation behind each one.
>
> The billing specialist makes every decision: accept the recommendation, override it with a reason. Everything is logged to an immutable audit trail.
>
> It's built on free public CMS data, deterministic rule checks run before any LLM call, and the governance layer — the audit log, the citation requirement, the human-in-loop workflow — was implemented before the AI."

---

## 2-Minute Version

> "Healthcare providers lose roughly $57 per claim to denials — and 86% of those denials are preventable coding errors. The problem isn't lack of rules; it's that the answer to 'will this claim deny' lives across NCCI edit tables, LCD/NCD policy documents, modifier rules, and tribal knowledge that doesn't scale.
>
> This copilot moves denial management upstream. Before a claim leaves the billing department, a set of checks validates coding against CMS reference data and reasons about medical necessity against coverage policy.
>
> Let me show you a claim from the PRD worked example.
>
> [Select CLM-001 in the dropdown. Click Review Claim.]
>
> This is a Medicare claim with four CPT codes and a single diagnosis — Z00.00, a routine exam. The system returns three findings in under a second.
>
> The first is HIGH severity: 80048 is bundled into 80053 — you can't bill both. The citation is the NCCI PTP edit table: specific codes, modifier indicator 0 meaning no bypass is allowed.
>
> The second is also HIGH: Z00.00, a routine exam with no abnormal findings, conflicts with 99214, a problem-oriented E/M. The citation is the ICD-10-CM usage note for Z00.00.
>
> The third is MEDIUM: there may be a missing modifier 25 situation.
>
> The billing specialist — in this case, me — enters their name in the sidebar. They can accept each finding or override it with a documented reason. Once a decision is made, they save it to the audit trail.
>
> [Accept finding 1. Save. Switch to Audit Trail tab.]
>
> Every decision is in this table: who reviewed it, when, what the AI recommended, what the human decided, and why. It's exportable to CSV for compliance workflows.
>
> The architecture is built to extend: the rule layer runs first because lookup tables should never be LLM calls, and the agent layer — coverage validation over real LCD/NCD data — drops in behind it using the same governance infrastructure."

---

## 5-Minute Walkthrough

### Setup (before demo — 30 seconds)
- Streamlit running at localhost:8501
- Reviewer name entered in sidebar: "Dr. Jane Smith" (or your name)
- CLM-001 selected in the Sample Claim dropdown (default mode)
- Audit Trail tab cleared of previous sessions if needed

### Optional: Manual Claim Entry Path (insert after Step 1 or demo separately)

> "I want to show you something more realistic — entering a claim directly the way a billing specialist would.
>
> [Click 'Manual Claim Entry' mode selector]
>
> [Click 'Load Worked Example']
>
> This is the same claim as CLM-001 but entered manually: Medicare, three service lines — 99214 with Z00.00, 80053 with Z00.00, 80048 with Z00.00. A specialist would build this from the encounter.
>
> [Click Review Claim]
>
> Same three findings in under a second. The manual entry path goes through exactly the same rule engine. The system normalizes codes — it will uppercase and strip whitespace before evaluation, so transcription formatting doesn't create false negatives. And it deduplicates across service lines, so if the same diagnosis appears on four lines, it counts once.
>
> The audit trail, the citation view, the accept/override workflow — all of it is identical to the sample claim path."

---

### Opening (30 seconds)

> "I want to walk you through the Denial Prevention Copilot. The problem it solves: healthcare providers lose an average of $57 per denied claim, and roughly 86% of those denials are preventable. Not from complex medical disputes — from coding errors that a specialized tool should catch before the claim is submitted.
>
> What I've built is a pre-submission review workspace. Let me start with the claim."

---

### Step 1: Claim Overview (45 seconds)

> "This is CLM-001, the worked example from the PRD. Medicare Part B, four CPT codes — a comprehensive metabolic panel, a basic metabolic panel, a venipuncture, and an office E/M visit — with a single ICD-10 diagnosis: Z00.00, general adult exam with no abnormal findings. No modifiers.
>
> This claim has two near-certain denial triggers in it. Without a review, it would likely come back in 30–45 days with CO-97 and a medical necessity denial, each requiring rework.
>
> I'll click Review Claim."

[Click Review Claim button]

---

### Step 2: Findings (90 seconds)

> "Under a second. Three findings.
>
> Below the risk banner, you'll see: 'Checks run: NPI validation · NCCI PTP bundling edits · MUE unit limits · Dx-procedure conflict · Modifier 25 requirement.' Five checks, in order — this is what ran on this claim, every time.
>
> **Finding 1 — HIGH: Bundled code pair.** 80048, a basic metabolic panel, is bundled into 80053, the comprehensive panel. Billing both is a CO-97 denial. The citation is the CMS NCCI Practitioner PTP edit table, version v322r0, effective July 1, 2026. Modifier indicator 0 means no bypass — this is a hard bundling rule.
>
> [Expand 'View source excerpt']
>
> The excerpt comes directly from the CMS quarterly file: '80048 (component) is a component of 80053 (comprehensive). Modifier indicator 0: no bypass allowed. Source: ccipra-v322r0-f4.xlsx.' This is not a placeholder — it is the real CMS NCCI data loaded at startup. The coding specialist can verify it against the CMS download at any time.
>
> **Finding 2 — HIGH: Diagnosis conflict.** Z00.00 is a well-visit code — no abnormal findings. Billing it with 99214, a problem-oriented E/M, is a medical necessity mismatch. The citation is the ICD-10-CM coding guideline for Z00.00.
>
> **Finding 3 — MEDIUM: Missing modifier 25.** If a problem E/M and a preventive visit occurred on the same day, modifier 25 is required. This is flagged as medium because it depends on clinical intent that the AI can't know.
>
> Confidence scores are shown on each finding. This one is 75% — which is why you see the 'Manual Review Recommended' note. The system doesn't block the specialist; it flags the uncertainty."

---

### Step 2.5: AI Coverage Analysis (60 seconds) — *Requires ANTHROPIC_API_KEY in .env*

> "Below the rule findings, you'll see an AI Coverage Analysis section. This is the first LLM-backed check — it reasons about medical necessity against coverage policy documents, not just coding rules.
>
> [Click '🤖 Run AI Coverage Analysis']
>
> The system retrieves the policy documents relevant to this claim's diagnosis codes and sends them — along with the claim — to Claude. One API call, per button click. Claude must call one of two tools: `report_coverage_finding` if it identifies a concern, or `no_coverage_concern` if the policies support coverage.
>
> [While spinner runs:]
>
> What makes this different from a rule check: the AI is reasoning over the actual policy text — the LCD language about when a problem-oriented E/M is separately reimbursable alongside a preventive visit. The rule layer knows Z00.00 and 99214 conflict; the AI knows *why* that conflict matters and can explain it in plain language with a citation.
>
> [Finding appears:]
>
> The finding has the same structure as a rule finding: severity badge, issue text, recommendation, and a citation. The citation shows the specific policy section and an excerpt from the LCD text the model was reasoning over.
>
> [Expand 'View policy detail']
>
> The `document_id` in the citation must match one of the policy documents that was actually retrieved. If the model tried to cite a document that wasn't in the retrieved set, the finding would be suppressed. That's the citation grounding rule: no hallucinated policy references.
>
> The AI finding can be accepted, overridden, and saved to the audit trail — identical workflow to rule findings. The audit record shows `source = 'agent_layer'` distinguishing it from `'rule_layer'` findings."

**If no AI key available:**

> "Without an API key, the AI section shows 'AI Coverage Analysis disabled' in the sidebar — the rest of the app runs exactly the same. The architecture is designed so AI is additive: the rule layer provides the deterministic foundation, and the AI layer adds coverage reasoning where the policies are nuanced. Removing the AI key degrades to a rules-only mode, not a broken state."

**Live validation results (2026-06-18):**

| Metric | Result |
|---|---|
| Model | `claude-sonnet-4-5-20250929` |
| Scenario | Labs + Z00.00 (CPT 80053 + 83036, ICD-10 Z00.00) |
| Policies retrieved | 7 |
| Policies sent to model | 3 |
| Finding generated | Yes — HIGH severity |
| Citation grounding | Passed |
| Latency | 7.27s |
| Status | Production Validated |

---

### Step 2.5 Extended: Coverage Policy Demo Scenarios

The coverage policy corpus (Sprint 10) supports 6 specific manual-claim demo scenarios. Use these in Manual Claim Entry mode to show targeted coverage concerns.

#### Demo Scenario 1: Labs with Well-Visit Diagnosis Only (concern expected)

**Claim:** CPT 80053 + 83036, ICD-10 Z00.00, Medicare
- Enter service line 1: CPT 80053, ICD-10 Z00.00
- Enter service line 2: CPT 83036, ICD-10 Z00.00
- Click Review Claim, then Run AI Coverage Analysis
- **Expected:** MEDIUM concern — CMP and HbA1c ordered with only routine exam diagnosis; labs require a documented clinical indication (e.g., E11.9 for diabetes, I10 for hypertension); policies retrieved: `LCD_LAB_MEDICAL_NECESSITY_METABOLIC`, `LCD_HEMOGLOBIN_A1C_FREQUENCY`
- **Talking point:** "The rule layer can flag a NCCI or MUE violation, but it can't tell you that metabolic panels are only covered when there's a clinical condition requiring monitoring. That requires policy reasoning — this is what the agent adds."

#### Demo Scenario 2: Diabetes Management E/M (no concern expected)

**Claim:** CPT 99214, ICD-10 E11.9, Medicare
- Enter service line 1: CPT 99214, ICD-10 E11.9
- Click Review Claim, then Run AI Coverage Analysis
- **Expected:** No concern — E11.9 (Type 2 diabetes) is a covered indication for E/M services; policy retrieved: `LCD_DIABETES_MGMT_E11`
- **Talking point:** "This demonstrates the suppression path: the agent identifies a supported clinical indication and correctly returns no finding rather than a false positive. Precision matters here — overclaiming failures destroys trust."

#### Demo Scenario 3: Annual Wellness Visit + Same-Day E/M (concern expected)

**Claim:** CPT G0439 + 99213, ICD-10 Z00.00, Medicare
- Enter service line 1: CPT G0439, ICD-10 Z00.00
- Enter service line 2: CPT 99213, ICD-10 Z00.00
- Click Review Claim, then Run AI Coverage Analysis
- **Expected:** MEDIUM concern — AWV (G0439) and office E/M on same date require modifier 25 and a documented separate problem diagnosis; without modifier, E/M will be denied as bundled with AWV; policy retrieved: `NCD_AWV_G0438_G0439`
- **Talking point:** "The AWV is a Medicare-specific benefit with specific billing rules. The AI knows the distinction between G0439 (Annual Wellness Visit) and 99213 (problem-focused E/M) and can apply the modifier 25 requirement in plain language — this is the kind of nuanced coverage rule that NCCI edits don't capture."

#### Demo Scenario 4: Unspecified Diagnosis + High-Level E/M (concern expected)

**Claim:** CPT 99215, ICD-10 M54.9, Medicare
- Enter service line 1: CPT 99215, ICD-10 M54.9
- Click Review Claim, then Run AI Coverage Analysis
- **Expected:** MEDIUM concern — M54.9 (Dorsalgia, unspecified) is an unspecified code; ICD-10-CM guidelines require the highest degree of specificity the documentation supports; 99215 audit risk is elevated when the diagnosis is unspecified; policies retrieved: `LCD_DIAGNOSIS_SPECIFICITY_REQ`, `LCD_EM_CODING_LEVEL_SUPPORT`
- **Talking point:** "Two policies are retrieved and the AI synthesizes them: specificity requirements from ICD-10 guidelines plus E/M level documentation requirements. A high-level visit with an unspecified dx is a double audit flag."

#### Demo Scenario 5: Screening Colonoscopy with Polypectomy (concern expected)

**Claim:** CPT 45385, ICD-10 Z12.11, Medicare
- Enter service line 1: CPT 45385, ICD-10 Z12.11
- Click Review Claim, then Run AI Coverage Analysis
- **Expected:** MEDIUM–HIGH concern — when polypectomy (45385) is performed during a screening colonoscopy, the encounter converts from screening to diagnostic; Z12.11 alone as the only diagnosis after polypectomy is insufficient; the actual polyp finding code must be added; policies retrieved: `NCD_COLORECTAL_SCREENING_COLONOSCOPY`, `LCD_COLONOSCOPY_DIAGNOSIS_Z12`
- **Talking point:** "The screening-to-diagnostic conversion rule is one of the most common denial sources in gastroenterology — the CPT code changes, the diagnosis must change with it, and neither the NCCI edit table nor code validity catches this. This is exactly where policy reasoning over LCD text adds value."

#### Demo Scenario 6: HbA1c for Established Diabetic (no concern expected)

**Claim:** CPT 83036, ICD-10 E11.65, Medicare
- Enter service line 1: CPT 83036, ICD-10 E11.65
- Click Review Claim, then Run AI Coverage Analysis
- **Expected:** No concern — HbA1c testing is covered up to 4x/year for patients with diabetes; E11.65 (T2DM with hyperglycemia) is a covered indication; policies retrieved: `LCD_HEMOGLOBIN_A1C_FREQUENCY`, `LCD_DIABETES_MGMT_E11`
- **Talking point:** "This pairs with Scenario 1. Same CPT code (83036), different diagnosis: with E11.65 (diabetes with hyperglycemia), the test is clearly covered. Without a diabetes diagnosis — only Z00.00 — it's not. The retrieval system surfaces both policies either way; the AI reasons about which applies."

---

### Step 3: Human Decision Workflow (60 seconds)

> "Every decision is made by a named specialist. My name is in the sidebar.
>
> [Click Accept on Finding 1]
>
> Finding 1 is accepted — the coder agrees: remove 80048.
>
> [Click Save Decision. Point to 'Saved to audit log.']
>
> That decision is now in the database. The audit trail has the timestamp, the finding, the citation, the decision, and the reviewer name.
>
> Let me show the override path on Finding 3.
>
> [Click Override on Finding 3]
>
> Overrides require a reason. The system won't let you save without one — that's an architectural requirement, not a UX choice. The reason is part of the audit record.
>
> [Type reason: 'Provider confirmed separate diagnosis addressed at same visit. Chart note supports modifier 25.']
> [Click Confirm, then Save Decision]
>
> Now we have two decisions in the audit log: an accepted finding and an overridden finding with a documented reason."

---

### Step 4: Audit Trail (45 seconds)

> "This is the Audit Trail tab.
>
> [Switch to Audit Trail tab]
>
> Every saved decision is here: timestamp in UTC, claim ID, finding ID, severity, what the human decided, who the reviewer was, confidence score, the issue text, the override reason if applicable, and the citation source.
>
> The table is filterable by claim ID or reviewer name. You can imagine a compliance lead filtering to see every override in the last 30 days, or a manager reviewing all decisions by a specific coder.
>
> [Click Export to CSV]
>
> The audit log exports to CSV. The 18-column structure matches what a compliance export would need: it's not a log file — it's a structured decision record.
>
> Two things the database never does: UPDATE and DELETE. Every row is an INSERT. The architecture treats the audit trail as an append-only ledger."

---

### Step 5: Architecture Story (60 seconds)

> "Let me pull back to the architecture for a moment, because the build sequence was as deliberate as the features.
>
> The system has three layers. The rule layer runs first — NCCI checks, MUE limits, code validity, NPI status. These are binary lookups against CMS tables. I built this first because deterministic accuracy matters more than AI here: an LLM reasoning about whether 80048 is bundled into 80053 will sometimes be wrong. The edit table is never wrong.
>
> The governance layer — the audit trail, the citation requirement, the human-in-loop workflow — was built before the AI. Not after. This is a deliberate product decision: if governance is retrofitted after AI, every path that produces findings has to be updated. Built first, every future agent inherits the contract.
>
> The agent layer — you just saw the first one. Coverage validation reasons over retrieved LCD/NCD text — that's where the LLM earns its role: medical necessity determination is reasoning over unstructured policy, not a lookup. Every coverage finding requires a citation sourced from a retrieved document. No citation, no finding. That rule is enforced in the agent, not by convention.
>
> The next phase extends the RAG pipeline: replacing the JSON policy corpus with ChromaDB and real CMS LCD/NCD documents. The agent interface doesn't change — only the retrieval call behind it.
>
> The product builds from the outside in: governance and determinism established, AI layer drops in behind them."

---

### Close (30 seconds)

> "The business case is straightforward. 10–15% of claims are denied on first submission. 86% of those are preventable. The cost to rework a denied claim is $25–$100 depending on practice size, and 65% of denied claims are never resubmitted at all. That's revenue earned and then abandoned.
>
> This copilot moves the work upstream: catch the error before submission, when the fix is cheap. Every recommendation is cited, every decision is logged, and the human always makes the call."

---

## Likely Audience Questions

### Product Management Questions

**Q: Why did you build the governance layer before the AI?**

> Two reasons. First, governance retrofitting is expensive — every path that produces findings has to be updated after the fact. Built first, every future agent inherits the same audit contract automatically.
>
> Second, it was the right product decision for a healthcare workflow. The compliance lead persona from the PRD needs to trust the audit trail before they trust the AI. If the audit trail has gaps from before governance was added, the whole record is suspect. Trust is a launch requirement in this domain, not a launch enhancement.

---

**Q: How did you decide what to include in MVP scope vs. what to defer?**

> I used the PRD's P0/P1/P2 framework explicitly. P0 is what you need to prove the core value proposition: deterministic validation, a cited finding, a human decision, an audit trail. P1 is what strengthens demo quality: batch mode, documentation review, confidence flags. P2 is deliberate scope-out: commercial payer policies, denial analytics — real but not what proves the concept.
>
> The other prioritization signal was dependency order. You can't evaluate AI without governance. You can't govern AI that produces uncited findings. So the build sequence was: rule layer → governance → RAG retrieval → agents. Each phase is a prerequisite for the next.

---

**Q: What would you change about this PRD if you were shipping to a real customer?**

> Two things. First, eligibility denials are the single largest denial category, and this PRD explicitly excludes eligibility verification. That's the right call for an MVP that proves AI reasoning quality, but a production system would need to at minimum consume eligibility status as an input signal — flag claims where eligibility hasn't been verified rather than doing the verification itself.
>
> Second, the override rate threshold. The PRD flags "sustained overrides above 30% on high-severity findings means precision work is needed." I'd want to instrument that from day one and set an alert, not just track it.

---

**Q: How does this compare to what exists in the market?**

> Three incumbent categories. Clearinghouse scrubbers (Waystar, Availity) do high-volume rule edits at submission time but rarely explain the policy basis or suggest a fix — they flag, not recommend. Denial analytics platforms give you retroactive trend analysis. And RCM outsourcing scales human expertise but doesn't keep that expertise in-house.
>
> The positioning is: scrubbers are rules without reasons; analytics are reasons without prevention. This is prevention with reasons. The differentiator isn't the rules — those are public CMS data. It's the retrieval-grounded explanation that a specialist can verify in under a minute, pre-submission, before the claim ages 30 days.

---

### AI Product Management Questions

**Q: Why did you choose RAG over fine-tuning for the coverage agent?**

> Three reasons. First, the source material — LCDs and NCDs — is updated quarterly. Fine-tuned weights bake in a snapshot that goes stale. RAG retrieves from versioned documents, so the system cites the edition it consulted and can be updated by refreshing the index.
>
> Second, citation integrity. The PRD requires that every finding cite the specific document section and effective date. Fine-tuning can't guarantee that a finding maps to a specific retrievable source. RAG grounds the finding in retrieved text — the excerpt is right there in the `Citation.excerpt` field.
>
> Third, Medicare LCDs are not well-represented in LLM training data relative to their specificity. A model reasoning from weights about whether a specific CPT code is covered under a specific LCD for a specific ICD-10 range is unreliable. A model reasoning over the retrieved LCD text is auditable.

---

**Q: How do you handle LLM hallucination?**

> The primary control is the citation requirement. Coverage findings must carry a `citation.doc_id`, `citation.section`, and `citation.excerpt` sourced from retrieved text. The `save_decision()` method in `AuditRepository` will reject a finding without a citation — it's enforced at the persistence layer.
>
> If retrieval returns no relevant chunk for a diagnosis-procedure combination, the Coverage Agent produces no finding rather than a speculative one. Suppression is the correct behavior when the evidence isn't there.
>
> The secondary control is confidence scoring. If the agent's confidence on a finding is below 70%, the UI shows "Manual Review Recommended." The specialist can still accept or override, but they're flagged to look more carefully. And override rates feed back into evaluation — a sustained override rate on high-confidence findings is a precision signal.

---

**Q: How would you evaluate agent quality?**

> The PRD defines three targets: ≥90% finding precision on a golden synthetic set, ≥85% recall, and 100% citation coverage. The golden set is a collection of claims with known correct findings — seeded denial risks with ground-truth expected output.
>
> The evaluation runs as `pytest tests/ -m golden`, which compares the orchestrator's findings against the ground truth and reports precision, recall, and citation coverage per agent type.
>
> Override rate is a second evaluation signal: if specialists are consistently overriding high-severity findings, that's a precision problem. If they're rarely overriding, that's either high quality or alert fatigue — the dismiss pattern per finding type distinguishes the two.

---

**Q: What's the most interesting architecture decision you made?**

> Splitting `finding_id` generation from the rule modules using SHA-256 rather than a UUID or sequential integer.
>
> The problem: the audit log needs a stable foreign key from a decision row back to the specific finding. UUIDs are non-deterministic — a new one generates each run, breaking correlation across reruns of the same claim. Sequential integers are position-dependent — insert a new finding at the front and everything renumbers.
>
> SHA-256 on `(claim_id, rule, issue)` gives you a 12-character deterministic key that's the same across every process, machine, and Python version. The same finding in claim CLM-001 always gets ID `9e76b012c9bf`. The audit record written today and the finding produced six months from now point to the same logical finding.

---

### Healthcare AI / Governance Questions

**Q: How do you ensure the audit trail can't be modified?**

> Architecturally: the `AuditRepository.save_decision()` method is the only path to the database. The UI never touches sqlite3 directly. And `save_decision()` only issues INSERT statements — no UPDATE, no DELETE.
>
> The `initialize_database()` method creates the table with no triggers or permissions that would allow modification. In a production deployment, this would be backed by a PostgreSQL database with row-level INSERT-only permissions for the application user, and a separate read-only role for compliance exports.
>
> For this portfolio, SQLite enforces the append-only behavior by convention (the code never issues UPDATE or DELETE), but the column design anticipates the production enforcement model.

---

**Q: What happens if the AI is wrong and the specialist doesn't catch it?**

> A few things. First, the citation makes it verifiable. The specialist sees the exact policy excerpt. If the AI's reasoning is wrong, the excerpt gives them the information to catch it — the correction is one click away.
>
> Second, every decision is in the audit trail. If a claim is submitted with an AI-recommended fix that turns out to be wrong, the record shows what the AI said, what the human decided, and when. That's accountability the specialist can review.
>
> Third, override rate monitoring. If a finding type has a high override rate, that surfaces in the audit trail data — it's a signal to review that finding type's prompt or retrieval quality.
>
> The product principle is: the AI never submits, corrects, or denies anything autonomously. Every action is a recommendation pending human decision.

---

**Q: How does this handle the "black box" concern that healthcare teams have with AI?**

> The citation requirement is the answer. Every finding has to show the source: the NCCI edit table row, the LCD section, the policy excerpt. If the AI can't cite it, it doesn't say it. That's not a UX feature — it's enforced at the persistence layer.
>
> The billing specialist's question — "show me why, and let me decide" — is answered by the expandable source excerpt on every finding. They're not being asked to trust a model; they're being asked to verify a specific policy reference, which is work they do today, just more slowly.

---

## Architecture Discussion Points

Use these when a viewer asks to go deeper on the technical design.

### Why the rule layer runs first
The NCCI edit table is binary — 80048 is either bundled into 80053 or it isn't. An LLM reasoning about this will be sometimes right and sometimes wrong. A lookup is always right. The principle: deterministic where deterministic suffices; generative where reasoning is required.

### Why NPI runs before NCCI
NPI validation is the first check because an invalid provider identifier makes downstream coding checks unreliable — a claim with a deactivated NPI will be rejected regardless of whether the codes are correct. A HIGH NPI finding (bad format or failed Luhn check digit) short-circuits the rule engine: NCCI, MUE, and code validity do not run. A MEDIUM finding (NPPES lookup failed or NPI not enrolled) is included alongside coding findings so the specialist sees the full picture. NPPES network errors are silenced — a timeout never blocks a review.

When a SHORT-CIRCUIT occurs, the UI displays "⚡ NPI short-circuit: invalid NPI stopped evaluation. Fix the NPI to run NCCI, MUE, and code-validity checks." — so the specialist knows exactly what didn't run and why. The five-item checks-run list narrows to just the NPI check. This is driven by `CHECKS_RUN` exported from `rule_engine.py` — the UI consumes the rule engine's own metadata rather than hardcoding check labels.

### Why finding_id is SHA-256
The audit log is append-only. The decision row is written once and never updated. The foreign key from decision → finding must remain valid if the claim is re-reviewed, if findings are reordered, or if the system adds agent findings alongside rule findings. SHA-256 on (claim_id, rule, issue) is process-stable and position-independent.

### Why Citation is a first-class dataclass, not a string
Three reasons: it maps field-for-field to the audit schema (no parsing at write time), it carries the excerpt for inline display, and it enforces the "no citation → no finding" rule at the type level (you can't construct a Finding without a Citation).

### Why governance came before AI
Governance retrofitting is expensive: every agent output path has to be updated. Built first, agents inherit the contract. Specifically: `Finding` is already audit-ready, `Citation` fields map to audit columns, and `finding_id` is stable across reruns — all before a single LLM call is made.

### Where the AI goes in
The Coverage Validation Agent sits between the vector store (retrieval) and the Claude API (reasoning). It queries ChromaDB for LCD/NCD chunks relevant to the claim's diagnosis-procedure pair, passes the retrieved text to Claude with structured tool use, and forces the model to emit a `Finding`-shaped object. The `citation.doc_id` must reference a chunk that was actually retrieved — the agent cannot hallucinate a document ID.

---

## Product Strategy Discussion Points

### The positioning in one sentence
"Scrubbers are rules without reasons. Analytics are reasons without prevention. This is prevention with reasons."

### Why public CMS data is the right foundation
All the raw material for explainable denial prevention has been free all along — NCCI tables, ICD-10-CM, LCDs, HCPCS, the NPI Registry. The gap wasn't the data; it was a product that assembles it into a workflow specialists trust.

### The long-term platform play (PRD §3)
Claims review is the entry point. The same governed agent architecture, the same policy intelligence layer, the same evidence retrieval framework that reviews a claim can drive: prior authorization requirement detection (Phase 2 in the PRD roadmap), appeals drafting (Phase 3), and eventually EDI integration as a platform API (Phase 4). Build the decision layer once, with governance designed in, and each new workflow is an extension.

### Why this validates the market
The enterprise automation industry is moving toward pre-submission intelligence — denial prevention and prior-authorization agents are an active product category. This project is a transparent reference implementation of the decision layer underneath that category: evidence-grounded findings, public data only, every recommendation citable.

### The human-in-loop is a feature, not a limitation
Revenue cycle specialists don't want an AI that submits claims for them — they want an AI that does the research so they can make better decisions faster. "AI researches, humans decide" is not a safety disclaimer; it's the value proposition for the primary user persona.
