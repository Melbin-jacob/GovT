# Speed and footprint per model (Appendix B)

Fill one row per model and size after `assessment-engine accuracy run` on the same case
file. Times come from the run file (`speed`); memory from the commands in
`docs/model-setup.md`. Every row is **DRAFT GOLDEN SET** until the golden set is confirmed.

| Date | Model | Quantization | Server | Hardware | Region | Peak memory | Median s / assessment (EN / FR) | 95th pct s (EN / FR) | Tokens/s | Verdict agreement (EN / FR) | Calibration error (EN / FR) | Run file |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | Qwen3-4B | Q4_K_M | llama.cpp | | | | | | | | | |
| | Qwen3-8B | Q4_K_M | llama.cpp | | | | | | | | | |
| | Mistral Small 3.2 24B | FP8 | vLLM | | | | | | | | | |
