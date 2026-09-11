# Model comparison (identical protocol; all runs on JarvisLabs)

Protocol per model: core-v1 (10 tasks × 1, budget 15 min), heldout-v1 (5 × 2, thresholds pre-registered), VerilogEval v2 spec-to-rtl direct single-shot pass@1 (n=156, T=0.2, no thinking), VerilogEval v2 agent mode (every 4th problem, n=39, budget 6 min). Golden pass = independently correct against human-written references never shown to the model. False acceptance = agent accepted but independent check failed.

| Model @ rev | core-v1 golden | core-v1 false acc. | heldout golden | heldout false acc. | VerilogEval direct pass@1 | VerilogEval agent pass | agent false acc. | core-v1 mean wall s |
|---|---|---|---|---|---|---|---|---|
| `AS-SiliconMind/SiliconMind-V1-Qwen3-8B @ 901f9c5118` | 7/10 | 0/10 | 8/10 | 0/10 | 76/156 | 19/39 | 7/39 | 179.5 |
| `Qwen/Qwen3-8B @ b968826d9c` | 6/10 | 1/10 | 5/10 | 1/10 | 47/156 | 13/39 | 5/39 | 115.7 |
| `Qwen/Qwen3.5-35B-A3B @ 59d61f3ce6` | 7/10 | 0/10 | 8/10 | 0/10 | 87/156 | 23/39 | 5/39 | 67.7 |
| `Qwen/Qwen3.5-9B @ c202236235` | 7/10 | 0/10 | 8/10 | 2/10 | 66/156 | 17/39 | 8/39 | 139.6 |
| `Qwen/Qwen3.6-27B @ 6a9e13bd6f` | 9/10 | 0/10 | 6/10 | 0/10 | 104/156 | 18/39 | 2/39 | 470.2 |
| `Qwen/Qwen3.8-27B @ 1d4bf0f2ff` | 10/10 | 0/10 | 8/10 | 0/10 | 76/156 | 21/39 | 10/39 | 244.8 |
| `core12345/ChipMATE-V-4B @ 7fbb17249a` | 5/10 | 1/10 | 0/10 | 0/10 | 41/156 | 7/39 | 3/39 | 46.3 |
| `deepseek-v4-flash @ remote` | 9/10 | 0/10 | 10/10 | 0/10 | 124/156 | 32/39 | 1/39 | 218.9 |
| `glm-5.3 @ remote` | 10/10 | 0/10 | 10/10 | 0/10 | 109/156 | 28/39 | 6/39 | 113.0 |
| `openai/gpt-oss-120b @ b5c939de8f` | 9/10 | 1/10 | 8/10 | 0/10 | 114/156 | 28/39 | 9/39 | 34.2 |
| `openai/gpt-oss-20b @ 6cee5e81ee` | 8/10 | 0/10 | 9/10 | 0/10 | 95/156 | 22/39 | 12/39 | 23.2 |
| `zhuyaoyu/CodeV-R1-RL-Qwen-7B @ 286cf433f5` | 5/10 | 0/10 | 5/10 | 0/10 | 95/156 | 20/39 | 1/39 | 189.2 |

Source directories:

- `AS-SiliconMind/SiliconMind-V1-Qwen3-8B @ 901f9c5118`: core-v1=`core-v1-SiliconMind-V1-Qwen3-8B-20260908-164627`, heldout-v1=`heldout-v1-SiliconMind-V1-Qwen3-8B-20260908-171625`, veval-agent=`verilogeval-v2-agent-SiliconMind-V1-Qwen3-8B-20260908-183402`, veval-direct=`verilogeval-v2-direct-SiliconMind-V1-Qwen3-8B-20260908-175302`
- `Qwen/Qwen3-8B @ b968826d9c`: core-v1=`core-v1-20260908-115153`, heldout-v1=`heldout-v1-20260908-154311`, veval-agent=`verilogeval-v2-agent-20260908-141552`, veval-direct=`verilogeval-v2-direct-20260908-132456`
- `Qwen/Qwen3.5-35B-A3B @ 59d61f3ce6`: core-v1=`core-v1-Qwen3.5-35B-A3B-20260908-192531`, heldout-v1=`heldout-v1-Qwen3.5-35B-A3B-20260908-193652`, veval-agent=`verilogeval-v2-agent-Qwen3.5-35B-A3B-20260908-195612`, veval-direct=`verilogeval-v2-direct-Qwen3.5-35B-A3B-20260908-194618`
- `Qwen/Qwen3.5-9B @ c202236235`: core-v1=`core-v1-Qwen3.5-9B-20260908-164638`, heldout-v1=`heldout-v1-Qwen3.5-9B-20260908-170958`, veval-agent=`verilogeval-v2-agent-Qwen3.5-9B-20260908-175606`, veval-direct=`verilogeval-v2-direct-Qwen3.5-9B-20260908-172853`
- `Qwen/Qwen3.6-27B @ 6a9e13bd6f`: core-v1=`core-v1-Qwen3.6-27B-20260908-164620`, heldout-v1=`heldout-v1-Qwen3.6-27B-20260908-180445`, veval-agent=`verilogeval-v2-agent-Qwen3.6-27B-20260908-200815`, veval-direct=`verilogeval-v2-direct-Qwen3.6-27B-20260908-192938`
- `Qwen/Qwen3.8-27B @ 1d4bf0f2ff`: core-v1=`core-v1-Qwen3.8-27B-20260908-164755`, heldout-v1=`heldout-v1-Qwen3.8-27B-20260908-172846`, veval-agent=`verilogeval-v2-agent-Qwen3.8-27B-20260908-184327`, veval-direct=`verilogeval-v2-direct-Qwen3.8-27B-20260908-181246`
- `core12345/ChipMATE-V-4B @ 7fbb17249a`: core-v1=`core-v1-ChipMATE-V-4B-20260908-193516`, heldout-v1=`heldout-v1-ChipMATE-V-4B-20260908-194303`, veval-agent=`verilogeval-v2-agent-ChipMATE-V-4B-20260908-195324`, veval-direct=`verilogeval-v2-direct-ChipMATE-V-4B-20260908-194808`
- `deepseek-v4-flash @ remote`: core-v1=`core-v1-deepseek-v4-flash-20260909-041529`, heldout-v1=`heldout-v1-deepseek-v4-flash-20260909-064225`, veval-agent=`verilogeval-v2-agent-deepseek-v4-flash-20260909-080655`, veval-direct=`verilogeval-v2-direct-deepseek-v4-flash-20260909-071537`
- `glm-5.3 @ remote`: core-v1=`core-v1-glm-5.3-20260909-041535`, heldout-v1=`heldout-v1-glm-5.3-20260909-064224`, veval-agent=`verilogeval-v2-agent-glm-5.3-20260909-071514`, veval-direct=`verilogeval-v2-direct-glm-5.3-20260909-065441`
- `openai/gpt-oss-120b @ b5c939de8f`: core-v1=`core-v1-gpt-oss-120b-20260908-181846`, heldout-v1=`heldout-v1-gpt-oss-120b-20260908-182432`, veval-agent=`verilogeval-v2-agent-gpt-oss-120b-20260908-183615`, veval-direct=`verilogeval-v2-direct-gpt-oss-120b-20260908-182952`
- `openai/gpt-oss-20b @ 6cee5e81ee`: core-v1=`core-v1-gpt-oss-20b-20260908-181249`, heldout-v1=`heldout-v1-gpt-oss-20b-20260908-181644`, veval-agent=`verilogeval-v2-agent-gpt-oss-20b-20260908-182356`, veval-direct=`verilogeval-v2-direct-gpt-oss-20b-20260908-182007`
- `zhuyaoyu/CodeV-R1-RL-Qwen-7B @ 286cf433f5`: core-v1=`core-v1-CodeV-R1-RL-Qwen-7B-20260908-193946`, heldout-v1=`heldout-v1-CodeV-R1-RL-Qwen-7B-20260908-201122`, veval-agent=`verilogeval-v2-agent-CodeV-R1-RL-Qwen-7B-20260908-210332`, veval-direct=`verilogeval-v2-direct-CodeV-R1-RL-Qwen-7B-20260908-203655`
