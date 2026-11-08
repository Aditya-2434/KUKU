"""
quick_test.py -- API Spot-Check on 2 Episodes
===============================================
Demonstrates the full Gemini pipeline on Episodes 1 & 2 only.
Sends candidates ONE at a time with 15s sleep — ultra-conservative.
Shows real LLM scores vs our local heuristic scores side-by-side.
"""

import json, os, time, pathlib
from dotenv import load_dotenv
load_dotenv()

from parser       import parse_all_episodes
from extractor    import extract_single_episode_candidates
from local_scorer import score_candidates_local
from scorer       import _call_gemini, _composite, _build_batch_prompt, GEMINI_MODEL
from google       import genai
from google.genai import types

# Simple heuristic to pick the best candidates before sending to Gemini
def _heuristic_score(cand):
    d = cand["transcript"].count('":\n') + cand["transcript"].count('": "')
    cliff = cand["last_5s_text"].lower()
    cliff_b = sum(2 for w in ["?", "never", "not anymore", "regret",
                               "truth", "proof", "i know"] if w in cliff)
    return d + cliff_b

BASE_DIR     = pathlib.Path(__file__).parent
EPISODES_DIR = BASE_DIR / os.getenv("EPISODES_DIR", "I Married a Broken Soldier. He was a Duke")
SLEEP        = 15   # seconds between API calls (conservative)

def run():
    print("=" * 62)
    print("  KuKu Promo Finder — API Spot-Check (Episodes 1 & 2)")
    print("=" * 62)

    # -- Parse just eps 1 & 2 ------------------------------------------------
    print("\n[1] Parsing Episodes 1 and 2 ...")
    all_eps = parse_all_episodes(str(EPISODES_DIR))
    eps = [e for e in all_eps if e.episode_num in (1, 2)]

    # -- Extract + heuristic pre-filter to top 5 per ep ----------------------
    print("[2] Extracting candidates (top 5 per episode by heuristic) ...")
    selected = []
    for ep in eps:
        cands = extract_single_episode_candidates(ep)
        cands.sort(key=_heuristic_score, reverse=True)
        top5 = cands[:5]
        selected.extend(top5)
        print(f"    Ep {ep.episode_num}: {len(cands)} candidates -> keeping top 5")

    print(f"    Total to score via API: {len(selected)} candidates\n")

    # -- Local scores (baseline) ----------------------------------------------
    local_scored = score_candidates_local(selected, top_k_per_episode=99)
    local_map = {c["promo_id"]: c for c in local_scored}

    # -- Gemini scores (1 candidate per call) ----------------------------------
    print(f"[3] Calling Gemini ({GEMINI_MODEL}) — 1 candidate per call, {SLEEP}s sleep ...\n")
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    results = []
    for i, cand in enumerate(selected):
        print(f"  [{i+1}/{len(selected)}] {cand['promo_id']}  "
              f"(Ep {cand['episode_nums']}, {cand['total_duration']:.0f}s) ...", end=" ", flush=True)
        prompt  = _build_batch_prompt([cand])
        api_res = _call_gemini(client, prompt)

        if api_res:
            r = api_res[0]
            r["composite_score"] = _composite(r)
            gemini_composite = r["composite_score"]
            print(f"Gemini={gemini_composite:.2f}  "
                  f"[H={r.get('hook_strength',0)} C={r.get('cliffhanger_quality',0)} "
                  f"S={r.get('standalone_clarity',0)} E={r.get('emotional_intensity',0)}]")
            results.append({**cand, **r, "source": "gemini"})
        else:
            print("FAILED — using local score as fallback")
            local = local_map.get(cand["promo_id"], {})
            results.append({**cand, **local, "source": "local_fallback"})

        if i < len(selected) - 1:
            time.sleep(SLEEP)

    # -- Side-by-side comparison ----------------------------------------------
    print("\n" + "=" * 62)
    print("  COMPARISON: Local Heuristic vs Gemini API")
    print("=" * 62)
    print(f"  {'promo_id':<18} {'Local':>7} {'Gemini':>7}  {'Source'}")
    print(f"  {'-'*18} {'-'*7} {'-'*7}  {'-'*12}")
    for r in results:
        pid     = r["promo_id"]
        gemini  = r.get("composite_score", 0.0)
        local   = local_map.get(pid, {}).get("composite_score", 0.0)
        src     = r.get("source", "?")
        print(f"  {pid:<18} {local:>7.2f} {gemini:>7.2f}  {src}")

    # -- Print top result with full LLM analysis ------------------------------
    ranked = sorted(results, key=lambda x: x.get("composite_score", 0), reverse=True)
    best   = ranked[0]
    print("\n" + "=" * 62)
    print("  TOP PROMO FROM API RUN")
    print("=" * 62)
    ep  = best["episode_nums"]
    seg = best["segments"][0]
    print(f"  Episode    : {ep}")
    print(f"  Window     : {seg['start']:.1f}s -> {seg['end']:.1f}s  ({seg['duration']:.0f}s)")
    print(f"  Score      : {best.get('composite_score',0):.2f}/10")
    print(f"  Hook       : {best.get('hook_strength','?')}/10")
    print(f"  Cliffhanger: {best.get('cliffhanger_quality','?')}/10")
    print(f"  Standalone : {best.get('standalone_clarity','?')}/10")
    print(f"  Emotion    : {best.get('emotional_intensity','?')}/10")
    print(f"\n  Hook desc  : {best.get('hook_description','')}")
    print(f"  Cliff desc : {best.get('cliffhanger_desc','')}")
    print(f"  Why works  : {best.get('why_it_works','')}")
    print(f"\n  Transcript preview:")
    for line in best.get("transcript","").split("\n")[:6]:
        print(f"    {line}")

    # -- Save spot-check JSON -------------------------------------------------
    out_path = BASE_DIR / "outputs" / "api_spot_check.json"
    slim = [{k: v for k, v in r.items() if k not in ("segments","events")}
            for r in results]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(slim, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved -> {out_path}")
    print("=" * 62)

if __name__ == "__main__":
    run()
