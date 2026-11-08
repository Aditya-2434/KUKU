"""
local_scorer.py -- Rule-based Promo Scorer (zero API, zero cost)
=================================================================
Scores each candidate promo segment using deterministic text-analysis rules
applied directly to the screenplay transcript. No LLM, no internet required.

Scoring dimensions (each 0-10):
  hook_strength        -- power of the first 3 seconds
  cliffhanger_quality  -- how unresolved the ending feels
  standalone_clarity   -- can a stranger follow it?
  emotional_intensity  -- how charged is the content?

Descriptions are extracted from the actual transcript text, so there is
zero hallucination risk -- every word in the output came from the script.
"""

import re
from collections import Counter

# ---------------------------------------------------------------------------
# Word/phrase banks (derived from studying the scripts + social media promo
# best-practices for romance microdramas)
# ---------------------------------------------------------------------------

HOOK_POWER_PHRASES = [
    "how dare", "not anymore", "i knew", "you knew", "you lied",
    "you swore", "how could you", "i trusted you", "how long",
    "you let me", "you planned", "it was you", "i know the truth",
    "she is mine", "he is mine", "get out", "you will never",
    "i am leaving", "it is over", "you are nothing", "look at me",
    "turn around", "stop", "enough", "no more", "you dare",
    "i forbid", "how long have you", "she told me everything",
    "i saw you", "i heard you", "i found out",
]

CLIFFHANGER_PHRASES = [
    "you will regret", "wait and see", "i know what you did",
    "i have proof", "i will expose", "you don't know me",
    "this is not over", "we are not done", "i am not done",
    "i will not let", "you haven't heard the last", "mark my words",
    "you will pay", "just you wait", "i dare you", "try me",
    "then you don't know", "i will tell", "i have something",
    "there is something you should know", "i need to tell you",
    "i have to tell you something", "before you go",
    "wait -- there is", "that is not all",
]

HOOK_EMOTION_TAGS = {
    "outraged", "furious", "devastated", "betrayed", "shocked",
    "piercing", "accusing", "bitter", "defiant", "stunned",
    "incredulous", "horrified", "gasping", "heartbroken",
    "commanding", "cold, callous", "cold", "steely",
}

CLIFF_EMOTION_TAGS = {
    "threatening", "ominous", "defiant", "resolute", "cold",
    "piercing", "accusing", "steely", "commanding", "icy",
    "firm", "unyielding", "mysterious", "dangerous", "warning",
}

HIGH_EMOTION_TAGS = {
    "heartbroken", "devastated", "outraged", "betrayed", "crushed",
    "shattered", "furious", "sobbing", "trembling", "desperate",
    "anguished", "broken", "weeping", "gasping", "horrified",
    "bitter", "cold", "piercing", "steely", "defiant",
    "accusing", "commanding", "stunned", "incredulous",
}

PHYSICAL_TENSION_WORDS = [
    "slap", "slam", "grab", "shove", "throw", "storm", "burst",
    "tears", "cry", "weep", "sob", "tremble", "shake", "gasp",
    "clutch", "clench", "kneel", "collapse", "flinch", "recoil",
    "freeze", "stiffen", "back away", "step back", "spin around",
]

STANDALONE_SCENE_WORDS = [
    "cathedral", "church", "wedding", "throne room", "palace",
    "bedroom", "hallway", "garden", "courtroom", "study",
    "ballroom", "manor", "library", "corridor", "estate",
    "dining room", "carriage", "doorway", "altar",
]

# ---------------------------------------------------------------------------
# Individual dimension scorers
# ---------------------------------------------------------------------------

def _score_hook(cand: dict) -> tuple:
    """
    Score the hook strength (0-10) and return (score, description).
    Looks at: first_3s_text, hook phrases, opening emotion tags,
    physical tension in opening ACTION.
    """
    text = cand["first_3s_text"].lower()
    full = cand["transcript"]
    score = 0

    # 1. Power phrases in opening
    phrase_hits = sum(1 for p in HOOK_POWER_PHRASES if p in text)
    score += min(phrase_hits * 2, 4)

    # 2. Strong emotion tag on first dialogue
    first_emotion = _extract_first_emotion(full)
    if first_emotion and first_emotion.lower() in HOOK_EMOTION_TAGS:
        score += 3

    # 3. Physical tension / action in opening
    tension_hits = sum(1 for w in PHYSICAL_TENSION_WORDS if w in text)
    score += min(tension_hits, 2)

    # 4. Dialogue exists in first 3s (silent opener = weak hook)
    if '"' in cand["first_3s_text"]:
        score += 1

    score = min(score, 10)

    # Build description from actual first dialogue line
    first_line = _extract_first_dialogue(full)
    if first_line:
        desc = f'Opens on: "{first_line[:100]}"'
    elif "ACTION:" in cand["first_3s_text"]:
        action = cand["first_3s_text"].split("ACTION:")[-1].strip()[:100]
        desc = f"Opens on physical action: {action}"
    else:
        desc = "Opens on scene-setting moment."

    return score, desc


def _score_cliffhanger(cand: dict) -> tuple:
    """
    Score the cliffhanger quality (0-10) and return (score, description).
    Looks at: last_5s_text, unresolved lines, cliffhanger phrases,
    ending on a question, strong closing emotion tag.
    """
    last_text = cand["last_5s_text"].lower()
    score = 0

    # 1. Ends on a question mark
    if "?" in last_text:
        score += 3

    # 2. Cliffhanger phrases
    phrase_hits = sum(1 for p in CLIFFHANGER_PHRASES if p in last_text)
    score += min(phrase_hits * 2, 4)

    # 3. Strong closing emotion tag
    last_emotion = _extract_last_emotion(cand["transcript"])
    if last_emotion and last_emotion.lower() in CLIFF_EMOTION_TAGS:
        score += 2

    # 4. Ends mid-confrontation (dialogue ends, no resolution word)
    resolution_words = ["goodbye", "thank you", "good night", "understood",
                        "agreed", "settled", "forgive", "i see", "very well"]
    if not any(w in last_text for w in resolution_words):
        score += 1

    score = min(score, 10)

    # Build description from actual last dialogue line
    last_line = _extract_last_dialogue(cand["transcript"])
    if last_line:
        desc = f'Cuts on: "{last_line[:100]}"'
    else:
        desc = "Ends at an unresolved confrontation moment."

    return score, desc


def _score_standalone(cand: dict) -> tuple:
    """
    Score standalone clarity (0-10) and return (score, description).
    Checks: named characters, scene description, self-contained context.
    """
    transcript = cand["transcript"]
    text_lower = transcript.lower()
    score = 0

    # 1. Physical scene is established (from ACTION lines)
    if any(w in text_lower for w in STANDALONE_SCENE_WORDS):
        score += 2

    # 2. Character names appear (not just pronouns)
    # Count capitalised proper-noun-looking words in dialogue lines
    dialogue_lines = [l for l in transcript.split("\n") if '": "' in l or '"):' in l]
    named_speakers = set()
    for line in transcript.split("\n"):
        m = re.match(r"\[[\d.]+s\] ([A-Z][A-Z\s]+?)(?:\s*\([^)]+\))?\s*:", line)
        if m:
            speaker = m.group(1).strip()
            if len(speaker) > 2 and speaker not in ("ACTION", "CAMERA", "SOUND"):
                named_speakers.add(speaker)
    score += min(len(named_speakers), 3)

    # 3. Has at least 2 dialogue exchanges (back-and-forth)
    dialogue_count = transcript.count('":\n') + transcript.count('": "') + transcript.count('":\r\n')
    if dialogue_count >= 3:
        score += 2
    elif dialogue_count >= 1:
        score += 1

    # 4. Logline provides context (bonus if show logline is rich)
    if len(cand.get("logline", "")) > 50:
        score += 1

    # 5. No confusing pronouns without antecedent in first line
    first_line = _extract_first_dialogue(transcript)
    if first_line:
        starts_with_pronoun = re.match(r"^(she|he|they|it|this|that)\b", first_line.lower())
        if not starts_with_pronoun:
            score += 1

    score = min(score, 10)
    return score, f"{len(named_speakers)} named character(s), {dialogue_count} dialogue exchange(s)"


def _score_emotion(cand: dict) -> tuple:
    """
    Score emotional intensity (0-10) and return (score, description).
    Uses emotion tags already embedded in the screenplay format.
    """
    transcript = cand["transcript"]
    text_lower = transcript.lower()

    # Count high-emotion tags present
    emotion_hits = sum(1 for tag in HIGH_EMOTION_TAGS if tag in text_lower)
    score = min(emotion_hits * 2, 6)

    # Physical tension words in full transcript
    tension_hits = sum(1 for w in PHYSICAL_TENSION_WORDS if w in text_lower)
    score += min(tension_hits, 2)

    # Exclamation marks (heightened delivery)
    excl = transcript.count("!")
    score += min(excl, 2)

    score = min(score, 10)

    # Find the strongest emotion tag for description
    found_tags = [tag for tag in HIGH_EMOTION_TAGS if tag in text_lower]
    if found_tags:
        top_tag = found_tags[0].title()
        desc = f"Peak emotion: {top_tag}"
    else:
        desc = "Moderate emotional tone."

    return score, desc


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _extract_first_dialogue(transcript: str) -> str:
    """Return the text of the first dialogue line in the transcript."""
    for line in transcript.split("\n"):
        m = re.search(r':\s*"(.+)"', line)
        if m:
            return m.group(1).strip()
    return ""


def _extract_last_dialogue(transcript: str) -> str:
    """Return the text of the last dialogue line in the transcript."""
    last = ""
    for line in transcript.split("\n"):
        m = re.search(r':\s*"(.+)"', line)
        if m:
            last = m.group(1).strip()
    return last


def _extract_first_emotion(transcript: str) -> str:
    """Extract the emotion tag from the first dialogue event."""
    for line in transcript.split("\n"):
        m = re.search(r"\(([^)]+)\):", line)
        if m:
            return m.group(1).strip()
    return ""


def _extract_last_emotion(transcript: str) -> str:
    """Extract the emotion tag from the last dialogue event."""
    last = ""
    for line in transcript.split("\n"):
        m = re.search(r"\(([^)]+)\):", line)
        if m:
            last = m.group(1).strip()
    return last


# ---------------------------------------------------------------------------
# Composite scorer
# ---------------------------------------------------------------------------

WEIGHTS = {
    "hook_strength":       0.35,
    "cliffhanger_quality": 0.35,
    "standalone_clarity":  0.20,
    "emotional_intensity": 0.10,
}


def _composite(scores: dict) -> float:
    return round(sum(scores.get(k, 0) * w for k, w in WEIGHTS.items()), 3)


def _why_it_works(h_score, c_score, s_score, e_score,
                  h_desc, c_desc) -> str:
    """Generate a one-line 'why it works' from the top dimension."""
    best = max(
        ("hook",        h_score, h_desc),
        ("cliffhanger", c_score, c_desc),
        key=lambda x: x[1]
    )
    if best[0] == "hook":
        return f"Strong opening hook ({h_score}/10): {h_desc[:80]}"
    else:
        return f"Sharp cliffhanger ({c_score}/10): {c_desc[:80]}"


# ---------------------------------------------------------------------------
# Public API  (mirrors scorer.py interface so main.py can call either)
# ---------------------------------------------------------------------------

def score_candidates_local(candidates: list, top_k_per_episode: int = 10) -> list:
    """
    Score all candidates locally using rule-based text analysis.

    1. Pre-filter: top_k_per_episode using dialogue-density heuristic.
    2. Apply all 4 dimension scorers.
    3. Return enriched candidate dicts — same schema as scorer.py output.
    """
    from collections import defaultdict

    # Reuse the same heuristic from scorer.py for pre-filter
    def heuristic(c):
        d = c["transcript"].count('":\n') + c["transcript"].count('": "')
        cliff = c["last_5s_text"].lower()
        cliff_b = sum(2 for w in ["?", "never", "not anymore", "regret",
                                   "truth", "proof", "i know"] if w in cliff)
        return d + cliff_b

    by_ep = defaultdict(list)
    for cand in candidates:
        ep_key = tuple(cand["episode_nums"])
        by_ep[ep_key].append(cand)

    filtered = []
    for ep_key, ep_cands in sorted(by_ep.items()):
        ep_cands.sort(key=heuristic, reverse=True)
        filtered.extend(ep_cands[:top_k_per_episode])

    print(f"  Local scorer: {len(candidates)} -> {len(filtered)} candidates")

    scored = []
    for i, cand in enumerate(filtered):
        h_score, h_desc = _score_hook(cand)
        c_score, c_desc = _score_cliffhanger(cand)
        s_score, s_desc = _score_standalone(cand)
        e_score, e_desc = _score_emotion(cand)

        composite = _composite({
            "hook_strength":       h_score,
            "cliffhanger_quality": c_score,
            "standalone_clarity":  s_score,
            "emotional_intensity": e_score,
        })

        enriched = {
            **cand,
            "hook_strength":       h_score,
            "cliffhanger_quality": c_score,
            "standalone_clarity":  s_score,
            "emotional_intensity": e_score,
            "hook_description":    h_desc,
            "cliffhanger_desc":    c_desc,
            "why_it_works":        _why_it_works(h_score, c_score, s_score,
                                                  e_score, h_desc, c_desc),
            "composite_score":     composite,
            "scorer":              "local_heuristic",
        }
        scored.append(enriched)

        if (i + 1) % 100 == 0:
            print(f"    Scored {i+1}/{len(filtered)}...")

    print(f"  Done. {len(scored)} candidates scored (no API calls).")
    return scored
