# Model setup: a self-hosted model for the assessment engine

The engine talks to one **OpenAI-compatible** server (`/v1/chat/completions`) inside your
deployment, through `govhub_shared.model_gateway`. It refuses any host not listed in
`MODEL_GATEWAY_ALLOWED_HOSTS`. Nothing in CI or the default Compose stack runs a model:
they use the scripted fake model. This guide covers a CPU start with **llama.cpp** and a
GPU VM with **vLLM**.

> Check each model's page for its current version and licence before you download. The
> recommendations below were written in November 2026; newer releases may exist.

## Recommended models

| Use | Model | Licence | Runs on |
|---|---|---|---|
| CPU start | Qwen3-8B (GGUF `Q4_K_M`, about 5 GB) | Apache 2.0 | 8+ cores, 16 GB RAM (32 GB recommended) |
| CPU, smallest | Qwen3-4B (GGUF `Q4_K_M`, about 2.5 GB) | Apache 2.0 | 4+ cores, 8 GB RAM |
| GPU, best French | Mistral Small 3.2 24B Instruct (2506) | Apache 2.0 | one 48 GB GPU (FP8), or 24 GB with a 4-bit GGUF in llama.cpp |

Measure all three on the same cases: the harness reports accuracy, calibration, speed and
footprint per model, in English and French separately.

## Quick start: CPU with llama.cpp (Qwen3-8B)

```bash
# 1. Build llama.cpp (once)
git clone https://github.com/ggml-org/llama.cpp
cmake -S llama.cpp -B llama.cpp/build -DGGML_NATIVE=ON
cmake --build llama.cpp/build --config Release -j
```

```bash
# 2. Download the model (accept the licence on the model page if asked)
pip install -U "huggingface_hub[cli]"
huggingface-cli download Qwen/Qwen3-8B-GGUF Qwen3-8B-Q4_K_M.gguf --local-dir models
```

```bash
# 3. Serve it on localhost only (thinking off: the engine wants one JSON answer)
llama.cpp/build/bin/llama-server -m models/Qwen3-8B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8080 -c 8192 -t "$(nproc)" --jinja \
  --chat-template-kwargs '{"enable_thinking": false}'
```

If your llama.cpp build has no `--chat-template-kwargs`, use `--reasoning-budget 0`
instead (see `llama-server --help`). For Qwen3-4B use `Qwen/Qwen3-4B-GGUF` and
`Qwen3-4B-Q4_K_M.gguf`.

```bash
# 4. Run the accuracy harness against it (from the repository)
MODEL_GATEWAY_URL=http://127.0.0.1:8080 MODEL_GATEWAY_MODEL=qwen3-8b-q4_k_m \
MODEL_GATEWAY_ALLOWED_HOSTS=127.0.0.1 \
uv run assessment-engine accuracy run --cases data/accuracy/synthetic-demo/cases.csv \
  --hardware "$(nproc) vCPU, $(free -g | awk '/Mem:/{print $2}') GB RAM, llama.cpp Q4_K_M"
```

Then the same with your human-labelled cases (`--cases data/accuracy/private/cases.csv`,
see `docs/accuracy-cases.md`). Your first run on real hardware becomes the baseline:

```bash
uv run assessment-engine accuracy baseline --run data/accuracy/runs/<run>.json
```

## GPU VM in a Canadian region with vLLM (Mistral Small 3.2 24B)

Pick a GPU VM in a Canadian region (for example a 48 GB L40S or A6000 class GPU; check
what your provider offers in its Canadian regions today), Ubuntu 22.04 or 24.04, NVIDIA
driver and Docker with the NVIDIA container toolkit installed. Keep the port on
localhost or a private network: never expose the model server publicly.

```bash
# 1. Download the official weights (needs a Hugging Face token if the page asks you to
#    accept terms; the token stays on the VM)
export HF_TOKEN=...   # only if required
huggingface-cli download mistralai/Mistral-Small-3.2-24B-Instruct-2506 --local-dir /models/mistral-small-3.2
```

```bash
# 2. Serve with vLLM, FP8 on the fly, on localhost
docker run --gpus all --rm -p 127.0.0.1:8000:8000 -v /models:/models \
  vllm/vllm-openai:latest \
  --model /models/mistral-small-3.2 --served-model-name mistral-small-3.2-24b \
  --tokenizer-mode mistral --config-format mistral --load-format mistral \
  --quantization fp8 --max-model-len 16384 --gpu-memory-utilization 0.92
```

Pin the vLLM image to a specific version tag once you have a working one. On a 24 GB GPU,
run a 4-bit GGUF of the same model with llama.cpp built with CUDA
(`-DGGML_CUDA=ON`, then `llama-server -m <model>.gguf -ngl 99 ...` as above). GGUF
conversions of Mistral Small come from third parties: check the source and checksum.

```bash
# 3. From your machine, reach it through an SSH tunnel (no public port)
ssh -N -L 8000:127.0.0.1:8000 <user>@<vm>
MODEL_GATEWAY_URL=http://127.0.0.1:8000 MODEL_GATEWAY_MODEL=mistral-small-3.2-24b \
MODEL_GATEWAY_ALLOWED_HOSTS=127.0.0.1 \
uv run assessment-engine accuracy run --cases data/accuracy/private/cases.csv \
  --hardware "1x L40S 48 GB, vLLM FP8, <provider> Canadian region"
```

## Using the model in the Compose stack

The Compose stack uses the scripted fake model by default. To use your server instead,
set the three variables before `make up`. The engine reaches the host through
`host.docker.internal`:

```bash
MODEL_GATEWAY_URL=http://host.docker.internal:8080 MODEL_GATEWAY_MODEL=qwen3-8b-q4_k_m \
MODEL_GATEWAY_ALLOWED_HOSTS=host.docker.internal make up
```

On Kubernetes/OpenShift, run the model server as its own Deployment and Service inside the
namespace and list that Service's host name in `MODEL_GATEWAY_ALLOWED_HOSTS`.

## Ollama (alternative)

```bash
ollama pull qwen3:8b
MODEL_GATEWAY_URL=http://127.0.0.1:11434 MODEL_GATEWAY_MODEL=qwen3:8b \
MODEL_GATEWAY_ALLOWED_HOSTS=127.0.0.1 uv run assessment-engine accuracy run ...
```

Ollama may not return token log-probabilities; the engine then uses the model's own
confidence, and the harness reports calibration for that one only.

## Footprint to record with each run

Pass it as `--hardware`; for the report, fill `docs/accuracy-footprint.md`:

```bash
ps -o rss= -p "$(pgrep -f llama-server)" | awk '{printf "%.1f GB RAM\n", $1/1048576}'  # CPU
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv                      # GPU
```
