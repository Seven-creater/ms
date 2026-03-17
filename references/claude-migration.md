# Claude Code Migration (Minimal)

## Goal
Reuse the same Python entrypoint and JSON outputs with minimal changes.

## What to Keep
1. Keep `scripts/mshub.py` unchanged.
2. Keep command shape unchanged:
   - `model search`
   - `dataset search`
   - `model download`
   - `dataset download`
3. Keep `--json` output as the integration contract.

## Typical Calls

```bash
python scripts/mshub.py --json model search -q qwen --top 5 --with-readme
python scripts/mshub.py --json dataset search -q alpaca --top 5 --with-readme
python scripts/mshub.py --json model download --repo-id Qwen/Qwen3-8B --local-dir ./downloads/model
python scripts/mshub.py --json dataset download --repo-id AI-ModelScope/alpaca-gpt4-data-zh --local-dir ./downloads/dataset
```

## Environment
- Python + `modelscope` + `requests`
- Optional token env:

```bash
export MODELSCOPE_API_TOKEN=your_token
```

