# LLM Providers Guide

TBL supports multiple LLM providers. This guide explains how to set up each one.

---

## Ollama (Local)

Runs models locally on your machine.

### Setup

1. Install from [ollama.com](https://ollama.com/)
2. Download a model: `ollama pull qwen3:14b`
3. Select "Ollama" in TBL

### Models by VRAM

| VRAM | Model | Size |
|------|-------|------|
| 6-10 GB | `qwen3:8b` | 5.2 GB |
| 10-16 GB | `qwen3:14b` | 9.3 GB |
| 16-24 GB | `qwen3:30b-instruct` | 19 GB |
| 48+ GB | `qwen3:235b` | 142 GB |

Browse models: [ollama.com/search](https://ollama.com/search)

### CLI Example

```bash
python translate.py -i book.txt -o book_fr.txt -m qwen3:14b
```

---

## OpenAI-Compatible Servers (Local)

TBL supports any server that implements the OpenAI API format. This includes:

- **llama.cpp** (`llama-server`) - Lightweight, direct model serving
- **LM Studio** - Desktop app with GUI
- **vLLM** - High-performance serving
- **LocalAI** - Drop-in OpenAI replacement
- **Text Generation Inference** - HuggingFace's serving solution

### Setup

1. Start your OpenAI-compatible server
2. In TBL:
   - Select "OpenAI-Compatible" provider
   - Set endpoint to your server URL (see table below)
   - Leave API key empty (local servers don't require it)

| Server | Default Endpoint |
|--------|------------------|
| llama.cpp (`llama-server`) | `http://localhost:8080/v1/chat/completions` |
| LM Studio | `http://localhost:1234/v1/chat/completions` |
| vLLM | `http://localhost:8000/v1/chat/completions` |
| LocalAI | `http://localhost:8080/v1/chat/completions` |

### CLI Examples

```bash
# llama.cpp (llama-server)
python translate.py -i book.txt -o book_fr.txt \
    --provider openai \
    --api_endpoint http://localhost:8080/v1/chat/completions \
    -m your-model-name

# LM Studio
python translate.py -i book.txt -o book_fr.txt \
    --provider openai \
    --api_endpoint http://localhost:1234/v1/chat/completions \
    -m your-model-name
```

---

## OpenRouter (Cloud)

Access to 200+ models from multiple providers through a single API.

### Setup

1. Get API key at [openrouter.ai/keys](https://openrouter.ai/keys)
2. In TBL: Select "OpenRouter", enter your key
3. Choose a model from the list

### CLI Example

```bash
python translate.py -i book.txt -o book_fr.txt \
    --provider openrouter \
    --openrouter_api_key sk-or-v1-your-key \
    -m anthropic/claude-sonnet-4
```

Browse models and pricing: [openrouter.ai/models](https://openrouter.ai/models)

---

## OpenAI Cloud

Official OpenAI API (GPT models). Uses the same "OpenAI-Compatible" provider in TBL.

### Models

- `gpt-4o` - Latest GPT-4
- `gpt-4o-mini` - Smaller, cheaper
- `gpt-4-turbo`
- `gpt-3.5-turbo`

### Setup

1. Get API key at [platform.openai.com](https://platform.openai.com/api-keys)
2. In TBL:
   - Select "OpenAI-Compatible" provider
   - Keep endpoint as `https://api.openai.com/v1/chat/completions`
   - Enter your API key

### CLI Example

```bash
python translate.py -i book.txt -o book_fr.txt \
    --provider openai \
    --openai_api_key sk-your-key \
    -m gpt-4o
```

Pricing: [openai.com/pricing](https://openai.com/pricing)

---

## Google Gemini (Cloud)

Google's Gemini models.

### Models

- `gemini-2.0-flash`
- `gemini-1.5-pro`
- `gemini-1.5-flash`

### Setup

1. Get API key at [Google AI Studio](https://makersuite.google.com/app/apikey)
2. In TBL: Select "Gemini", enter your key

### CLI Example

```bash
python translate.py -i book.txt -o book_fr.txt \
    --provider gemini \
    --gemini_api_key your-key \
    -m gemini-2.0-flash
```

---

## Anthropic (Cloud)

Native Claude API integration with prompt caching. Different from accessing Claude through OpenRouter or Poe: this provider talks to `api.anthropic.com` directly and wraps the system prompt in `cache_control` so Anthropic's prompt caching kicks in. On a long book this typically gives a 2-3x net saving on input tokens.

### Models

- `claude-sonnet-4-6` — best price/quality balance, recommended default
- `claude-opus-4-7` — highest quality, more expensive
- `claude-haiku-4-5` — cheapest, fast

### Setup

1. Get API key at [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)
2. In TBL: Select "Anthropic", enter your key
3. Or set in `.env`:

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6
ANTHROPIC_PROMPT_CACHING=true   # default; set to false only for debugging
```

### CLI Example

```bash
python translate.py -i book.txt -o book_fr.txt \
    --provider anthropic \
    --anthropic_api_key sk-ant-... \
    -m claude-sonnet-4-6
```

Pricing: [anthropic.com/pricing](https://www.anthropic.com/pricing)

---

## Mistral (Cloud)

European cloud provider with strong multilingual quality.

### Models

- `mistral-large-latest` — flagship
- `mistral-small-latest` — cheaper, fast
- `open-mistral-nemo`
- `codestral-latest`

### Setup

1. Get API key at [console.mistral.ai/api-keys](https://console.mistral.ai/api-keys)
2. In TBL: Select "Mistral", enter your key

### CLI Example

```bash
python translate.py -i book.txt -o book_fr.txt \
    --provider mistral \
    --mistral_api_key your-key \
    -m mistral-large-latest
```

Pricing: [mistral.ai/technology](https://mistral.ai/technology)

---

## DeepSeek (Cloud)

Chinese LLM provider with 64K context and OpenAI-compatible API. Supports thinking models.

### Models

- `deepseek-v4-pro` — high-quality model
- `deepseek-v4-flash` — faster economical model
- `deepseek-chat` — legacy alias scheduled for deprecation on 2026-07-24
- `deepseek-reasoner` — reasoning model with `<think>` blocks

### Setup

1. Get API key at [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys)
2. In TBL: Select "DeepSeek", enter your key

### CLI Example

```bash
python translate.py -i book.txt -o book_fr.txt \
    --provider deepseek \
    --deepseek_api_key your-key \
    -m deepseek-v4-pro
```

Pricing: [api-docs.deepseek.com/quick_start/pricing](https://api-docs.deepseek.com/quick_start/pricing)

---

## Poe (Cloud)

Single key, many models — Claude, GPT, Gemini, Llama, Mistral, DeepSeek and more from one Poe account.

### Setup

1. Get API key at [poe.com/api_key](https://poe.com/api_key)
2. In TBL: Select "Poe", enter your key
3. Pick a model name from [poe.com](https://poe.com/) (case-sensitive, e.g. `Claude-Sonnet-4`)

### CLI Example

```bash
python translate.py -i book.txt -o book_fr.txt \
    --provider poe \
    --poe_api_key your-key \
    -m Claude-Sonnet-4
```

> Poe usage is metered in points — each model has its own cost. Check the model card on poe.com for the rate.

---

## NVIDIA NIM (Cloud)

Hosted models via NVIDIA's inference platform — OpenAI-compatible API, generous free tier.

### Setup

1. Get API key at [build.nvidia.com](https://build.nvidia.com/)
2. In TBL: Select "NVIDIA NIM", enter your key

### CLI Example

```bash
python translate.py -i book.txt -o book_fr.txt \
    --provider nim \
    --nim_api_key your-key \
    -m meta/llama-3.1-8b-instruct
```

Browse models: [build.nvidia.com](https://build.nvidia.com/)

---

## Fallback Provider

When the primary provider returns a refusal (full or partial), echoes the input, produces output with too many latin characters for a non-latin target, or fails completely after retries and token alignment, the runner re-translates that chunk through a **second provider**. This is designed for cases where the primary occasionally refuses chunks even with safety thresholds at their loosest setting — typically NSFW fiction translated by cloud providers, but also useful for obscure technical text.

Two layers work together:

- **Post-validation** (`RESPONSE_VALIDATION_*`) — detects suspicious chunks (latin-ratio overshoot, echoed source, refusal phrases). Always runs, costs nothing extra.
- **Fallback runner** (`FALLBACK_*`) — re-translates the flagged chunks through the configured fallback provider. Optional; leave `FALLBACK_PROVIDER` empty to keep only the warnings.

### Setup

In `.env`:

```bash
FALLBACK_PROVIDER=ollama          # or deepseek, anthropic, gemini, etc.
FALLBACK_MODEL=qwen3:14b
FALLBACK_API_KEY=                 # required only for cloud fallbacks
FALLBACK_MAX_INVOCATIONS_PER_JOB=100   # hard cap on cost in worst case
FALLBACK_TRIGGER_ON_PHASE3=true        # fallback when primary completely fails
FALLBACK_TRIGGER_ON_SUSPICIOUS=true    # fallback when post-validation flags the output
```

### Recommended presets

**NSFW fiction.** Primary Gemini Flash 3.5 (fast, cheap, good multilingual), fallback to local Ollama with `qwen3:14b` on a workstation. Gemini's internal safety filter strips a small percentage of explicit chunks regardless of `GEMINI_SAFETY_THRESHOLD`; the local model picks them up.

```bash
LLM_PROVIDER=gemini
DEFAULT_MODEL=gemini-2.5-flash
FALLBACK_PROVIDER=ollama
FALLBACK_MODEL=qwen3:14b
OLLAMA_HOST=http://192.168.x.x:11434
FALLBACK_MAX_INVOCATIONS_PER_JOB=200
```

**Technical books / universal safety net.** Primary Anthropic/Gemini/OpenAI, fallback DeepSeek. Cheap, no censorship on technical content, useful when the primary occasionally refuses obscure excerpts.

```bash
FALLBACK_PROVIDER=deepseek
FALLBACK_MODEL=deepseek-chat
FALLBACK_API_KEY=sk-...
FALLBACK_MAX_INVOCATIONS_PER_JOB=100
```

### Post-validation tuning

```bash
RESPONSE_VALIDATION_ENABLED=true
RESPONSE_VALIDATION_LATIN_THRESHOLD=0.15   # raise to 0.20-0.25 for books with many english names; lower to 0.05-0.10 for strict literary work
RESPONSE_VALIDATION_ECHO_ENABLED=true      # turn off only when source and target language match (e.g. polish/refine on same language)
```

The translation summary at the end of the job reports how many chunks were flagged and how many were successfully re-translated via fallback.

> Known limitation: the draft-mode pipeline and Phase 2 token-alignment success path currently bypass post-validation. Suspicious chunks produced there are not routed to fallback.

---

## API Key Rotation

Every cloud provider above accepts a comma-separated list of keys (e.g. `key1,key2,key3`). The system automatically rotates keys on HTTP 429 — useful for chaining free-tier accounts. See [API_KEY_ROTATION.md](API_KEY_ROTATION.md) for details.

---

## Environment Variables

Store settings in `.env` file:

```bash
# Provider
LLM_PROVIDER=ollama

# API Keys (each accepts comma-separated values for automatic rotation)
OPENROUTER_API_KEY=sk-or-v1-...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...
MISTRAL_API_KEY=...
DEEPSEEK_API_KEY=...
POE_API_KEY=...
NIM_API_KEY=...

# Anthropic-specific
ANTHROPIC_MODEL=claude-sonnet-4-6
ANTHROPIC_PROMPT_CACHING=true     # 2-3x savings on input tokens for long books

# Ollama settings
API_ENDPOINT=http://localhost:11434/api/generate
DEFAULT_MODEL=qwen3:14b

# Fallback provider (optional, see "Fallback Provider" section above)
FALLBACK_PROVIDER=
FALLBACK_MODEL=
FALLBACK_API_KEY=
FALLBACK_MAX_INVOCATIONS_PER_JOB=100
FALLBACK_TRIGGER_ON_PHASE3=true
FALLBACK_TRIGGER_ON_SUSPICIOUS=true

# Post-validation (optional, see "Fallback Provider" section above)
RESPONSE_VALIDATION_ENABLED=true
RESPONSE_VALIDATION_LATIN_THRESHOLD=0.15
RESPONSE_VALIDATION_ECHO_ENABLED=true
```
