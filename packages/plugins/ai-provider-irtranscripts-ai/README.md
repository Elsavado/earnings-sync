# @irtranscripts/plugin-ai-provider-irtranscripts-ai

IRTranscripts AI provider plugin for the Ever IRTranscripts AI chat engine
([`@irtranscripts/plugin-ai-chat`](../ai-chat)) — currently a **placeholder**.

On bootstrap it registers the `irtranscripts-ai` provider with the chat engine's
`AiProviderRegistry` so the provider appears in the registry and the UI, but
**chat is not routed through IRTranscripts AI yet**: `createModel` throws
`Chat via IRTranscripts AI is not implemented yet — configure another provider.`
and the provider exposes no models. Use one of the direct provider plugins
(`@irtranscripts/plugin-ai-provider-anthropic`, `-openai`, `-openrouter`,
`-vercel-gateway`) in the meantime.

## Environment variables

| Variable            | Description                                              |
| ------------------- | -------------------------------------------------------- |
| `IRTRANSCRIPTS_AI_API_KEY`  | Server-wide IRTranscripts AI API key (reserved for future use).  |
| `IRTRANSCRIPTS_AI_BASE_URL` | Optional custom IRTranscripts AI API base URL.                   |

## Planned design

When the IRTranscripts AI integration
([`packages/plugins/integration-ai`](../integration-ai)) is enabled for a
tenant, chat requests for the `irtranscripts-ai` provider will be **proxied to the
IRTranscripts AI API**, which manages provider API keys, model selection and routing
server-side — so tenants get chat without configuring any upstream provider
key. BYOK (per-tenant keys via `/api/ai-chat/credentials`) remains the way to
use the direct providers, and continues to take precedence over server
environment variables for those providers.
