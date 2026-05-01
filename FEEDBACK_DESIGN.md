# 🔁 Feedback Design — Learning Loop Signals

> **Date:** 28/04/2026
> **Status:** Design only — no implementation
> **Purpose:** Define how `feedback: bool` signals should be generated in real usage for `MemoryConfidenceFeedbackLayer`

---

## Context

The learning loop currently has an unfilled gap:

```
BehaviorPipeline.run(intent, behavior, identity)
  → decision_trace

MemoryConfidenceFeedbackLayer.apply(decision_trace, feedback, identity)
  → adjusted_identity

MemoryPerformanceTracker.apply(decision_trace, feedback, state)
  → updated_performance_state
```

The `feedback: bool` parameter exists in both `MemoryConfidenceFeedbackLayer.apply()` and `MemoryPerformanceTracker.apply()`, but **no code generates this signal**. The entire learning pipeline is idle — patterns accumulate via `MemoryPatternIntegrator` but never get reinforced or weakened based on real outcomes.

This document designs the feedback sources.

---

## 1. Explicit User Feedback

Direct signals from the user about the bot's behavior.

### 1.1 Direct Approval / Rejection

| Aspect | Description |
|---|---|
| **Detection** | User responds to a behavior-related question with "sí"/"no", "me gusta"/"no me gusta", or emoji reactions (👍/👎). |
| **When it fires** | After the bot proposes a behavior change: "¿Te parece bien este tono?" The user's next message is scanned for approval/rejection keywords. |
| **Signal mapping** | Approval keywords → `feedback=True`. Rejection keywords → `feedback=False`. |
| **Reliability** | 🔴 **Medium** — Users may say "sí" out of politeness rather than genuine approval. Context matters. |
| **Risks** | False positives from ambiguous language ("sí" could mean "yes, continue" not "yes, the behavior was correct"). Users may answer a different question. Needs clear conversation context to disambiguate. |
| **Rate** | Low frequency — only fires when bot explicitly asks for feedback. |

**Scoring rule proposal:**
- `feedback=True` weight: 0.5 (discounted because of politeness risk)
- `feedback=False` weight: 1.0 (higher confidence — users are more likely to be honest about dislikes)

### 1.2 Explicit Correction Commands

| Aspect | Description |
|---|---|
| **Detection** | User explicitly says "más formal", "sé más técnico", "no, quiero algo casual", "más corto", etc. |
| **When it fires** | Anytime the user modifies the bot's behavior with a directive. |
| **Signal mapping** | If user corrects toward a value that matches the decision → `feedback=True` (user confirmed). If user corrects away from the decision → `feedback=False` (decision was wrong). If the correction matches a different dimension's value → partial feedback per dimension. |
| **Reliability** | 🟢 **High** — The user is explicitly stating their preference. |
| **Risks** | Ambiguous mapping: "más técnico" could mean tone=technical OR depth=deep. Needs keyword-to-dimension mapping. The correction itself is a learning opportunity but the feedback signal is about the *previous* decision, not the new preference. |
| **Rate** | Medium frequency — users correct bots naturally. |

**Keyword-to-dimension mapping proposal:**
```
tone keywords: ["formal", "casual", "técnico", "directo", "profesional", "relajado"]
depth keywords: ["más profundo", "más corto", "resume", "detalla", "en breve", "extiéndete"]
style keywords: ["conciso", "estructurado", "narrativo", "lista", "puntos", "bullet"]
```

---

## 2. Implicit Signals (Conversation Patterns)

Behavioral signals derived from how the user interacts with the bot, without explicit feedback.

### 2.1 Conversation Continuation

| Aspect | Description |
|---|---|
| **Detection** | User sends a follow-up message within N minutes (e.g., 5 min) after the bot's response, AND the follow-up is NOT a correction or complaint. |
| **Signal mapping** | If the user continues the conversation naturally → `feedback=True` (the behavior was appropriate enough to keep engaging). If the user stops responding for >30 min → ambiguous (could be satisfied or frustrated — NOT a feedback signal). |
| **Reliability** | 🟡 **Low-Medium** — Correlation, not causation. The user may continue despite bad behavior if they need information. A stopped conversation may mean satisfaction, not dissatisfaction. |
| **Risks** | False positives: user continues despite bad behavior (they need the answer). False negatives: user leaves satisfied after getting a complete answer. Confirmation bias: reinforces status quo behavior even when change would be better. |
| **Rate** | Very high frequency — every message generates this signal. Must be carefully gated to avoid overwhelming the learning pipeline. |

**Gating proposal:**
- Only emit signal if conversation continues for ≥3 exchanges after the behavior decision
- Discount factor: 0.3 (low confidence implicit signal)
- Never use conversation STOP as a negative signal

### 2.2 Repetition Detection

| Aspect | Description |
|---|---|
| **Detection** | User asks the same or very similar question within a short window (same intent, same topic). |
| **Signal mapping** | If user repeats a question → `feedback=False` for the original behavior decision. The bot's response was not satisfying enough. |
| **Reliability** | 🟢 **High** — Repetition is a strong signal that the previous response missed the mark. |
| **Risks** | User may repeat for non-behavior reasons (they forgot, they want more detail on a different aspect). The repetition may be about content, not behavior. Must check semantic similarity, not just keyword overlap. |
| **Rate** | Low frequency — repetition is relatively rare. |

**Detection proposal:**
- Use `MemoryDecisionLayer._word_based_match()` or `SequenceMatcher` on the user's current message vs. their last N messages
- If similarity ≥ 0.7 within the same intent → possible repetition
- If similarity ≥ 0.85 → probable repetition → `feedback=False`

### 2.3 Message Length Trend

| Aspect | Description |
|---|---|
| **Detection** | Track user message length over time. A sustained increase suggests engagement. A sharp decrease or one-word answers suggest disengagement. |
| **Signal mapping** | Increasing length trend (over 5+ messages) → `feedback=True` (user is engaged, behavior is working). Decreasing trend → no signal (too many confounds). One-word answers after a behavior change → possible `feedback=False`. |
| **Reliability** | 🔴 **Low** — Too many confounds (user in a hurry, topic change, mobile vs desktop). |
| **Risks** | High false positive rate. Users typing on mobile send shorter messages regardless of satisfaction. Topic shifts naturally change message length. |
| **Rate** | Medium frequency (per message, but requires window). |

**Recommendation:** Do NOT use this as a standalone feedback signal. Use only as a tiebreaker or supporting signal combined with others.

### 2.4 Response Time Delta

| Aspect | Description |
|---|---|
| **Detection** | Measure time between bot response and user's next message. Compare to the user's historical average response time. |
| **Signal mapping** | Faster-than-average reply → `feedback=True` (user is engaged and eager to continue). Slower-than-average → no signal (too many confounds). |
| **Reliability** | 🔴 **Low** — User may reply slowly because they're busy, not because they disliked the response. |
| **Risks** | Confounds: time of day, interruptions, multitasking, reading comprehension. Noisy signal that requires large sample sizes. |
| **Rate** | Per message, but requires baseline. |

**Recommendation:** Do NOT use. Too unreliable for individual feedback signals.

---

## 3. System-Based Validation

Signals derived from the system's own operations, independent of user behavior.

### 3.1 Task Execution Success

| Aspect | Description |
|---|---|
| **Detection** | After the bot executes a task (build_app, execute_plan, notion_create), check the result status. |
| **Signal mapping** | Task succeeds (status=200, no "error" in response) → `feedback=True` (the behavior that led to this task was appropriate). Task fails (error response, exception) → `feedback=False` (the behavior should be adjusted). |
| **Reliability** | 🟢 **High** — Objective success/failure. No user interpretation needed. |
| **Risks** | The task outcome may be unrelated to the behavior decision (rate limits cause failure, but behavior was fine). Must separate infrastructure errors from behavioral errors. Only emit if the failure is plausibly related to behavior (e.g., wrong tool choice, bad parameter). |
| **Rate** | Low frequency — depends on how often the AI uses tools. |

**Gating proposal:**
- Only emit feedback for behavior-affecting failures: wrong tool call, bad parameters, missing permission
- Do NOT emit for: network errors, rate limits, API timeouts
- Track in `decision_trace` metadata whether the task was behavior-correlated

### 3.2 AI Cascade Depth

| Aspect | Description |
|---|---|
| **Detection** | Track how many API fallbacks were needed to generate the response. Record the `attempt_index` returned from `call_ai_with_fallback()`. |
| **Signal mapping** | Attempt index 0 (primary API, Groq 1) → no signal (baseline). Attempt index ≥ 3 (degraded model, smaller model) → possible `feedback=False` if the response quality is lower. Deeper fallback → lower response quality expectation. |
| **Reliability** | 🟡 **Medium** — Cascade depth correlates with response quality (deeper = smaller/cheaper models). But the correlation is loose — Groq 3 (index 3) is still a capable model. |
| **Risks** | False positives: a deep fallback may still produce excellent responses. False negatives: primary API may produce bad responses too. The feedback signal should be about *actual* response quality, not *expected* quality. |
| **Rate** | Per message — always available. |

**Recommendation:** Do NOT use cascade depth as standalone feedback. Combine with other signals (e.g., if deep fallback AND user repetition → more confident negative feedback).

### 3.3 Tool Call Validity

| Aspect | Description |
|---|---|
| **Detection** | After a tool call, check if the AI made a valid tool choice given the context. For example: did the AI call `notion_search` when memory already had the answer? Did it call `notion_create` without permission? Did it hallucinate a page ID? |
| **Signal mapping** | Valid tool call → `feedback=True`. Hallucinated tool call (fake page IDs, wrong parameters) → `feedback=False`. Unnecessary tool call (bypassing memory) → `feedback=False`. |
| **Reliability** | 🟢 **High** — Tool call validity is objectively measurable. Hallucinated IDs are detectable. |
| **Risks** | Requires implementing validation logic for each tool. Some tool calls are hard to validate (e.g., `notion_search` with valid-but-wrong search terms). The correlation to behavior decision may be weak — tool call validity is more about AI quality than behavior. |
| **Rate** | Medium frequency — every AI loop with tool calls. |

**Detection examples:**
- `_clean_page_id(page_id)` returns None → hallucinated ID → `feedback=False`
- `notion_create` called without user saying "sí" or "yes" → violating system prompt → `feedback=False`
- `notion_search` called right after memory returned the same data → redundant → `feedback=False`

### 3.4 Behavior Stability Over Time

| Aspect | Description |
|---|---|
| **Detection** | Track how often the behavior changes across similar intents. If the same intent (e.g., "greeting") gets wildly different behavior values across 10+ interactions, the patterns may be unstable. |
| **Signal mapping** | High variance in behavior per intent → `feedback=False` for all recent decisions (inconsistent). Low variance → no signal (stable, but not necessarily correct). |
| **Reliability** | 🟡 **Medium** — Variance is a useful diagnostic but not a direct correctness signal. |
| **Risks** | Low variance could mean the system is stuck (deadlock in incorrect behavior). High variance could be legitimate exploration. |
| **Rate** | Very low frequency — requires N+ interactions per intent. |

---

## 4. Signal Integration Design

### 4.1 Signal Priority Matrix

| Signal | Reliability | Frequency | Behavior Correlation | Use as Primary? |
|---|---|---|---|---|
| Explicit rejection ("no") | 🟢 High | Low | 🟢 High | ✅ Yes |
| Explicit correction ("más formal") | 🟢 High | Medium | 🟢 High | ✅ Yes |
| Explicit approval ("sí") | 🟡 Medium | Low | 🟡 Medium | ⚠️ Discounted 0.5× |
| Task execution success | 🟢 High | Low | 🟡 Medium | ⚠️ Gated |
| Tool call validity | 🟢 High | Medium | 🟡 Medium | ✅ Yes (when measurable) |
| Repetition detection | 🟢 High | Low | 🟡 Medium | ⚠️ Needs 0.85+ threshold |
| Conversation continuation | 🟡 Low | High | 🔴 Low | ❌ As standalone |
| Message length trend | 🔴 Low | Medium | 🔴 Low | ❌ Not used |
| Response time delta | 🔴 Low | Medium | 🔴 Low | ❌ Not used |
| AI cascade depth | 🟡 Medium | High | 🔴 Low | ❌ As standalone |
| Behavior stability | 🟡 Medium | Very Low | 🟡 Medium | ❌ Diagnostic only |

### 4.2 Feedback Aggregation Strategy

Since multiple signals may arrive for the same decision, a **weighted voting system** is recommended:

```
feedback_vote = sum(signal.weight * signal.direction for signal in signals)
final_feedback = feedback_vote > 0  # True if net positive

# With confidence weighting:
confidence_score = sum(signal.weight * abs(signal.direction) for signal in signals)
```

**Where:**
- `signal.weight` = reliability score (0.0–1.0)
- `signal.direction` = +1 for positive, -1 for negative, 0 for neutral/undefined

**Example:**
```
User says "sí" → weight=0.5, direction=+1 → +0.5
Task succeeded → weight=0.8, direction=+1 → +0.8
Net: +1.3 → feedback=True, confidence=1.3
```

### 4.3 Feedback Gating

Before emitting any feedback signal, check:
1. **Decision existed** — Was there a non-"none" source and non-zero confidence?
2. **Minimum data** — Has the user had enough interactions (≥5) for patterns to be meaningful?
3. **Cooldown** — Don't fire multiple feedback signals for the same decision from different signal sources within a short window (e.g., 1 minute)
4. **Idempotency** — Don't re-fire feedback for a decision trace that was already processed

---

## 5. Integration Points in Existing Code

### 5.1 Where to inject (no implementation)

The feedback signal generation should be added in `orchestrators/conversation_orchestrator.py` within `process_message()`:

| Injection point | When | Available signals |
|---|---|---|
| After `MemoryAdaptiveBehaviorLayer.apply()` in the complex profile path | User asked a complex memory question | Explicit feedback, repetition |
| After each tool call in the AI loop | AI used a tool | Task success, tool validity |
| After user responds to a bot prompt | Bot asked for confirmation | Explicit approval/rejection |
| At the end of `process_message()` (before returning) | After full response is sent | Conversation continuation, cascade depth |

### 5.2 Required state additions

To support feedback generation, the conversation flow would need to:
- **Store** the last `decision_trace` per chat_id (it's currently not persisted)
- **Store** the last `behavior` per chat_id (for comparison with corrections)
- **Track** recent user message history (for repetition detection)
- **Track** recent tool call results (for task validation)

These already partially exist in `_recent_memory` and `chat_states`.

---

## 6. Risks Overview

| Risk | Severity | Mitigation |
|---|---|---|
| **Noisy signals cause pattern oscillation** | 🔴 High | StabilityGuardLayer already prevents updates until MIN_TOTAL=5, STABLE_TOTAL=10 |
| **Explicit acceptance politeness bias** | 🟡 Medium | Discount explicit "sí" to 0.5× weight |
| **False negatives from cascade depth** | 🟡 Medium | Don't use cascade depth alone. Combine with other signals. |
| **Feedback loop amplifies wrong patterns** | 🔴 High | Require multiple consistent signals before updating. AdaptiveStrategyLayer has slow, monotonic adjustments. |
| **User confusion from bot experiments** | 🟡 Medium | Only adjust behavior on strong signals (confidence ≥ 2.0 for dimension change). |
| **Over-correction from one-time events** | 🟡 Medium | Noise gate in StabilityGuardLayer (min_delta=0.05) prevents tiny adjustments from accumulating. |
| **Feedback not representative** | 🔴 High | The user who gives feedback may not represent the user population (self-selection bias). In a single-user system, this is less risky. |

---

## 7. Summary

The most practical first step is to implement **three signal sources**:

```
Priority 1 — Tool Call Validity
  Easy to detect, highly reliable, already measurable
  Integration: check tool call results in the AI loop

Priority 2 — Repetition Detection
  High signal value, relatively simple
  Integration: compare user messages via SequenceMatcher

Priority 3 — Explicit Feedback (limited)
  Start with negative only (rejections are more reliable than approvals)
  Integration: scan for keywords after behavior-related exchanges
```

These three cover the most reliable signals with the least implementation risk. Explicit approval ("sí") and conversation continuation signals can be added later after the basic loop is validated.

The existing `MemoryStabilityGuardLayer` and `MemoryAdaptiveStrategyLayer` provide sufficient safety against noisy signals — the guard won't allow strategy updates until each source has ≥10 tracked decisions, and adjustments are clamped to [0.1, 1.0] ranges.
