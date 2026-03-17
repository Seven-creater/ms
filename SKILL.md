---
name: modelscope-download
description: Lightweight ModelScope search and download skill. Use when the user asks to search models, search datasets, download a model repo, or download a dataset repo from ModelScope. Also use when the user wants search results together with repository homepage content (README.md) for models or datasets.
---

# ModelScope Download

## Overview
Use this skill for four V1 capabilities only:
1. `model search`
2. `dataset search`
3. `model download`
4. `dataset download`

Do not expand this skill to create/upload/delete operations in V1.

## Entry Point
Run the unified script:

```bash
python scripts/mshub.py --help
```

Command families:

```bash
python scripts/mshub.py model search ...
python scripts/mshub.py dataset search ...
python scripts/mshub.py model download ...
python scripts/mshub.py dataset download ...
```

## Query + Results + Homepage (README)
When the user asks for "search results + homepage content", add `--with-readme`:

```bash
python scripts/mshub.py --json model search -q qwen --top 5 --with-readme
python scripts/mshub.py --json dataset search -q alpaca --top 5 --with-readme
```

The script also exposes a reusable Python function:

```python
from scripts.mshub import search_with_readme

result = search_with_readme(
    "qwen",
    entity="model",      # or "dataset"
    top=5,
    include_readme=True,
)
```

## Output
- Default output: concise human-readable summary.
- `--json`: structured output for agents.
- Search result schema includes:
  - `repo_id`
  - `name`
  - `owner`
  - `description`
  - `downloads`
  - `likes`
  - `updated_at`
  - optional `homepage` when `--with-readme` is enabled

## Version Strategy
- Recommended: `modelscope==1.35.0`
- Minimum tested compatibility: `1.9.5`
- Do not auto-modify global environment.
- If capability is unavailable in the current version, return a clear hint and next step.

## Token and Permissions
- Public search/download works without token.
- Private resources require `MODELSCOPE_API_TOKEN` or `--token`.

## References
- Capability mapping: `references/capability-mapping.md`
- Optional migration notes: `references/claude-migration.md`
- ModelScope docs:
  - https://www.modelscope.cn/docs/%E6%A8%A1%E5%9E%8B%E7%9A%84%E4%B8%8B%E8%BD%BD
  - https://www.modelscope.cn/docs/%E6%95%B0%E6%8D%AE%E9%9B%86%E7%9A%84%E4%B8%8B%E8%BD%BD

