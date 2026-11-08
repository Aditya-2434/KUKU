"""
parser.py — Episode Script Parser
==================================
Reads each .txt episode file and returns a structured list of timed events
(CAMERA, ACTION, DIALOGUE) ready for the segment extractor.

Data model per event:
{
    "type":    "DIALOGUE" | "ACTION" | "CAMERA" | "SOUND_FX",
    "speaker": str | None,
    "emotion": str | None,
    "text":    str,
    "start":   float,   # seconds
    "end":     float,   # seconds
}
"""

import os
import re
from dataclasses import dataclass, asdict, field
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Event:
    type: str                    # DIALOGUE | ACTION | CAMERA | SOUND_FX
    speaker: Optional[str]       # e.g. "LADY JULIANA"
    emotion: Optional[str]       # e.g. "Heartbroken"
    text: str                    # dialogue line or action description
    start: float                 # seconds from episode start
    end: float                   # seconds from episode start


@dataclass
class Episode:
    episode_num: int
    logline: str
    continuity: str
    filename: str
    events: list = field(default_factory=list)   # list[Event]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _ts_to_seconds(ts: str) -> float:
    """Convert 'MM:SS.ss' or 'SS.ss' timestamp string to float seconds."""
    ts = ts.strip()
    if ":" in ts:
        parts = ts.split(":")
        minutes = float(parts[0])
        seconds = float(parts[1])
        return minutes * 60 + seconds
    return float(ts)


def _extract_timestamps(line: str):
    """
    Extract start and end seconds from a line like:
        'Start: (01:23.40) | End: (01:25.80)'
    Returns (start_sec, end_sec) or (None, None).
    """
    pattern = r"Start:\s*\(([^)]+)\)\s*\|\s*End:\s*\(([^)]+)\)"
    m = re.search(pattern, line)
    if m:
        return _ts_to_seconds(m.group(1)), _ts_to_seconds(m.group(2))
    return None, None


def _parse_header_line(line: str):
    """
    Parse a bold markdown header like:
        **LADY JULIANA (Heartbroken):**
        **ACTION:**
        **CAMERA:**
        **SOUND FX:**
    Returns (event_type, speaker, emotion).
    """
    # Strip surrounding ** and trailing :
    inner = re.sub(r"^\*\*|\*\*:?$|:$", "", line.strip()).strip("* ").strip(":")

    # Classify
    upper = inner.upper()
    if upper.startswith("ACTION"):
        return "ACTION", None, None
    if upper.startswith("CAMERA"):
        return "CAMERA", None, None
    if upper.startswith("SOUND"):
        return "SOUND_FX", None, None

    # Dialogue — parse speaker (emotion) pattern
    m = re.match(r"^(.+?)\s*\(([^)]+)\)(?:\s*\([^)]+\))?$", inner)
    if m:
        speaker_raw = m.group(1).strip()
        emotion = m.group(2).strip()
        # Remove off-screen tags
        speaker = re.sub(r"\s*\(O\.S\.\)\s*|\s*\(Off-screen\)\s*", "", speaker_raw,
                         flags=re.IGNORECASE).strip()
        return "DIALOGUE", speaker, emotion

    # Fallback — treat as dialogue with no emotion
    return "DIALOGUE", inner.strip(), None


# ──────────────────────────────────────────────────────────────────────────────
# Main parser
# ──────────────────────────────────────────────────────────────────────────────

def parse_episode(filepath: str) -> Episode:
    """Parse a single episode .txt file and return an Episode object."""
    with open(filepath, encoding="utf-8") as f:
        lines = f.readlines()

    # Extract metadata from first few lines
    episode_num = 0
    logline = ""
    continuity = ""
    for line in lines[:10]:
        if line.startswith("EPISODE NUMBER:"):
            raw = line.split(":", 1)[1].strip()
            nums = re.findall(r"\d+", raw)
            episode_num = int(nums[0]) if nums else 0
        elif line.startswith("EPISODE LOGLINE:"):
            logline = line.split(":", 1)[1].strip()
        elif line.startswith("CONTINUITY NOTES:"):
            continuity = line.split(":", 1)[1].strip()

    episode = Episode(
        episode_num=episode_num,
        logline=logline,
        continuity=continuity,
        filename=os.path.basename(filepath),
        events=[]
    )

    # Walk through the script body
    in_script = False
    current_type = None
    current_speaker = None
    current_emotion = None
    current_start = None
    current_end = None
    pending_text_lines = []

    def flush_event():
        """Commit the buffered event to the episode."""
        if current_type and current_start is not None:
            text = " ".join(pending_text_lines).strip().strip('"')
            if text:
                episode.events.append(Event(
                    type=current_type,
                    speaker=current_speaker,
                    emotion=current_emotion,
                    text=text,
                    start=current_start,
                    end=current_end or current_start,
                ))

    for raw_line in lines:
        line = raw_line.rstrip()

        if "--- SCRIPT START ---" in line:
            in_script = True
            continue
        if "--- SCRIPT END ---" in line:
            flush_event()
            break
        if not in_script:
            continue

        # Detect a bold header → new event block
        if line.strip().startswith("**") and line.strip().endswith("**:") or \
           (line.strip().startswith("**") and ":**" in line):
            flush_event()
            # Reset state
            current_type, current_speaker, current_emotion = _parse_header_line(line.strip())
            current_start = None
            current_end = None
            pending_text_lines = []
            continue

        # Detect timestamp line
        s, e = _extract_timestamps(line)
        if s is not None:
            # First timestamp in a block → that's our event's time range
            if current_start is None:
                current_start = s
                current_end = e
            continue

        # Collect text content (skip blank lines and scene headings)
        stripped = line.strip()
        if stripped and not stripped.startswith("SCENE") and \
           not stripped.startswith("Scene") and \
           not stripped.startswith("---"):
            pending_text_lines.append(stripped)

    # Sort by start time (usually already sorted, but just in case)
    episode.events.sort(key=lambda ev: ev.start)
    return episode


def parse_all_episodes(episodes_dir: str) -> list:
    """Parse all .txt episode files in the given directory."""
    files = sorted([
        os.path.join(episodes_dir, f)
        for f in os.listdir(episodes_dir)
        if f.endswith(".txt")
    ])
    episodes = []
    for filepath in files:
        try:
            ep = parse_episode(filepath)
            episodes.append(ep)
            print(f"  [OK] Parsed Episode {ep.episode_num:>3}  ({len(ep.events)} events)  [{ep.filename}]")
        except Exception as ex:
            print(f"  [FAIL] {filepath}: {ex}")
    return episodes


# ──────────────────────────────────────────────────────────────────────────────
# Quick sanity check
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json, pathlib, os
    base = pathlib.Path(__file__).parent
    episodes_dir = str(base / "I Married a Broken Soldier. He was a Duke")
    eps = parse_all_episodes(episodes_dir)
    print(f"\nParsed {len(eps)} episodes total.")
    # Print first 3 events of episode 1
    for ev in eps[0].events[:3]:
        print(json.dumps(asdict(ev), indent=2))
