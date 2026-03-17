# Capability Mapping (V1)

## Scope
This skill intentionally supports only:
1. model search
2. dataset search
3. model download
4. dataset download

## Command -> API/CLI

| Command | Primary Path | Compatibility/Fallback Path | Notes |
|---|---|---|---|
| `model search` | SDK `HubApi.list_models` (when `--owner` is provided) | OpenAPI `GET /openapi/v1/models` | Global search defaults to OpenAPI for better cross-version behavior. |
| `dataset search` | SDK `HubApi.list_datasets` | OpenAPI `GET /openapi/v1/datasets` | Older SDK versions may fail on list endpoint, so OpenAPI fallback is enabled. |
| `model download` | SDK `snapshot_download` | file-level download (`HubApi.get_model_files` + `model_file_download`) or CLI `modelscope download` | File-level path is used when include/exclude patterns are provided. |
| `dataset download` | SDK `dataset_snapshot_download` | legacy file-list path (`get_dataset_meta_file_list` + repo file URL download), then CLI if available | Legacy path improves compatibility in versions without `dataset_snapshot_download`. |

## Search Result Schema

```json
{
  "repo_id": "owner/name",
  "name": "display name",
  "owner": "owner",
  "description": "text",
  "downloads": 123,
  "likes": 10,
  "updated_at": "2026-01-01T00:00:00Z",
  "tags": [],
  "homepage": {
    "ok": true,
    "path": "README.md",
    "content": "...",
    "content_preview": "...",
    "content_length": 1234
  }
}
```

`homepage` is included only when `--with-readme` or `search_with_readme(..., include_readme=True)` is used.

## Version Policy
- Recommended: `modelscope==1.35.0`
- Minimum tested: `1.9.5`
- The script must not auto-upgrade global packages.
- On incompatibility, return capability hint and next-step guidance.

