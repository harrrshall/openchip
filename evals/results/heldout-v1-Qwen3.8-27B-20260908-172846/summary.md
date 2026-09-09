# Eval `heldout-v1` — 20260908-172846

n = 10 (5 tasks x 2); budget 15m; model `Qwen/Qwen3.8-27B` @ `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` T=0.2 thinking=True

- agent accepted: 8/10
- golden pass (independent): 8/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | completed | True | pass | bounded_pass | 1 | 539.6 | 6 | 30211 |
| debounce | 1 | completed | True | pass | bounded_pass | 1 | 158.3 | 5 | 19142 |
| prio_enc | 0 | completed | True | pass | bounded_pass | 1 | 137.1 | 5 | 19434 |
| prio_enc | 1 | completed | True | pass | bounded_pass | 1 | 135.3 | 5 | 19434 |
| rr_arbiter | 0 | completed | True | pass | counterexample | 1 | 181.3 | 5 | 18331 |
| rr_arbiter | 1 | completed | True | pass | counterexample | 1 | 180.2 | 5 | 18331 |
| seq_detect | 0 | stalled | False | simulate | None | 3 | 487.2 | 7 | 31958 |
| seq_detect | 1 | stalled | False | simulate | None | 3 | 484.6 | 7 | 31958 |
| tick_gen | 0 | completed | True | pass | bounded_pass | 1 | 168.2 | 6 | 24489 |
| tick_gen | 1 | completed | True | pass | bounded_pass | 1 | 166.2 | 6 | 24489 |
