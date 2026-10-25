# C2C-013：本地LLM提供方

Goal: foundation for role chat: environment-only configuration, model discovery and explicit connection test, plus internal nonstreaming completion adapter. No sessions/chat UI yet.

Choose one OpenAI-compatible local protocol (Ollama/compatible local servers), rather than multiple SDKs or cloud-provider credentials. Use existing httpx, add runtime dependency declaration. Official protocol source checked2026-10-25: https://docs.ollama.com/api/openai-compatibility — local /v1/models and /v1/chat/completions subset. No OpenAI SDK or cloud calls.

Configuration read lazily from environment, not writable through API: LLM_BASE_URL default http://127.0.0.1:11434/v1, LLM_MODEL empty until explicitly set, LLM_API_KEY optional backend-only token, LLM_REQUEST_TIMEOUT default30 bounded1–120, LLM_MAX_TOKENS default128 bounded1–2048. URL only literal loopback/localhost, http scheme and /v1 path; reject userinfo, queries, fragments and remote hosts. No redirects/proxies/retries. Invalid optional configuration must not break backend health/startup. API never echoes key/base URL or upstream error text. No automatic install/download/pull/start/stop/model warmup at startup.

API: GET /api/llm/config (configured, provider identifier, model, token-configured boolean, bounded error code), GET /api/llm/models (explicit discovery), POST /api/llm/check (fixed short prompt using configured model). Internal complete(messages) for014 only; no general public prompt endpoint now. Discover does not require selected model; check does. Timeout504, unavailable/auth502-or503, busy429, malformed/oversized/upstream errors502 with fixed codes.

Bounds: one in-flight operation per service instance, ≤40 messages/16000 total characters, ≤8000 per message, roles system/user/assistant; output text≤16000, response raw body≤256KiB and model list≤1000. Strict schemas, no credentials in repr/errors/responses. Disable compression acceptance, reject encoded responses; total asyncio.wait_for deadline plus per-operation network timeouts, bounded streamed reads. Close per-operation clients reliably on cancellation. Distinguish connection probe success from real-model validation. No GPU training or downloads.

Tests: strict config/protocol/unit fake transport and actual local HTTP fake provider, redirects/auth/timeout/body budget/credentials/partial responses, real unavailable default probe. Existing environment currently has no11434/1234 listener or Ollama executable; report PARTIAL if real provider remains absent. Preserve original55 resources; independent review before GitHub.
