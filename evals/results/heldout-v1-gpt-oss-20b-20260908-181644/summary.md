# Eval `heldout-v1` — 20260908-181644

n = 10 (5 tasks x 2); budget 15m; model `openai/gpt-oss-20b` @ `6cee5e81ee83917806bbde320786a8fb61efebee` T=0.2 thinking=True

- agent accepted: 9/10
- golden pass (independent): 9/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | completed | True | pass | counterexample | 1 | 23.5 | 6 | 21773 |
| debounce | 1 | completed | True | pass | counterexample | 1 | 19.7 | 7 | 26098 |
| prio_enc | 0 | completed | True | pass | None | 1 | 13.9 | 5 | 14515 |
| prio_enc | 1 | completed | True | pass | bounded_pass | 1 | 16.8 | 5 | 14756 |
| rr_arbiter | 0 | budget_exhausted | False | simulate | None | 5 | 28.7 | 9 | 35931 |
| rr_arbiter | 1 | completed | True | pass | None | 1 | 22.7 | 6 | 22011 |
| seq_detect | 0 | completed | True | pass | counterexample | 2 | 16.1 | 6 | 19156 |
| seq_detect | 1 | completed | True | pass | counterexample | 1 | 19.8 | 6 | 18635 |
| tick_gen | 0 | completed | True | pass | counterexample | 1 | 18.9 | 6 | 23759 |
| tick_gen | 1 | completed | True | pass | counterexample | 1 | 20.1 | 6 | 24956 |
