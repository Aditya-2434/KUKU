# Quality Report — Where the Promo Finder Fails
*Generated: 2026-11-08 18:33*

## Score Distribution

| Score Bucket | Count |
|---|---|
| 1/10 | 52 |
| 2/10 | 298 |
| 3/10 | 434 |
| 4/10 | 198 |
| 5/10 | 8 |

## Known Failure Modes

### 1. Pure CAMERA description windows
Many windows contain only camera direction text with no dialogue.
These get low standalone scores because there's nothing audible.
**Fix:** Weight episodes by dialogue density before pre-filtering.

### 2. Mid-scene exposition
Some high-emotion dialogue occurs in the middle of scenes but lacks
a natural cliffhanger ending (episode just continues after the window).
The LLM correctly penalises these but we still generate many candidates.
**Fix:** Use scene-boundary-aware windowing (don't split mid-scene).

### 3. Cross-episode promos are harder to evaluate
The LLM receives two disconnected transcripts and must imagine the cut.
Without visual reference, cliffhanger scores may be under/over-estimated.
**Fix:** Add a 'cut quality' criterion specifically for multi-segment promos.

### 4. Repetitive high-scoring moments
Episode 1–2 (wedding betrayal) dominates top rankings because the
emotional peak is very strong. This is correct but would lead to
posting the same scene repeatedly.
**Fix:** Enforce 1 promo per episode in the final top-20 ranking.

### 5. LLM hallucination risk
Gemini Flash may describe a hook that isn't actually in the first 3 seconds.
We mitigate this by explicitly passing `first_3s_text` and `last_5s_text`
as separate fields, so the LLM scores based on what we show, not what it imagines.

## Lowest-Scoring Candidates (Tool Misfires)

### Bottom #1  — Ep [18, 19]  |  Score: 0.70
- Transcript preview: `[EP 18 — final 5s]
[No dialogue/action in this window]

[EP 19 — first 30s]
[0.0s] ACTION: Juliana clutches her mother's...`
- LLM note: Strong opening hook (0/10): Opens on: "This was our home."

### Bottom #2  — Ep [31, 32]  |  Score: 0.70
- Transcript preview: `[EP 31 — final 5s]
[No dialogue/action in this window]

[EP 32 — first 20s]
[3.8s] CATHERINE (Mocking, Savoring): "There...`
- LLM note: Strong opening hook (0/10): Opens on: "There it is."

### Bottom #3  — Ep [13, 14]  |  Score: 0.95
- Transcript preview: `[EP 13 — final 10s]
[109.0s] ACTION: Juliana reaches out her torn, bloodied hand and wraps her fingers tightly around th...`
- LLM note: Sharp cliffhanger (1/10): Cuts on: "I found it."

### Bottom #4  — Ep [21, 22]  |  Score: 0.95
- Transcript preview: `[EP 21 — final 10s]
[108.5s] ACTION: Lady Juliana sits motionless at the rustic wooden table, her bandaged hands holding...`
- LLM note: Sharp cliffhanger (1/10): Cuts on: "Keep your head down. If anyone recognizes you, everything is over."

### Bottom #5  — Ep [25, 26]  |  Score: 0.95
- Transcript preview: `[EP 25 — final 5s]
[No dialogue/action in this window]

[EP 26 — first 20s]
[0.0s] ACTION: Juliana glances nervously bac...`
- LLM note: Sharp cliffhanger (1/10): Cuts on: "Who are you? Speak to me. I have not seen your face before."

### Bottom #6  — Ep [25, 26]  |  Score: 0.95
- Transcript preview: `[EP 25 — final 10s]
[162.5s] ACTION: Alexander turns, falling into step beside Juliana. Together, side by side, they beg...`
- LLM note: Sharp cliffhanger (1/10): Cuts on: "Who are you? Speak to me. I have not seen your face before."

### Bottom #7  — Ep [31, 32]  |  Score: 0.95
- Transcript preview: `[EP 31 — final 5s]
[No dialogue/action in this window]

[EP 32 — first 15s]
[3.8s] CATHERINE (Mocking, Savoring): "There...`
- LLM note: Sharp cliffhanger (1/10): Cuts on: "...but now you are afraid."

### Bottom #8  — Ep [17, 18]  |  Score: 1.05
- Transcript preview: `[EP 17 — final 10s]
[112.2s] JULIANA (V.O.): "But every day, he gives me another reason to trust him."

[EP 18 — first 1...`
- LLM note: Sharp cliffhanger (1/10): Cuts on: "Alexander!"

### Bottom #9  — Ep [18, 19]  |  Score: 1.05
- Transcript preview: `[EP 18 — final 5s]
[No dialogue/action in this window]

[EP 19 — first 15s]
[0.0s] ACTION: Juliana clutches her mother's...`
- LLM note: Sharp cliffhanger (1/10): Cuts on: "My lady. You cannot stay here."

### Bottom #10  — Ep [18, 19]  |  Score: 1.05
- Transcript preview: `[EP 18 — final 5s]
[No dialogue/action in this window]

[EP 19 — first 20s]
[0.0s] ACTION: Juliana clutches her mother's...`
- LLM note: Sharp cliffhanger (1/10): Cuts on: "Take it."
