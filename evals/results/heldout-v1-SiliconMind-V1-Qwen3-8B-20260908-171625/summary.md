# Eval `heldout-v1` — 20260908-171625

n = 10 (5 tasks x 2); budget 15m; model `AS-SiliconMind/SiliconMind-V1-Qwen3-8B` @ `901f9c51184334ef7270211862c42369ad7bb177` T=0.2 thinking=True

- agent accepted: 5/10
- golden pass (independent): 8/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | completed | True | pass | counterexample | 1 | 134.4 | 5 | 22230 |
| debounce | 1 | completed | True | pass | None | 1 | 222.3 | 9 | 43088 |
| prio_enc | 0 | completed | True | pass | bounded_pass | 1 | 191.0 | 7 | 31004 |
| prio_enc | 1 | failed | False | no_rtl | None | 0 | 23.4 | 4 | 12943 |
| rr_arbiter | 0 | budget_exhausted | False | pass | None | 5 | 586.4 | 11 | 76189 |
| rr_arbiter | 1 | stalled | False | simulate | None | 3 | 432.5 | 9 | 63846 |
| seq_detect | 0 | stalled | False | pass | None | 2 | 221.6 | 8 | 40173 |
| seq_detect | 1 | stalled | False | pass | None | 3 | 235.0 | 8 | 40664 |
| tick_gen | 0 | completed | True | pass | counterexample | 1 | 73.0 | 7 | 30059 |
| tick_gen | 1 | completed | True | pass | counterexample | 1 | 74.0 | 7 | 29015 |
