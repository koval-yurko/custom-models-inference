# Reference examples

Each example shows one rule set in practice. Copy the closest one and change the content.

## 1. Mermaid: architecture with zones

Use for: who calls whom, and which part is public. One story only: the request path. The weights flow is a separate diagram.

```mermaid
flowchart LR
    subgraph pub["Public"]
        U["Browser<br/>test UI"]
        C["curl"]
        GW["API Gateway<br/>checks x-api-key"]
    end
    subgraph priv["Private, scale to zero"]
        CR["Cloud Run<br/>TTS Kokoro (CPU)"]
        CP["Cloud Run<br/>cors-proxy"]
        VX["Vertex AI endpoint<br/>LLM Gemma 4 (L4 GPU)"]
    end
    U -->|"x-api-key"| GW
    C -->|"x-api-key"| GW
    GW -->|"ID token"| CR
    GW -->|"ID token"| CP
    CP -->|"access token"| VX

    classDef public fill:#fff4e5,stroke:#d97706,color:#111
    classDef private fill:#e8f1ff,stroke:#2563eb,color:#111
    class U,C,GW public
    class CR,CP,VX private
    style pub fill:#fffaf2,stroke:#d97706
    style priv fill:#f5f9ff,stroke:#2563eb
```

## 2. Mermaid: sequence for a protocol

Use for: requests and answers in time order (CORS, cold start, retries). A flowchart with back edges is hard to read; a sequence is not.

```mermaid
sequenceDiagram
    participant B as Browser
    participant G as API Gateway
    participant P as CORS proxy<br/>(Cloud Run, private)
    participant V as Vertex AI
    B->>G: OPTIONS (preflight, no key)
    G->>P: OPTIONS + ID token
    P-->>B: 204 + CORS headers
    Note over P,V: Vertex AI is not called. No GPU starts.
    B->>G: POST + x-api-key
    G->>P: POST + ID token
    P->>V: :rawPredict + access token of proxy SA
    V-->>P: answer without CORS headers
    P-->>B: same status and body + CORS headers (streamed)
```

## 3. Mermaid: list nodes for layers

Use for: "what is in each part". One node per part with a short list. Do not put many unlinked nodes in a subgraph: Mermaid stacks them in one long column or row.

```mermaid
flowchart LR
    core["<b>infra/core</b><br/>apply once per project<br/>―――<br/>APIs, budget, registry repos<br/>buckets: weights, UI<br/>weights-copy job, hf-token secret<br/>API Gateway APIs, 1 shared API key"]
    dep["<b>deployments/#lt;name#gt;</b><br/>one folder and one state per model<br/>―――<br/>module model or model-service<br/>output ui"]
    core -->|"apply first"| dep

    classDef layer fill:#f8fafc,stroke:#475569,color:#111
    class core,dep layer
```

## 4. Mermaid: pipeline with one branch

Use for: steps in order. Left to right, short labels, each step once. Mark the step that costs money in red.

```mermaid
flowchart LR
    S1["hcp-sync.py"] --> S2["check.py<br/>preflight.py"] --> S3["apply<br/>infra/core"] --> W["weights-copy<br/>job"] --> A["apply<br/>deployment"]
    A -->|"Vertex AI"| V["vertex.py<br/>deploy"] --> G["gateway-<br/>streaming.py"]
    A -->|"Cloud Run"| G
    G --> U["ui-deploy.py"]

    classDef cost fill:#fde8e8,stroke:#dc2626,color:#111
    class V cost
```

## 5. D2: full system map in one picture

Use for: request path and data flow together, with zones. The ELK layout routes edges at right angles and avoids crossings. Mermaid could not do this without crossed edges. Used in [`docs/README.md`](../../../docs/README.md). Source: [`examples/system-map.d2`](examples/system-map.d2).

![System map, D2 with ELK layout](examples/system-map.d2.svg)

## 6. draw.io: overview with GCP icons

Use for: a slide-quality overview for people outside the team, with vendor icons. The SVG holds the editable diagram: open it in draw.io to change it. Positions are by hand, so every change costs more work.

![System map, draw.io with GCP icons](examples/system-map.drawio.svg)
