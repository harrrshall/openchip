# Eval `heldout-v1` — 20260908-194303

n = 10 (5 tasks x 2); budget 15m; model `core12345/ChipMATE-V-4B` @ `7fbb17249a49d109787bbc024a7a21b83302a1c2` T=0.2 thinking=True

- agent accepted: 0/10
- golden pass (independent): 0/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | stalled | False | simulate | None | 3 | 27.0 | 8 | 22737 |
| debounce | 1 | stalled | False | simulate | None | 3 | 26.4 | 8 | 22737 |
| prio_enc | 0 | budget_exhausted | False | simulate | None | 5 | 46.0 | 13 | 38059 |
| prio_enc | 1 | budget_exhausted | False | simulate | None | 5 | 45.3 | 13 | 38051 |
| rr_arbiter | 0 | failed | False | no_rtl | None | 0 | 23.4 | 4 | 15460 |
| rr_arbiter | 1 | failed | False | no_rtl | None | 0 | 23.3 | 4 | 15460 |
| seq_detect | 0 | stalled | False | simulate | None | 1 | 29.1 | 9 | 26295 |
| seq_detect | 1 | stalled | False | simulate | None | 1 | 28.6 | 9 | 26291 |
| tick_gen | 0 | stalled | False | simulate | None | 1 | 26.5 | 6 | 20540 |
| tick_gen | 1 | stalled | False | simulate | None | 1 | 25.8 | 6 | 20540 |
