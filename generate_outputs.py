"""
generate_outputs.py -- Offline Output Generator
================================================
Runs the full promo-finding pipeline WITHOUT any API calls.
Uses local_scorer.py (rule-based text analysis) instead of Gemini.

Produces the same 3 output files required for submission:
  outputs/promos_raw.json
  outputs/promos_report.md
  outputs/quality_report.md

Runtime: ~30 seconds on any machine. Zero cost. Zero internet needed.

NOTE: The full Gemini-powered pipeline is in main.py -- identical pipeline,
just swap local_scorer -> scorer.py. Run main.py with a valid API key to get
LLM-enhanced descriptions and scores.
"""

import json
import os
import pathlib
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

BASE_DIR     = pathlib.Path(__file__).parent
EPISODES_DIR = BASE_DIR / os.getenv("EPISODES_DIR", "I Married a Broken Soldier. He was a Duke")
OUTPUT_DIR   = BASE_DIR / os.getenv("OUTPUT_DIR", "outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

RAW_JSON_PATH   = OUTPUT_DIR / "promos_raw.json"
REPORT_MD_PATH  = OUTPUT_DIR / "promos_report.md"
QUALITY_MD_PATH = OUTPUT_DIR / "quality_report.md"

from parser       import parse_all_episodes
from extractor    import extract_all_candidates
from local_scorer import score_candidates_local

# Reuse report generators from main.py
from main import deduplicate, generate_report, generate_quality_report, _fmt_time


def main():
    print("=" * 60)
    print("  KuKu Promo Finder -- Offline / Local Scorer")
    print("  (No API calls -- rule-based text analysis)")
    print("=" * 60)

    # -- Step 1: Parse --------------------------------------------------------
    print("\n[1/4] Parsing episode scripts...")
    episodes = parse_all_episodes(str(EPISODES_DIR))
    print(f"  -> {len(episodes)} episodes parsed.\n")

    # -- Step 2: Extract ------------------------------------------------------
    print("[2/4] Extracting candidate promo segments...")
    candidates = extract_all_candidates(episodes)
    print(f"  -> {len(candidates)} total candidates.\n")

    # -- Step 3: Local scoring ------------------------------------------------
    print("[3/4] Scoring candidates (local rules, no API)...")
    # top_k=10 -> 10 best per episode group -> ~990 candidates scored locally
    # This is fast and free, so we keep more than the LLM version
    scored = score_candidates_local(candidates, top_k_per_episode=10)
    print()

    # -- Step 4: Rank, dedup, save --------------------------------------------
    print("[4/4] Ranking and saving outputs...")
    deduped = deduplicate(scored)
    ranked  = sorted(deduped, key=lambda c: c["composite_score"], reverse=True)

    # Slim for JSON (drop heavy events lists)
    def slim(c):
        out = {k: v for k, v in c.items() if k != "segments"}
        out["segments"] = [
            {kk: vv for kk, vv in s.items() if kk != "events"}
            for s in c.get("segments", [])
        ]
        return out

    with open(RAW_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump([slim(c) for c in ranked], f, indent=2, ensure_ascii=False)
    print(f"  [saved] {RAW_JSON_PATH}")

    report_md = generate_report(ranked, top_n=20)
    with open(REPORT_MD_PATH, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"  [saved] {REPORT_MD_PATH}")

    quality_md = generate_quality_report(scored, ranked)
    with open(QUALITY_MD_PATH, "w", encoding="utf-8") as f:
        f.write(quality_md)
    print(f"  [saved] {QUALITY_MD_PATH}")

    # -- Console top 5 --------------------------------------------------------
    print("\n" + "=" * 60)
    print("  TOP 5 PROMOS  (local heuristic scorer)")
    print("=" * 60)
    for rank, cand in enumerate(ranked[:5], 1):
        ep  = cand["episode_nums"]
        seg = cand["segments"][0]
        print(
            f"  #{rank}  Ep{ep}  "
            f"{_fmt_time(seg['start'])} -> {_fmt_time(seg['end'])}  "
            f"Score={cand['composite_score']:.2f}  "
            f"Hook={cand['hook_strength']}  Cliff={cand['cliffhanger_quality']}"
        )
        print(f"      {cand.get('why_it_works','')[:70]}")
    print()
    print(f"  Full report  -> {REPORT_MD_PATH}")
    print(f"  Raw JSON     -> {RAW_JSON_PATH}")
    print(f"  Quality      -> {QUALITY_MD_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
