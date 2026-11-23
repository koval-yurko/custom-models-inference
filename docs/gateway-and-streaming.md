# API Gateway and streaming

## What the gateway does

The gateway is the only public door. It checks the API key. A request without a valid key never reaches a backend, so it never starts a GPU.

```mermaid
sequenceDiagram
    participant C as Client
    participant G as API Gateway
    participant B as Private backend<br/>(LLM: CORS proxy)
    C->>G: POST /v1/... + x-api-key
    G->>G: Check the key
    alt key is wrong
        G-->>C: 4xx (backend not called)
    else key is valid
        G->>B: Same request + Google ID token of the gateway SA
        B-->>G: Response
        G-->>C: Response
    end
```

## Who creates what

```mermaid
flowchart LR
    subgraph core["infra/core/gateways.tf"]
        direction TB
        API["API<br/>1 per name in local.gateway_apis"]
        KEY["1 shared API key"]
    end
    subgraph dep["gateway module or gateway.tf"]
        direction TB
        SA["gateway<br/>service account"]
        CFG["API config<br/>OpenAPI 2.0 spec"]
        GWY["gateway"]
    end
    BE["private backend<br/>TTS or CORS proxy"]
    KEY -.->|"restricted to"| API
    API -->|"has"| CFG
    CFG -->|"used by"| GWY
    SA -->|"identity of"| CFG
    SA -->|"run.invoker on"| BE
```

- The OpenAPI spec lists the paths that reach the backend. All other paths return 404.
- `deadline` is the time limit for the whole response (300 s).
- Each path also has an `options` operation without a key. It answers the browser CORS preflight. For Vertex AI, the CORS proxy answers it.
- A config cannot change in place, so Terraform makes the new config first (`create_before_destroy`).

## Platform paths

A deployment on the `model` module (LLM-A) can run on several platforms. Its gateway has 2 paths per route:

| Path | Goes to |
|---|---|
| `/vertex/v1/chat/completions` | The `vertex` target. The CORS proxy removes `/vertex` |
| `/v1/chat/completions` (old path) | The default platform: the first one in `local.platforms` |

The gateway sends the full path to the CORS proxy (`APPEND_PATH_TO_ADDRESS`). The proxy picks the target by the first path segment. Details: `infra/README.md`, sections "Module: gateway" and "CORS proxy".

## Streaming

Terraform creates a gateway without streaming. The provider has no field for it. Streaming can be set only when a gateway is created (Public Preview).

```mermaid
flowchart LR
    A["terraform apply<br/>gateway without streaming"] --> B["gateway-streaming.py"]
    B --> C["delete gateway,<br/>create it again with streaming<br/>(same ID)"]
    C --> D["import into state,<br/>refresh"]
    D --> E["new URL: run ui-deploy.py"]
```

Warning: the gateway URL changes, and the gateway is down for some minutes. The script asks before it deletes (flag `--yes` skips the question). It does nothing when the gateway already streams.

```mermaid
flowchart LR
    subgraph N["Without streaming"]
        direction LR
        N1["Server makes all audio<br/>(about 2 min)"] --> N2["Client gets the whole file at once"]
    end
    subgraph S["With streaming"]
        direction LR
        S1["Chunk 1<br/>(first byte after about 3 s)"] --> S2["Chunk 2"] --> S3["Last chunk<br/>(about 2 min)"]
    end
```

| Model | Stream format | Where |
|---|---|---|
| LLM | SSE (`stream: true`) | `ui/src/panels/Llm.tsx` |
| TTS | raw PCM chunks, played at once | `ui/src/panels/Tts.tsx` |

Limits: the `deadline` ends the stream when it passes. It must not be longer than the Cloud Run request timeout. Streaming gateways have no custom domain during the preview.
