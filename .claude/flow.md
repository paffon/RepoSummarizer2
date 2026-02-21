# RepoSummarizer2 — Application Flow

## 1. High-Level Request Flow

```mermaid
flowchart TD
    A([POST /summarize]) --> B{Valid GitHub URL?}
    B -- No --> ERR422[422 Unprocessable Entity]
    B -- Yes --> C[Fetch repo metadata<br>GitHub API]
    C --> D{Repo exists<br>& is public?}
    D -- No --> ERR404[404 Not Found]
    D -- Rate limited --> ERR429[429 Too Many Requests]
    D -- Yes --> E[Check cache<br>repo + commit SHA]
    E --> F{Cache hit?}
    F -- Yes --> CACHED([Return cached summary])
    F -- No --> G[Fetch file tree<br>recursive=1]
    G --> H{Tree truncated?}
    H -- Yes --> I[Selective subtree expansion:<br>top-level + promising subdirs<br>by SHA, depth ≤ 4, max 12 dirs]
    H -- No --> J[Filter & score files]
    I --> J
    J --> K[Fetch selected files<br>in parallel via httpx]
    K --> L[Build LLM prompt<br>with token budget]
    L --> M{Repo large?}
    M -- Yes --> N[2-pass LLM<br>map → reduce]
    M -- No --> O[1-pass LLM<br>DeepSeek V3]
    N --> P{Valid JSON<br>response?}
    O --> P
    P -- No, retry --> Q[Repair prompt<br>retry once]
    Q --> R{Valid JSON<br>this time?}
    R -- No --> DEGRADE[Degrade gracefully<br>from metadata]
    R -- Yes --> S[Store in cache<br>by repo + SHA]
    P -- Yes --> S
    DEGRADE --> RESP
    S --> RESP([200 OK<br>summary + technologies + structure])
```

The main request lifecycle. Every branch either terminates with an HTTP error or flows through to a `200 OK` response. The cache check (keyed on the exact commit SHA) short-circuits the entire pipeline when the repo hasn't changed since the last request.

## 2. GitHub Data Collection

```mermaid
flowchart TD
    A[Parse github_url] --> B["GET /repos/{owner}/{repo}"]
    B --> C{HTTP status}
    C -- 404 --> ERR404[Raise RepoNotFound]
    C -- 403 --> D{Rate-limit<br>header present?}
    D -- Yes --> ERR429[Raise RateLimited]
    D -- No --> ERR403[Raise AccessDenied<br>private repo]
    C -- 200 --> E[Extract metadata:<br>default_branch, language,<br>description, size, topics,<br>license, fork, private]
    E --> F{private == true?}
    F -- Yes --> ERR404_2[Raise RepoPrivate<br>404 — message only<br>no metadata returned]
    F -- No --> G["GET /repos/{owner}/{repo}/git/<br>trees/{branch}?recursive=1"]
    G --> H{tree.truncated?}
    H -- Yes --> I["GET /repos/{owner}/{repo}/git/trees/{branch}<br>(non-recursive — top level)"]
    I --> I2[Identify promising subdirs:<br>src lib app packages etc.<br>skip blocklisted + test dirs<br>tests test __tests__ spec fixtures mocks]
    I2 --> I3["For each: GET /repos/{owner}/{repo}/git/trees/{sha}<br>non-recursive — max 12 dirs, depth ≤ 4"]
    I3 --> J[Merge into expanded tree]
    H -- No --> K[Full recursive tree]
    J --> L[Strip noise fields:<br>mode, sha, url<br>Keep: path, type, size]
    K --> L
    L --> M[Compute extension<br>frequency map]
    M --> N[Return: metadata<br>+ clean tree<br>+ primary language hint]
```

GitHub is queried with at most 2 + N calls: metadata, recursive tree attempt, and (on truncation fallback) a non-recursive top-level fetch plus up to 12 subtree fetches by SHA. All HTTP I/O is async via `httpx`. A `GITHUB_TOKEN` must be set; unauthenticated requests hit the 60-req/hour cap almost immediately under real load.

## 3. File Filtering & Prioritization

```mermaid
flowchart TD
    A[Raw file tree] --> B{"Is type blob<br>i.e. a file?"}
    B -- No, directory --> SKIP1[Skip]
    B -- Yes --> C{Matches blocklist<br>pattern?}
    C -- Yes --> SKIP2[Skip<br>node_modules vendor .git<br>binaries lock files secrets]
    C -- No --> D{size > 150 KB?}
    D -- Yes --> SKIP3[Skip<br>auto-generated or data dump]
    D -- No --> E[Assign priority score]

    E --> T1{"README*<br>manifest files<br>pyproject.toml package.json<br>Cargo.toml go.mod<br>pom.xml build.gradle<br>CMakeLists.txt Gemfile<br>pubspec.yaml mix.exs<br>*.csproj requirements.txt?"}
    T1 -- Yes --> TIER1[Tier 1 — score 100<br>Always include<br>full content]

    T1 -- No --> T2{"Language entry points?<br>py: main.py app.py wsgi.py manage.py<br>go: main.go cmd/main.go<br>js/ts: index.js index.ts server.js<br>java: Main.java Application.java<br>cs: Program.cs Startup.cs<br>c/cpp: main.c main.cpp<br>rs: src/main.rs src/lib.rs<br>rb: app.rb config.ru<br>php: index.php<br>swift: main.swift kt: Main.kt<br>dart: main.dart<br>Dockerfile Makefile .env.example?"}
    T2 -- Yes --> TIER2[Tier 2 — score 80<br>Include if budget allows<br>full content]

    T2 -- No --> T3{"Source files in<br>src/ or top-level<br>package?"}
    T3 -- Yes --> TIER3[Tier 3 — score 50<br>Signatures or first N lines<br>only]

    T3 -- No --> TIER4[Tier 4 — skip entirely<br>tests docs assets generated]

    TIER1 --> BUDGET[Token budget sort<br>score desc · size asc]
    TIER2 --> BUDGET
    TIER3 --> BUDGET
    BUDGET --> FETCH[Fetch up to 30 files<br>in parallel]
    FETCH --> NORMALIZE[Normalize content<br>① \r\n → \n<br>② strip trailing whitespace<br>③ remove empty lines<br>④ collapse license headers<br>⑤ strip decorator lines]
    NORMALIZE --> TRUNCATE{File content<br>> 10,000 chars?}
    TRUNCATE -- Yes --> TRIM[Truncate from bottom<br>keep top content]
    TRUNCATE -- No --> INCLUDE[Include full content]
    TRIM --> INCLUDE
    INCLUDE --> CONTEXT[Assembled repo context<br>ready for LLM]
```

The filtering uses a scoring function rather than ad-hoc conditionals. Higher-scored files fill the token budget first. Truncation always cuts from the bottom — the most informative content in source files is typically at the top (imports, class signatures, docstrings).

## 4. Token Budgeting

```mermaid
flowchart TD
    A[Scored file list] --> B[Compute token estimate<br>1 token ≈ 4 chars]
    B --> C[Hard ceiling =<br>80% of model context window]
    C --> D[Reserve ~1,000 tokens<br>for system prompt + schema]
    D --> E[Reserve ~3,000 tokens<br>for directory tree]
    E --> F[Reserve ~2,000 tokens<br>for LLM output]
    F --> G[Remaining = file budget]
    G --> H["Fill files sorted by (score desc, size asc)<br>— highest score first; ties broken by shortest file first<br>— stop when budget exhausted<br>— note any omitted files"]
    H --> PROMPT[Build prompt with<br>omission note if needed]
```

## 5. Two-Model LLM Pipeline

```mermaid
flowchart TD
    A[Assembled repo context] --> B{Repo size<br>estimate}
    B -- Small/Medium --> C[Single-pass strategy]
    B -- Large --> D[Two-pass map/reduce strategy]

    C --> C1[Worker: DeepSeek V3<br>temperature=0.3<br>JSON mode<br>max_tokens=2048]
    C1 --> C2{JSON valid?}
    C2 -- Yes --> OUT[Final structured output]
    C2 -- No --> C3[Repair prompt — retry once]
    C3 --> C4{JSON valid<br>this time?}
    C4 -- Yes --> OUT
    C4 -- No --> DEGRADE[Degrade: build summary<br>from GitHub metadata]
    DEGRADE --> OUT

    D --> D1["Pass A — Map chunks in parallel ⚡<br>asyncio.gather — all chunks concurrent<br>Planner: Llama 3.1 8B<br>temperature=0.2 · max_tokens=1024<br>Each chunk → structured notes"]
    D1 --> D2{All notes<br>collected?}
    D2 -- Yes --> D3["Pass B — Reduce<br>Worker: DeepSeek V3<br>Combine notes into final<br>summary/technologies/structure"]
    D3 --> C2
    D2 -- LLMError --> DEGRADE
```

The **Planner** (Llama 3.1 8B) is fast and cheap; all map calls are fired concurrently via `asyncio.gather` — wall-clock time is bounded by the slowest single chunk, not the sum. Once all notes are collected, the **Worker** (DeepSeek V3) runs a single reduce pass in JSON mode to produce the final structured response. Both call the Nebius Token Factory API using the same `AsyncOpenAI` client pattern (OpenAI-compatible endpoint).

## 6. Caching Strategy

```mermaid
flowchart TD
    A[Incoming request<br>github_url] --> B["GET /repos/{owner}/{repo}<br>(metadata call — already needed)"]
    B --> C[Extract latest commit SHA<br>for default branch]
    C --> D{SQLite lookup:<br>repo + SHA → summary}
    D -- Hit --> E([Return cached JSON<br>~0 ms latency<br>$0 LLM cost])
    D -- Miss --> F[Run full pipeline]
    F --> G[Store result:<br>INSERT OR REPLACE<br>repo + SHA → summary_json]
    G --> H([Return fresh summary])

    subgraph Cache invalidation
        I[New commit pushed<br>to repo] --> J[Next request<br>resolves new SHA]
        J --> K[Cache miss<br>new SHA not seen]
        K --> L[Process and overwrite<br>old cache entry]
    end
```

Cache entries are immortal under the commit SHA key — a given version of a repo never changes. The only invalidation event is a new commit, which produces a new SHA and automatically triggers a miss.

## 7. Error Handling & Response Codes

```mermaid
flowchart TD
    A[Any exception during pipeline] --> B{Exception type}
    B -- InvalidGitHubURL --> E422[422<br>status: error<br>message: Invalid GitHub URL...]
    B -- RepoPrivate --> PRIV[404<br>status: error<br>message: Repo not found or private]
    B -- RepoNotFound --> E404[404<br>status: error<br>message: Repo not found or private]
    B -- RateLimited --> E429[429<br>status: error<br>message: GitHub rate limit exceeded]
    B -- LLMError after retries --> E502[502<br>status: error<br>message: Upstream LLM failure]
    B -- asyncio.TimeoutError --> E504[504<br>status: error<br>message: Request timed out]
    B -- EmptyRepo --> E200["200 — empty repo<br>summary: No source files found<br>technologies: empty<br>structure: Empty repository"]
    B -- JSONDecodeError after retries --> DEGRADE[200 — degraded<br>Built from GitHub metadata<br>no LLM structured output]
```

All errors surface as JSON with `status: "error"` and a human-readable `message`. Private repos raise `RepoPrivate` (a distinct exception from `RepoNotFound`) and return a message-only 404 — no metadata is included to avoid confirming the repo exists or leaking its properties. The only case that silently degrades rather than erroring is a persistent LLM JSON parse failure — returning a partial answer is more useful to the caller than a 502.
