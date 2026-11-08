"""
main.py — Promo Finder Orchestrator
=====================================
Entry point for the KuKu AI Promo Finder tool.

Usage:
    python main.py

Outputs:
    outputs/promos_raw.json     — Full scored promo data (machine-readable)
    outputs/promos_report.md    — Human-readable ranked report
    outputs/quality_report.md   — Self-critique: where the tool fails

Pipeline:
    1. Parse all 50 episode scripts  (parser.py)
    2. Extract candidate segments    (extractor.py)
    3. Score via Gemini Flash        (scorer.py)
    4. Rank, deduplicate, report     (this file)
"""

import json
import os
import pathlib
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR      = pathlib.Path(__file__).parent
EPISODES_DIR  = BASE_DIR / os.getenv("EPISODES_DIR", "I Married a Broken Soldier. He was a Duke")
OUTPUT_DIR    = BASE_DIR / os.getenv("OUTPUT_DIR", "outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

RAW_JSON_PATH      = OUTPUT_DIR / "promos_raw.json"
REPORT_MD_PATH     = OUTPUT_DIR / "promos_report.md"
QUALITY_MD_PATH    = OUTPUT_DIR / "quality_report.md"

# ── Import our modules ────────────────────────────────────────────────────────
from parser    import parse_all_episodes
from extractor import extract_all_candidates
from scorer    import score_candidates


# ──────────────────────────────────────────────────────────────────────────────
# Step 4a: Deduplicate overlapping single-episode promos
# ──────────────────────────────────────────────────────────────────────────────

def deduplicate(scored: list, overlap_threshold: float = 0.7) -> list:
    """
    Remove candidates whose time window overlaps heavily with a higher-scoring
    candidate from the same episode.  Keeps the best in each overlapping cluster.
    """
    scored_sorted = sorted(scored, key=lambda c: c["composite_score"], reverse=True)
    kept = []

    def overlap_ratio(a, b):
        """Intersection-over-union of two [start, end] intervals."""
        if a["episode_nums"] != b["episode_nums"]:
            return 0.0
        # Only handle single-segment promos for dedup
        if len(a["segments"]) > 1 or len(b["segments"]) > 1:
            return 0.0
        s_a, e_a = a["segments"][0]["start"], a["segments"][0]["end"]
        s_b, e_b = b["segments"][0]["start"], b["segments"][0]["end"]
        inter = max(0, min(e_a, e_b) - max(s_a, s_b))
        union = max(e_a, e_b) - min(s_a, s_b)
        return inter / union if union > 0 else 0.0

    for cand in scored_sorted:
        dominated = False
        for good in kept:
            if overlap_ratio(cand, good) >= overlap_threshold:
                dominated = True
                break
        if not dominated:
            kept.append(cand)

    return kept


# ──────────────────────────────────────────────────────────────────────────────
# Step 4b: Generate Markdown report
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_time(seconds: float) -> str:
    """Format float seconds as MM:SS.s"""
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m:02d}:{s:04.1f}"


def generate_report(ranked: list, top_n: int = 20) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# KuKu Promo Finder — Ranked Results",
        f"*Show: I Married a Broken Soldier. He was a Duke*  |  *Generated: {ts}*",
        f"*Total promos found: {len(ranked)}  |  Showing top {min(top_n, len(ranked))}*",
        "",
        "---",
        "",
    ]

    for rank, cand in enumerate(ranked[:top_n], 1):
        eps = cand["episode_nums"]
        ep_str = f"Ep {eps[0]}" if len(eps) == 1 else f"Ep {eps[0]}+{eps[1]}"
        dur = cand["total_duration"]

        # Segment timestamps
        seg_lines = []
        for seg in cand["segments"]:
            seg_lines.append(
                f"**Ep {seg['episode_num']}** `{_fmt_time(seg['start'])}` → `{_fmt_time(seg['end'])}`  "
                f"({seg['duration']:.0f}s)"
            )

        hook_score   = cand.get("hook_strength", "?")
        cliff_score  = cand.get("cliffhanger_quality", "?")
        stand_score  = cand.get("standalone_clarity", "?")
        emo_score    = cand.get("emotional_intensity", "?")
        composite    = cand.get("composite_score", 0.0)

        lines += [
            f"## #{rank}  —  {ep_str}  |  {dur:.0f}s  |  Score: **{composite:.2f}/10**",
            "",
            "\n".join(seg_lines),
            "",
            f"| Dimension | Score |",
            f"|-----------|-------|",
            f"| 🎣 Hook strength | {hook_score}/10 |",
            f"| 🎬 Cliffhanger quality | {cliff_score}/10 |",
            f"| 👁 Standalone clarity | {stand_score}/10 |",
            f"| ❤️ Emotional intensity | {emo_score}/10 |",
            "",
            f"**Hook:** {cand.get('hook_description', 'N/A')}",
            "",
            f"**Cliffhanger:** {cand.get('cliffhanger_desc', 'N/A')}",
            "",
            f"**Why it works:** {cand.get('why_it_works', 'N/A')}",
            "",
            "<details>",
            "<summary>Full transcript</summary>",
            "",
            "```",
            cand.get("transcript", ""),
            "```",
            "",
            "</details>",
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Step 4c: Quality / failure report
# ──────────────────────────────────────────────────────────────────────────────

def generate_quality_report(all_scored: list, ranked: list) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Find lowest-scoring promos for failure analysis
    bottom = sorted(all_scored, key=lambda c: c["composite_score"])[:10]
    score_dist = {}
    for c in all_scored:
        bucket = round(c["composite_score"])
        score_dist[bucket] = score_dist.get(bucket, 0) + 1

    lines = [
        "# Quality Report — Where the Promo Finder Fails",
        f"*Generated: {ts}*",
        "",
        "## Score Distribution",
        "",
        "| Score Bucket | Count |",
        "|---|---|",
    ]
    for bucket in sorted(score_dist):
        lines.append(f"| {bucket}/10 | {score_dist[bucket]} |")

    lines += [
        "",
        "## Known Failure Modes",
        "",
        "### 1. Pure CAMERA description windows",
        "Many windows contain only camera direction text with no dialogue.",
        "These get low standalone scores because there's nothing audible.",
        "**Fix:** Weight episodes by dialogue density before pre-filtering.",
        "",
        "### 2. Mid-scene exposition",
        "Some high-emotion dialogue occurs in the middle of scenes but lacks",
        "a natural cliffhanger ending (episode just continues after the window).",
        "The LLM correctly penalises these but we still generate many candidates.",
        "**Fix:** Use scene-boundary-aware windowing (don't split mid-scene).",
        "",
        "### 3. Cross-episode promos are harder to evaluate",
        "The LLM receives two disconnected transcripts and must imagine the cut.",
        "Without visual reference, cliffhanger scores may be under/over-estimated.",
        "**Fix:** Add a 'cut quality' criterion specifically for multi-segment promos.",
        "",
        "### 4. Repetitive high-scoring moments",
        "Episode 1–2 (wedding betrayal) dominates top rankings because the",
        "emotional peak is very strong. This is correct but would lead to",
        "posting the same scene repeatedly.",
        "**Fix:** Enforce 1 promo per episode in the final top-20 ranking.",
        "",
        "### 5. LLM hallucination risk",
        "Gemini Flash may describe a hook that isn't actually in the first 3 seconds.",
        "We mitigate this by explicitly passing `first_3s_text` and `last_5s_text`",
        "as separate fields, so the LLM scores based on what we show, not what it imagines.",
        "",
        "## Lowest-Scoring Candidates (Tool Misfires)",
        "",
    ]

    for i, cand in enumerate(bottom, 1):
        ep = cand["episode_nums"]
        lines += [
            f"### Bottom #{i}  — Ep {ep}  |  Score: {cand['composite_score']:.2f}",
            f"- Transcript preview: `{cand['transcript'][:120]}...`",
            f"- LLM note: {cand.get('why_it_works', 'N/A')}",
            "",
        ]

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  KuKu Promo Finder — Starting Pipeline")
    print("=" * 60)

    # ── Step 1: Parse ─────────────────────────────────────────────────────────
    print("\n[1/4] Parsing episode scripts...")
    episodes = parse_all_episodes(str(EPISODES_DIR))
    print(f"  → {len(episodes)} episodes parsed.\n")

    # ── Step 2: Extract candidates ────────────────────────────────────────────
    print("[2/4] Extracting candidate promo segments...")
    candidates = extract_all_candidates(episodes)
    print(f"  → {len(candidates)} total candidates.\n")

    # ── Step 3: Score via Gemini ──────────────────────────────────────────────
    print("[3/4] Scoring candidates with Gemini Flash...")
    print("  (This may take a few minutes due to free-tier rate limits)")
    try:
        # top_k_per_episode=5 keeps total LLM calls under ~100 (free-tier safe)
        scored = score_candidates(candidates, top_k_per_episode=5)
    except ValueError as e:
        print(f"\n  ✗ ERROR: {e}")
        sys.exit(1)
    print(f"  → {len(scored)} candidates scored.\n")

    # ── Step 4: Rank, deduplicate, save ──────────────────────────────────────
    print("[4/4] Ranking and generating reports...")
    deduped = deduplicate(scored)
    ranked  = sorted(deduped, key=lambda c: c["composite_score"], reverse=True)

    # Save raw JSON (strip heavy events lists to keep file readable)
    def slim(c):
        out = {k: v for k, v in c.items() if k != "segments"}
        out["segments"] = [
            {kk: vv for kk, vv in s.items() if kk != "events"}
            for s in c.get("segments", [])
        ]
        return out

    with open(RAW_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump([slim(c) for c in ranked], f, indent=2, ensure_ascii=False)
    print(f"  ✓ Raw JSON saved → {RAW_JSON_PATH}")

    report_md = generate_report(ranked, top_n=20)
    with open(REPORT_MD_PATH, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"  ✓ Promo report saved → {REPORT_MD_PATH}")

    quality_md = generate_quality_report(scored, ranked)
    with open(QUALITY_MD_PATH, "w", encoding="utf-8") as f:
        f.write(quality_md)
    print(f"  ✓ Quality report saved → {QUALITY_MD_PATH}")

    # ── Print top 5 to console ────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  TOP 5 PROMOS")
    print("=" * 60)
    for rank, cand in enumerate(ranked[:5], 1):
        ep  = cand["episode_nums"]
        seg = cand["segments"][0]
        print(
            f"  #{rank}  Ep{ep}  "
            f"{_fmt_time(seg['start'])}→{_fmt_time(seg['end'])}  "
            f"Score={cand['composite_score']:.2f}  "
            f"| {cand.get('why_it_works','')[:60]}"
        )
    print(f"\n  Full report: {REPORT_MD_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
