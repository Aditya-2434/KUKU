# KuKu AI Generalist Assignment — Solution Document

**Problem 1: Find the Promos (Ads)**
Bandi Aditya | Roll No: 230283 | BT MSE | IIT Kanpur | adityab23@iitk.ac.in

---

## Why Problem 1

The input pack contains millisecond-precise, structured screenplay data — every line of
dialogue, camera beat, and action is timestamped. This makes promo-finding tractable with
a text pipeline rather than computer-vision or audio processing. The output (timestamped
windows) is immediately verifiable by a human editor, which is exactly what the brief asks for.

---

## How It Works

```
50 × .txt scripts
      │
  [parser.py]      Timed events per episode (DIALOGUE, ACTION, CAMERA, SOUND_FX)
      ▼
  [extractor.py]   Sliding 20–60s window at 5s steps → 9,728 candidate segments
                   + cross-episode tail-of-N + head-of-N+1 stitching (1,604 extra)
      ▼
  [local_scorer.py / scorer.py]   Score each candidate on 4 dimensions (0–10)
      ▼
  [main.py]        Composite score → deduplicate (70% IoU) → rank → save outputs
```

**Composite score:** `0.35 × hook + 0.35 × cliffhanger + 0.20 × standalone + 0.10 × emotion`

Hook and cliffhanger share the highest weight — they are the two criteria Kuku's brief
explicitly calls non-negotiable.

---

## Key Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Window step | 5 s | Coarser step = fewer candidates = manageable volume |
| Cross-episode promos | Tail-of-N + head-of-N+1 | Covers the dominant microdrama cliffhanger pattern |
| Deduplication | 70% IoU overlap | Stops the same scene filling all top-20 slots |
| Two scorer modes | Local rules + Gemini Flash | Local = zero cost for submission; Gemini = richer descriptions in production |
| Pre-filter | Top 10/ep by dialogue density | Trims 9,728 → 990 before scoring without losing likely winners |

---

## Assumptions

- Script timestamps ≈ actual video timestamps (no verification without the video files).
- Strong dialogue in text ↔ strong visual hook (assumed; no video available).
- Consecutive episodes are always continuous story.

---

## Tradeoffs & What Was Left Out

**Speed vs. coverage.** Pre-filtering to top-10 per episode risks missing a great promo
ranked 11th by heuristic. A second-pass re-scorer would catch this but doubles compute.

**Rules vs. LLM.** The local scorer uses keyword banks and emotion tags already embedded
in the screenplay format — fast, deterministic, zero hallucination. The Gemini scorer
(`scorer.py`) produces richer natural-language explanations but costs quota. Both are
drop-in interchangeable (same output schema).

**English only.** KuKu has Hindi/Tamil shows. A production version needs
language-specific prompt tuning or translated scripts.

---

## Failure Modes (Honest)

| Failure | Why | Mitigation |
|---------|-----|------------|
| Pure-camera windows score 0 | No dialogue → standalone = 0 | Pre-filter by dialogue density |
| Ep 1–2 dominate top rankings | Strongest emotional peak in the show | 1-promo-per-episode cap in report |
| Cross-episode scores noisier | Two disconnected transcript blocks | Separate tag in output; reviewer flag |
| Mid-scene windows lack cliffhangers | Scene continues past the window | Known gap; noted in `quality_report.md` |
| Text-only blindspot | Slaps/gasps score low without audio/video | Audio+video embeddings in future version |
| **Gemini daily quota exhausted** | Debug runs consumed the daily free-tier cap before the full pipeline completed. The first 20 batches (100 clips) did score — proving the API path works. | Submission uses `generate_outputs.py`; run `quick_test.py` after quota resets (midnight PT / ~12:30 PM IST) |

---

## Scale & Quality

**Current:** 50 episodes · 9,728 candidates · 990 scored · runs in **6 seconds** (local).

**At 500 episodes/week:** async Gemini API calls + Cloud Tasks queue + content-hash caching
(skip re-scoring unchanged scripts). Human editor reviews top-10 per episode and marks
approve/reject → labels feed a fine-tuned ranker over time. Model swap takes one line
(`GEMINI_MODEL=...` in `.env`).

**How I know it's good:** Top promos from Ep 1–2 (the altar betrayal, Juliana's defiant
speech, Clarissa's cruelest line) rank in the top 5 — matching what a human editor
would intuitively pick. The `quality_report.md` documents every failure class honestly,
and `promos_raw.json` lets any evaluator re-weight dimensions without re-running the tool.

---

## What Actually Ran

**Local pipeline (`generate_outputs.py`) — completed, all outputs generated:**

| Step | Result |
|------|--------|
| Episodes parsed | 50 / 50, zero failures |
| Candidates extracted | 9,728 (8,124 single-ep + 1,604 cross-ep) |
| Scored (local rules) | 990 → deduplicated to **673 unique promos** |
| Runtime | **~6 seconds**, zero API calls |
| Output files | `promos_raw.json` · `promos_report.md` · `quality_report.md` |

**Gemini API pipeline (`main.py`) — integration confirmed, full run blocked by daily quota:**

The first 20 batches returned `[5/5 scored]` before hitting `429 RESOURCE_EXHAUSTED` —
proof the API integration is correct. The 429 is a daily cap (not a code bug): ~60 calls
were consumed across debug runs. Run `python quick_test.py` after the quota resets
(midnight PT / ~12:30 PM IST) to get live Gemini scores on 10 clips saved to
`outputs/api_spot_check.json`. Both scorers share the same output JSON schema —
swapping them requires changing one import line.

---

## If I Had More Time

Audio/video timestamp verification · fine-tuned ranker from editor labels ·
multi-language support · Streamlit UI for editor approve/reject workflow.
