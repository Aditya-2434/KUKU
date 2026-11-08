"""
scorer.py — LLM-based Promo Scorer using Google Gemini (google-genai SDK)
===========================================================================
Takes a list of candidate promo dicts (from extractor.py) and scores each one
using Gemini 3.5 Flash. Processes candidates in small batches with delays to
stay within free-tier rate limits.

Scoring rubric (returned as JSON by the LLM):
  hook_strength         0-10  (how grabbing is the first 3 seconds?)
  cliffhanger_quality   0-10  (how unresolved / need-to-know is the ending?)
  standalone_clarity    0-10  (can a new viewer understand without context?)
  emotional_intensity   0-10  (how emotionally charged is the moment?)
  hook_description      str   (1 sentence)
  cliffhanger_desc      str   (1 sentence)
  why_it_works          str   (1 line)
  composite_score       float (computed locally, not by LLM)
"""

import json
import os
import time
import re
from google import genai
from google.genai import types
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# Scoring weights (must sum to 1.0)
WEIGHTS = {
    "hook_strength":       0.35,
    "cliffhanger_quality": 0.35,
    "standalone_clarity":  0.20,
    "emotional_intensity": 0.10,
}

# Rate limiting — gemini-3.5-flash free tier: ~15 requests/minute
# With 1 req per batch and 60s sleep, we stay at 1 req/min — zero risk of 429.
# Total time: ~495 batches * 60s = ~8 hrs at 15/batch, so we cut candidates hard.
BATCH_SIZE           = 5     # 5 clips per call (reduce total call count)
SLEEP_BETWEEN_CALLS  = 60.0  # 60 seconds between calls = safe 1 req/min

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert social-media video editor for a microdrama streaming platform.
Your job is to evaluate short clips extracted from romance drama screenplays and score how good
they would be as 20-60 second promotional clips posted on Instagram, TikTok, or YouTube.

A great promo:
1. Opens on a HOOK - something in the first 3 seconds that makes a scrolling viewer stop
   (a slap, shocking reveal, betrayal, a killer line of dialogue).
2. Ends on a CLIFFHANGER - cuts at an unresolved moment, so the viewer needs to know what happens.
3. Makes sense STANDALONE - someone who has never seen the show understands what is at stake.

You will receive a JSON array of candidate clips. For EACH clip, return scores and analysis
as a JSON array with the SAME order and count. Return ONLY valid JSON array, no markdown, no extra text."""

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_batch_prompt(batch: list) -> str:
    items = []
    for cand in batch:
        items.append({
            "promo_id":        cand["promo_id"],
            "duration_s":      cand["total_duration"],
            "first_3s":        cand["first_3s_text"],
            "last_5s":         cand["last_5s_text"],
            "full_transcript": cand["transcript"],
            "show_logline":    cand.get("logline", ""),
        })

    schema = {
        "promo_id":            "string — same promo_id as input",
        "hook_strength":       "integer 0-10",
        "cliffhanger_quality": "integer 0-10",
        "standalone_clarity":  "integer 0-10",
        "emotional_intensity": "integer 0-10",
        "hook_description":    "one sentence describing what the hook is",
        "cliffhanger_desc":    "one sentence describing the unresolved ending",
        "why_it_works":        "one line on why this would stop a scrolling viewer",
    }

    return (
        f"Evaluate these {len(batch)} promo candidates. "
        f"Return a JSON array of exactly {len(batch)} objects each matching:\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        f"Candidates:\n{json.dumps(items, indent=2)}"
    )

# ---------------------------------------------------------------------------
# Single Gemini call
# ---------------------------------------------------------------------------

def _call_gemini(client: genai.Client, prompt: str, retries: int = 4) -> list:
    """Call Gemini and parse the JSON array response.
    Retries on 503 (transient demand) and 429 (quota) with backoff.
    On 429 we wait 65s (just over the 1-minute quota window).
    """
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )
            raw = response.text.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            return json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"\n    [WARN] JSON parse error (attempt {attempt+1}): {e}")
            return []
        except Exception as e:
            err_str = str(e)
            is_quota   = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
            is_unavail = "503" in err_str or "UNAVAILABLE" in err_str
            if (is_quota or is_unavail) and attempt < retries - 1:
                # 429 → wait 65s to clear the per-minute quota window
                # 503 → wait 20s * (attempt+1)
                wait = 65 if is_quota else 20 * (attempt + 1)
                label = "429 quota" if is_quota else "503 unavail"
                print(f"\n    [RETRY {attempt+1}] {label} — waiting {wait}s ...", end="", flush=True)
                time.sleep(wait)
                print(" retrying.")
            else:
                print(f"\n    [WARN] Gemini error after {attempt+1} attempts: {err_str[:100]}")
                return []
    return []

# ---------------------------------------------------------------------------
# Composite score
# ---------------------------------------------------------------------------

def _composite(scores: dict) -> float:
    return round(sum(scores.get(k, 0) * w for k, w in WEIGHTS.items()), 3)

# ---------------------------------------------------------------------------
# Heuristic pre-filter
# ---------------------------------------------------------------------------

def _heuristic_score(cand: dict) -> float:
    """
    Quick score without LLM:
    - Count dialogue lines (high-value events)
    - Bonus for ending on a question or strong word
    - Duration ratio (prefer mid-length clips — not too short, not padded)
    """
    transcript = cand["transcript"]
    dialogue_lines = transcript.count('":\n') + transcript.count('": "')
    
    # Bonus: last 5s has a punchy ending keyword
    cliff_text = cand["last_5s_text"].lower()
    cliff_bonus = sum(2 for w in ["never", "you", "can't", "won't", "lies", "lied",
                                   "him", "her", "dead", "gone", "wrong", "?", "!",
                                   "how dare", "not anymore", "i know"] if w in cliff_text)

    # Hook: first 3s has strong opener
    hook_text = cand["first_3s_text"].lower()
    hook_bonus = sum(2 for w in ["how dare", "you dare", "slap", "gasp", "shock",
                                  "betrayal", "abandon", "left", "alone", "never",
                                  "not anymore"] if w in hook_text)

    duration_ratio = min(cand["total_duration"] / 60.0, 1.0)
    return dialogue_lines * (1 + duration_ratio) + cliff_bonus + hook_bonus

# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def score_candidates(candidates: list, top_k_per_episode: int = 15) -> list:
    """
    Score all candidates using Gemini 3.5 Flash.

    1. Pre-filter: keep top_k_per_episode per episode via heuristic.
    2. Batch BATCH_SIZE candidates per Gemini call.
    3. Sleep between calls to respect free-tier rate limits.
    4. Return enriched candidate dicts with LLM scores.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        raise ValueError(
            "GEMINI_API_KEY not set. Please paste your key in the .env file."
        )

    client = genai.Client(api_key=GEMINI_API_KEY)

    # -- Pre-filter --------------------------------------------------------
    from collections import defaultdict
    by_episode = defaultdict(list)
    for cand in candidates:
        ep_key = tuple(cand["episode_nums"])
        by_episode[ep_key].append(cand)

    filtered = []
    for ep_key, ep_cands in sorted(by_episode.items()):
        ep_cands.sort(key=_heuristic_score, reverse=True)
        filtered.extend(ep_cands[:top_k_per_episode])

    print(f"\n  Pre-filter: {len(candidates)} -> {len(filtered)} candidates for LLM scoring")
    print(f"  Model: {GEMINI_MODEL}  |  Batch size: {BATCH_SIZE}  |  Delay: {SLEEP_BETWEEN_CALLS}s\n")

    # -- Batch LLM calls ---------------------------------------------------
    scored_map = {}
    batches = [filtered[i:i + BATCH_SIZE] for i in range(0, len(filtered), BATCH_SIZE)]
    total_batches = len(batches)

    for idx, batch in enumerate(batches):
        print(f"  Batch {idx + 1:>3}/{total_batches}  ({len(batch)} clips) ... ", end="", flush=True)
        prompt = _build_batch_prompt(batch)
        results = _call_gemini(client, prompt)

        ok_count = 0
        for res in results:
            pid = res.get("promo_id")
            if pid:
                res["composite_score"] = _composite(res)
                scored_map[pid] = res
                ok_count += 1

        print(f"[{ok_count}/{len(batch)} scored]")

        if idx < total_batches - 1:
            time.sleep(SLEEP_BETWEEN_CALLS)

    # -- Merge scores back into candidates ---------------------------------
    scored_candidates = []
    for cand in filtered:
        pid = cand["promo_id"]
        if pid in scored_map:
            enriched = {**cand, **scored_map[pid]}
        else:
            # LLM missed this — assign zeroes so it appears in quality report
            enriched = {
                **cand,
                "composite_score":    0.0,
                "hook_strength":      0,
                "cliffhanger_quality": 0,
                "standalone_clarity": 0,
                "emotional_intensity": 0,
                "hook_description":   "N/A (scoring failed)",
                "cliffhanger_desc":   "N/A",
                "why_it_works":       "N/A",
            }
        scored_candidates.append(enriched)

    scored_ok = sum(1 for c in scored_candidates if c["composite_score"] > 0)
    print(f"\n  LLM scoring complete: {scored_ok}/{len(scored_candidates)} candidates scored successfully.")
    return scored_candidates


if __name__ == "__main__":
    print("scorer.py -- run main.py to execute the full pipeline.")
