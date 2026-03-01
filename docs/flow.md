# RepoSummarizer2 — Application Flow (Submission Copy)

This document is a submission-facing copy of the internal flow notes, updated to match the current implementation in `src/`.

## 1. High-Level Request Flow

```mermaid
flowchart TD
    A([POST /summarize]) --> B{Valid GitHub URL?}
    B -- No --> ERR422[422 Unprocessable Entity]
    B -- Yes --> C[Fetch repo metadata<br>GitHub API]
    C --> D{Repo exists<br>& is public?}
    D -- No --> ERR404[404 Not Found]
    D -- Rate limited / access denied --> ERR429[429 Too Many Requests]
    D -- Yes --> G[Fetch file tree<br>recursive=1]
    G --> H{Tree truncated?}
    H -- Yes --> I[Selective subtree expansion:<br>top-level + promising subdirs<br>by SHA, max 12 dirs]
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
    R -- Yes --> RESP
    P -- Yes --> RESP
    DEGRADE --> RESP
    RESP([200 OK<br>summary + technologies + structure])
```

## 2. GitHub Data Collection

```mermaid
flowchart TD
    A[Parse github_url] --> B[GET /repos/{owner}/{repo}]
    B --> C{HTTP status}
    C -- 404 --> ERR404[Raise RepoNotFound]
    C -- 403 --> ERR429[Raise RateLimited]
    C -- 200 --> E[Extract metadata:<br>default_branch, language,<br>description, topics,<br>license, fork, private]
    E --> F{private == true?}
    F -- Yes --> ERR404_2[Raise RepoPrivate<br>404 message-only]
    F -- No --> G[GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1]
    G --> H{tree.truncated?}
    H -- Yes --> I[GET /git/trees/{branch}<br>non-recursive top level]
    I --> I2[Pick promising subdirs<br>skip test dirs]
    I2 --> I3[For each: GET /git/trees/{sha}<br>non-recursive, max 12]
    I3 --> J[Merge into expanded tree]
    H -- No --> K[Full recursive tree]
    J --> L[Keep: path, type, size]
    K --> L
    L --> N[Return metadata + cleaned tree]
```

Notes:
- `GITHUB_TOKEN` is optional (recommended for better rate limits), not required to start.
- `MAX_TREE_DEPTH` exists in config but is not currently enforced in the subtree expansion path.

## 3. File Filtering & Prioritization

```mermaid
flowchart TD
    A[Raw file tree] --> B{type == blob?}
    B -- No --> SKIP1[Skip]
    B -- Yes --> C{Matches blocklist?}
    C -- Yes --> SKIP2[Skip]
    C -- No --> D{size > 150 KB?}
    D -- Yes --> SKIP3[Skip]
    D -- No --> E[Assign priority score]

    E --> T1{Tier 1 manifests/docs?}
    T1 -- Yes --> TIER1[Tier 1 score 100]

    T1 -- No --> T2{Tier 2 entry/deploy files?}
    T2 -- Yes --> TIER2[Tier 2 score 80]

    T2 -- No --> T3{Tier 3 source dirs / top-level source?}
    T3 -- Yes --> TIER3[Tier 3 score 50]

    T3 -- No --> TIER4[Tier 4 score 0 skip]

    TIER1 --> BUDGET[Sort: score desc, size asc]
    TIER2 --> BUDGET
    TIER3 --> BUDGET
    BUDGET --> FETCH[Fetch up to 30 files in parallel]
    FETCH --> NORMALIZE[Normalize content]
    NORMALIZE --> TRUNCATE{content > 10,000 chars?}
    TRUNCATE -- Yes --> TRIM[Truncate from bottom]
    TRUNCATE -- No --> INCLUDE[Include full content]
    TRIM --> INCLUDE
    INCLUDE --> CONTEXT[Assembled context]
```

Note:
- Tier 3 files currently go through the same fetch/normalize/truncate path as other selected files (no dedicated signature-only parser).

## 4. Token Budgeting

```mermaid
flowchart TD
    A[Scored file list] --> B[Estimate tokens: chars / 4]
    B --> C[Large threshold: 50,000 tokens]
    C --> D[Reserve prompt/tree/output headroom]
    D --> E[Use remaining chars as file budget]
    E --> F[Greedy select by score, then size]
    F --> G[Build context + omitted file note]
```

## 5. Two-Model LLM Pipeline

```mermaid
flowchart TD
    A[Assembled repo context] --> B{Token estimate}
    B -- < 50k --> C[Single pass: DeepSeek V3]
    B -- >= 50k --> D[Map/Reduce]

    C --> C2{JSON valid?}
    C2 -- Yes --> OUT[Final output]
    C2 -- No --> C3[Repair prompt once]
    C3 --> C4{JSON valid?}
    C4 -- Yes --> OUT
    C4 -- No --> DEGRADE[Metadata degrade]
    DEGRADE --> OUT

    D --> D1[Map: Llama 3.1 8B, one call per selected file, concurrent]
    D1 --> D2{Any notes produced?}
    D2 -- No --> DEGRADE2[Metadata degrade]
    D2 -- Yes --> D3[Reduce: DeepSeek V3]
    D3 --> C2
```

Notes:
- In map/reduce mode, `LLMError` is caught and degraded to metadata response (200), not surfaced as 502.
- In single-pass mode, upstream LLM failure maps to 502.

## 6. No-cache runtime mode

For submission simplicity and deterministic behavior during evaluation, this version runs without persistent caching.
Each request executes the same fetch/filter/summarize pipeline end-to-end.

## 7. Errors & Response Shape

- API error payload shape is standardized as:

```json
{ "status": "error", "message": "Description of what went wrong" }
```

- Key mappings:
  - Invalid GitHub URL → 422
  - Invalid request body → 422
  - Repo not found/private → 404
  - GitHub rate limit/access denied path → 429
  - LLM upstream failure (single-pass path) → 502
  - Timeout → 504
  - Empty repo/no source content path → graceful 200 response
