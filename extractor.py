"""
extractor.py — Candidate Promo Segment Extractor
==================================================
Given a parsed Episode, finds all candidate promo segments in 20–60 second
windows.  Also attempts simple cross-episode stitching for multi-segment promos.

Each candidate looks like:
{
    "promo_id":      str,          # e.g. "ep01_t0000"
    "episode_nums":  list[int],
    "segments": [
        {
            "episode_num": int,
            "start":       float,  # seconds
            "end":         float,  # seconds
            "duration":    float,
            "events":      list[Event-dicts]
        }
    ],
    "total_duration": float,       # sum of segment durations
    "transcript":     str,         # human-readable text for LLM scoring
    "first_3s_text":  str,         # hook window
    "last_5s_text":   str,         # cliffhanger window
}
"""

from dataclasses import asdict
from parser import Episode, Event

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

MIN_DURATION = 20.0   # seconds
MAX_DURATION = 60.0   # seconds
STEP_SIZE    = 5.0    # sliding window step in seconds

# For multi-segment promos we allow a small gap between joined segments
MAX_JOIN_GAP  = 10.0  # seconds gap allowed between two segments

# How many events must be DIALOGUE (not just CAMERA) for a segment to be
# considered "content-rich" enough to send to the LLM
MIN_DIALOGUE_EVENTS = 1


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _events_in_window(events: list, win_start: float, win_end: float) -> list:
    """Return events whose START falls within [win_start, win_end).
    Events may be either Event dataclass instances or plain dicts (from asdict()).
    """
    def get_start(e):
        return e["start"] if isinstance(e, dict) else e.start
    return [e for e in events if win_start <= get_start(e) < win_end]


def _make_transcript(events: list) -> str:
    """Convert a list of Event dicts into a compact readable transcript string."""
    lines = []
    for ev in events:
        if ev["type"] == "DIALOGUE":
            speaker = ev["speaker"] or "UNKNOWN"
            emotion = f" ({ev['emotion']})" if ev["emotion"] else ""
            ts = f"[{ev['start']:.1f}s]"
            lines.append(f'{ts} {speaker}{emotion}: "{ev["text"]}"')
        elif ev["type"] == "ACTION":
            ts = f"[{ev['start']:.1f}s]"
            lines.append(f"{ts} ACTION: {ev['text']}")
        # CAMERA events add noise — skip unless very few events total
    return "\n".join(lines) if lines else "[No dialogue/action in this window]"


def _first_n_seconds_text(events: list, win_start: float, n: float = 3.0) -> str:
    hook_events = [e for e in events if e["start"] < win_start + n]
    return _make_transcript(hook_events) if hook_events else "(no events in first 3s)"


def _last_n_seconds_text(events: list, win_end: float, n: float = 5.0) -> str:
    cliff_events = [e for e in events if e["start"] >= win_end - n]
    return _make_transcript(cliff_events) if cliff_events else "(no events in last 5s)"


# ──────────────────────────────────────────────────────────────────────────────
# Single-episode sliding window
# ──────────────────────────────────────────────────────────────────────────────

def extract_single_episode_candidates(episode: Episode) -> list:
    """
    Slide a window of increasing size across the episode timeline and collect
    all segments between MIN_DURATION and MAX_DURATION seconds that contain
    at least MIN_DIALOGUE_EVENTS dialogue events.
    """
    if not episode.events:
        return []

    all_events_dict = [asdict(ev) for ev in episode.events]
    ep_start = episode.events[0].start
    ep_end   = episode.events[-1].end

    candidates = []
    seen_windows = set()

    win_start = ep_start
    while win_start < ep_end - MIN_DURATION:
        for win_duration in range(int(MIN_DURATION), int(MAX_DURATION) + 1, 5):
            win_end = win_start + win_duration
            if win_end > ep_end + 5:   # slight overshoot allowed
                break

            key = (round(win_start, 1), round(win_end, 1))
            if key in seen_windows:
                continue
            seen_windows.add(key)

            window_events = _events_in_window(all_events_dict, win_start, win_end)

            # Must have at least one dialogue event
            dialogue_count = sum(1 for e in window_events if e["type"] == "DIALOGUE")
            if dialogue_count < MIN_DIALOGUE_EVENTS:
                continue

            transcript = _make_transcript(window_events)
            first3  = _first_n_seconds_text(window_events, win_start)
            last5   = _last_n_seconds_text(window_events, win_end)

            promo_id = f"ep{episode.episode_num:02d}_t{int(win_start):04d}"
            candidates.append({
                "promo_id": promo_id,
                "episode_nums": [episode.episode_num],
                "segments": [{
                    "episode_num": episode.episode_num,
                    "start":    win_start,
                    "end":      win_end,
                    "duration": win_duration,
                    "events":   window_events,
                }],
                "total_duration": float(win_duration),
                "transcript":    transcript,
                "first_3s_text": first3,
                "last_5s_text":  last5,
                "logline":       episode.logline,
                "ep_continuity": episode.continuity,
            })

        win_start += STEP_SIZE

    return candidates


# ──────────────────────────────────────────────────────────────────────────────
# Cross-episode multi-segment promos (optional v1 feature)
# ──────────────────────────────────────────────────────────────────────────────

def extract_cross_episode_candidates(ep_a: Episode, ep_b: Episode) -> list:
    """
    Join the TAIL of episode A with the HEAD of episode B when the episodes
    are consecutive and their combined duration stays within 20–60 seconds.
    This covers the common microdrama pattern of ending one episode on a hook
    and opening the next with the payoff.
    """
    if ep_b.episode_num != ep_a.episode_num + 1:
        return []
    if not ep_a.events or not ep_b.events:
        return []

    candidates = []
    tail_durations = [5, 10, 15, 20, 25, 30]
    head_durations = [5, 10, 15, 20, 25, 30]

    ep_a_end   = ep_a.events[-1].end
    ep_b_start = ep_b.events[0].start

    for tail_dur in tail_durations:
        for head_dur in head_durations:
            total = tail_dur + head_dur
            if not (MIN_DURATION <= total <= MAX_DURATION):
                continue

            tail_start = ep_a_end - tail_dur
            head_end   = ep_b_start + head_dur

            tail_events = _events_in_window([asdict(e) for e in ep_a.events],
                                             tail_start, ep_a_end + 1)
            head_events = _events_in_window([asdict(e) for e in ep_b.events],
                                             ep_b_start, head_end)

            if not tail_events and not head_events:
                continue

            tail_diag = sum(1 for e in tail_events if e["type"] == "DIALOGUE")
            head_diag = sum(1 for e in head_events if e["type"] == "DIALOGUE")
            if tail_diag + head_diag < MIN_DIALOGUE_EVENTS:
                continue

            # Adjust head event timestamps to be relative (for display)
            transcript = (
                f"[EP {ep_a.episode_num} — final {tail_dur}s]\n"
                + _make_transcript(tail_events)
                + f"\n\n[EP {ep_b.episode_num} — first {head_dur}s]\n"
                + _make_transcript(head_events)
            )

            promo_id = f"ep{ep_a.episode_num:02d}x{ep_b.episode_num:02d}_t{int(tail_dur):02d}h{int(head_dur):02d}"
            candidates.append({
                "promo_id": promo_id,
                "episode_nums": [ep_a.episode_num, ep_b.episode_num],
                "segments": [
                    {
                        "episode_num": ep_a.episode_num,
                        "start": tail_start,
                        "end":   ep_a_end,
                        "duration": tail_dur,
                        "events": tail_events,
                    },
                    {
                        "episode_num": ep_b.episode_num,
                        "start": ep_b_start,
                        "end":   head_end,
                        "duration": head_dur,
                        "events": head_events,
                    },
                ],
                "total_duration": float(total),
                "transcript":    transcript,
                "first_3s_text": _first_n_seconds_text(tail_events, tail_start),
                "last_5s_text":  _last_n_seconds_text(head_events, head_end),
                "logline":       ep_a.logline,
                "ep_continuity": ep_b.continuity,
            })

    return candidates


# ──────────────────────────────────────────────────────────────────────────────
# Full extraction across all episodes
# ──────────────────────────────────────────────────────────────────────────────

def extract_all_candidates(episodes: list) -> list:
    """
    Run extraction on all episodes (single + cross-episode) and return
    the flat list of all candidate promos.
    """
    all_candidates = []
    for ep in episodes:
        cands = extract_single_episode_candidates(ep)
        all_candidates.extend(cands)
        print(f"  Ep {ep.episode_num:>3}: {len(cands):>4} single-episode candidates")

    # Cross-episode pairs
    cross_count = 0
    for i in range(len(episodes) - 1):
        cross = extract_cross_episode_candidates(episodes[i], episodes[i + 1])
        all_candidates.extend(cross)
        cross_count += len(cross)
    print(f"  Cross-episode candidates: {cross_count}")
    print(f"  Total candidates: {len(all_candidates)}")
    return all_candidates


if __name__ == "__main__":
    import pathlib
    from parser import parse_all_episodes
    base = pathlib.Path(__file__).parent
    eps = parse_all_episodes(str(base / "I Married a Broken Soldier. He was a Duke"))
    cands = extract_all_candidates(eps)
    print(f"\nSample candidate:\n")
    import json
    sample = {k: v for k, v in cands[0].items() if k != "segments"}
    print(json.dumps(sample, indent=2))
