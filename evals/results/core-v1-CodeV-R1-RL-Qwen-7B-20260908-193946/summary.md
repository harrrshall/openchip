# Eval `core-v1` — 20260908-193946

n = 10 (10 tasks x 1); budget 15m; model `zhuyaoyu/CodeV-R1-RL-Qwen-7B` @ `286cf433f596f1b8525529c1163eb81c19425c22` T=0.2 thinking=True

- agent accepted: 3/10
- golden pass (independent): 5/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | stalled | False | simulate | None | 1 | 339.6 | 8 | 49183 |
| edge_detector | 0 | stalled | False | pass | None | 1 | 136.0 | 7 | 27426 |
| gray_counter | 0 | completed | True | pass | counterexample | 2 | 30.5 | 5 | 12865 |
| pwm_gen | 0 | stalled | False | pass | None | 1 | 180.3 | 7 | 31024 |
| regfile | 0 | completed | True | pass | counterexample | 2 | 226.4 | 6 | 34546 |
| shift_reg | 0 | failed | False | no_rtl | None | 0 | 406.4 | 4 | 41291 |
| stream_acc | 0 | stalled | False | simulate | None | 2 | 217.9 | 9 | 49233 |
| sync_fifo | 0 | failed | False | no_rtl | None | 0 | 289.2 | 4 | 34764 |
| timer | 0 | failed | False | no_rtl | None | 0 | 39.6 | 3 | 6362 |
| updown_counter | 0 | completed | True | pass | counterexample | 1 | 26.2 | 5 | 13147 |
