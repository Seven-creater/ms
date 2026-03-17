#!/usr/bin/env python3
"""ModelScope lightweight helper (V1): search + download."""

from __future__ import annotations

import argparse
import fnmatch
import inspect
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

import requests

DEFAULT_ENDPOINT = "https://www.modelscope.cn"
DEFAULT_REVISION = "master"
DEFAULT_TOP_N = 10
RECOMMENDED_MODELSCOPE_VERSION = "1.35.0"
MIN_COMPATIBLE_VERSION = "1.9.5"
REQUEST_TIMEOUT = 60


class MSHubError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        next_step: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_step = next_step
        self.details = details or {}


def parse_version(version: str) -> Tuple[int, ...]:
    parts: List[int] = []
    for token in version.replace("-", ".").split("."):
        if token.isdigit():
            parts.append(int(token))
            continue
        digits = "".join(ch for ch in token if ch.isdigit())
        if digits:
            parts.append(int(digits))
        else:
            break
    return tuple(parts) if parts else (0,)


def normalize_endpoint(endpoint: str) -> str:
    endpoint = endpoint.strip()
    return endpoint.rstrip("/") if endpoint else DEFAULT_ENDPOINT


def call_with_supported_kwargs(func: Callable[..., Any], kwargs: Dict[str, Any]) -> Any:
    signature = inspect.signature(func)
    has_var_kw = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if has_var_kw:
        call_kwargs = {k: v for k, v in kwargs.items() if v is not None}
    else:
        call_kwargs = {
            k: v
            for k, v in kwargs.items()
            if k in signature.parameters and v is not None
        }
    return func(**call_kwargs)


def build_openapi_headers(token: Optional[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def request_openapi(
    endpoint: str,
    path: str,
    params: Dict[str, Any],
    token: Optional[str],
) -> Dict[str, Any]:
    url = f"{normalize_endpoint(endpoint)}{path}"
    try:
        response = requests.get(
            url,
            params={k: v for k, v in params.items() if v not in (None, "")},
            headers=build_openapi_headers(token),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise MSHubError(
            code="network_error",
            message=f"Failed to connect to ModelScope endpoint: {normalize_endpoint(endpoint)}",
            next_step="Check network or --endpoint value and retry.",
            details={"error": str(exc)},
        ) from exc
    if response.status_code >= 400:
        raise MSHubError(
            code="openapi_request_failed",
            message=f"OpenAPI request failed: HTTP {response.status_code}",
            next_step="Check network access and endpoint, then retry.",
            details={"url": url, "status_code": response.status_code, "body": response.text[:500]},
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise MSHubError(
            code="openapi_invalid_json",
            message="OpenAPI response is not valid JSON.",
            next_step="Retry later or switch to SDK path.",
            details={"url": url, "error": str(exc)},
        ) from exc

    if isinstance(payload, dict) and payload.get("success") is True and "data" in payload:
        data = payload["data"]
        return data if isinstance(data, dict) else {"items": data}
    if isinstance(payload, dict):
        return payload
    return {"items": payload}


def pick_value(item: Dict[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return default


def to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def ensure_list(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        priority_keys = (
            "models",
            "datasets",
            "items",
            "Models",
            "Datasets",
            "Data",
            "objects",
            "results",
        )
        for key in priority_keys:
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = ensure_list(value)
                if nested:
                    return nested
        for value in data.values():
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def split_repo_id(repo_id: str) -> Tuple[str, str]:
    if "/" not in repo_id:
        raise MSHubError(
            code="invalid_repo_id",
            message=f"Invalid repo_id: {repo_id}",
            next_step="Use the format <owner>/<name>, e.g. AI-ModelScope/alpaca-gpt4-data-zh.",
        )
    owner, name = repo_id.split("/", 1)
    if not owner or not name:
        raise MSHubError(
            code="invalid_repo_id",
            message=f"Invalid repo_id: {repo_id}",
            next_step="Use the format <owner>/<name>, e.g. Qwen/Qwen3.5-27B.",
        )
    return owner, name


def make_local_dir(entity: str, repo_id: str, local_dir: Optional[str]) -> Path:
    if local_dir:
        target = Path(local_dir)
    else:
        target = Path.cwd() / "downloads" / entity / repo_id.replace("/", "--")
    target.mkdir(parents=True, exist_ok=True)
    return target


def compile_patterns(patterns: Optional[List[str]]) -> List[str]:
    if not patterns:
        return []
    return [pattern.strip() for pattern in patterns if pattern and pattern.strip()]


def path_selected(path: str, include: List[str], exclude: List[str]) -> bool:
    if include:
        include_match = any(fnmatch.fnmatch(path, pattern) for pattern in include)
        if not include_match:
            return False
    if exclude and any(fnmatch.fnmatch(path, pattern) for pattern in exclude):
        return False
    return True


def normalized_search_text(item: Dict[str, Any]) -> str:
    chunks: List[str] = []
    for key in ("repo_id", "name", "owner", "description"):
        value = item.get(key)
        if value:
            chunks.append(str(value))
    tags = item.get("tags")
    if isinstance(tags, list):
        chunks.extend(str(tag) for tag in tags)
    elif tags:
        chunks.append(str(tags))
    return " ".join(chunks).lower()


def filter_and_rank(items: List[Dict[str, Any]], query: str, top: int) -> List[Dict[str, Any]]:
    q = query.strip().lower()
    if q:
        items = [item for item in items if q in normalized_search_text(item)]
    items.sort(
        key=lambda item: (
            item.get("downloads") or -1,
            item.get("likes") or -1,
            str(item.get("updated_at") or ""),
        ),
        reverse=True,
    )
    if top > 0:
        items = items[:top]
    return items


def normalize_model_item(item: Dict[str, Any]) -> Dict[str, Any]:
    owner = pick_value(item, ("owner", "author", "namespace", "Owner", "Author"), "")
    model_id = pick_value(item, ("id", "model_id", "ModelId", "Path", "path"), "")
    name = pick_value(item, ("display_name", "name", "Name", "model_name"), model_id)
    if isinstance(name, str) and "/" in name and not model_id:
        model_id = name
    if model_id and "/" not in model_id and owner:
        model_id = f"{owner}/{model_id}"
    if not owner and isinstance(model_id, str) and "/" in model_id:
        owner = model_id.split("/", 1)[0]

    return {
        "type": "model",
        "repo_id": model_id,
        "name": name,
        "owner": owner,
        "description": pick_value(item, ("description", "Description", "summary", "Summary"), ""),
        "downloads": to_int(pick_value(item, ("downloads", "Downloads", "download_count", "DownloadCount"))),
        "likes": to_int(pick_value(item, ("likes", "Likes", "like_count", "LikeCount"))),
        "updated_at": pick_value(item, ("last_modified", "updated_at", "UpdatedAt", "LastModified", "created_at"), ""),
        "tags": pick_value(item, ("tags", "Tags"), []),
    }


def normalize_dataset_item(item: Dict[str, Any]) -> Dict[str, Any]:
    owner = pick_value(item, ("owner", "author", "namespace", "Owner", "Author"), "")
    dataset_id = pick_value(item, ("id", "dataset_id", "DatasetId", "Path", "path", "dataset_name"), "")
    name = pick_value(item, ("display_name", "name", "Name", "dataset_name"), dataset_id)
    if dataset_id and "/" not in dataset_id and owner:
        dataset_id = f"{owner}/{dataset_id}"
    if not owner and isinstance(dataset_id, str) and "/" in dataset_id:
        owner = dataset_id.split("/", 1)[0]

    return {
        "type": "dataset",
        "repo_id": dataset_id,
        "name": name,
        "owner": owner,
        "description": pick_value(item, ("description", "Description", "summary", "Summary"), ""),
        "downloads": to_int(pick_value(item, ("downloads", "Downloads", "download_count", "DownloadCount"))),
        "likes": to_int(pick_value(item, ("likes", "Likes", "like_count", "LikeCount"))),
        "updated_at": pick_value(item, ("last_modified", "updated_at", "UpdatedAt", "LastModified", "created_at"), ""),
        "tags": pick_value(item, ("tags", "Tags"), []),
    }


def detect_runtime(endpoint: str) -> Dict[str, Any]:
    runtime: Dict[str, Any] = {
        "endpoint": normalize_endpoint(endpoint),
        "modelscope_version": None,
        "capabilities": {
            "model_search": False,
            "dataset_search": False,
            "model_download": False,
            "dataset_download": False,
            "cli_download": False,
            "cli_dataset_download": False,
        },
        "notes": [],
        "snapshot_model_fn": None,
        "snapshot_dataset_fn": None,
        "model_file_download_fn": None,
    }

    try:
        import modelscope  # type: ignore
        from modelscope.hub.api import HubApi  # type: ignore
    except Exception as exc:
        raise MSHubError(
            code="modelscope_not_installed",
            message="ModelScope is not installed in current Python environment.",
            next_step="Install with: python -m pip install modelscope",
            details={"error": str(exc)},
        ) from exc

    runtime["modelscope_version"] = getattr(modelscope, "__version__", "unknown")
    runtime["HubApi"] = HubApi
    runtime["capabilities"]["model_search"] = hasattr(HubApi, "list_models")
    runtime["capabilities"]["dataset_search"] = hasattr(HubApi, "list_datasets")

    model_fn: Optional[Callable[..., Any]] = None
    dataset_fn: Optional[Callable[..., Any]] = None
    try:
        from modelscope import snapshot_download as model_snapshot_download  # type: ignore

        model_fn = model_snapshot_download
    except Exception:
        try:
            from modelscope.hub.snapshot_download import snapshot_download as model_snapshot_download  # type: ignore

            model_fn = model_snapshot_download
        except Exception:
            model_fn = None

    try:
        from modelscope import dataset_snapshot_download as dataset_snapshot_download_fn  # type: ignore

        dataset_fn = dataset_snapshot_download_fn
    except Exception:
        try:
            from modelscope.hub.snapshot_download import dataset_snapshot_download as dataset_snapshot_download_fn  # type: ignore

            dataset_fn = dataset_snapshot_download_fn
        except Exception:
            dataset_fn = None

    try:
        from modelscope.hub.file_download import model_file_download  # type: ignore

        runtime["model_file_download_fn"] = model_file_download
    except Exception:
        runtime["model_file_download_fn"] = None

    runtime["snapshot_model_fn"] = model_fn
    runtime["snapshot_dataset_fn"] = dataset_fn
    runtime["capabilities"]["model_download"] = model_fn is not None
    runtime["capabilities"]["dataset_download"] = dataset_fn is not None or hasattr(HubApi, "get_dataset_meta_file_list")

    if shutil.which("modelscope"):
        runtime["capabilities"]["cli_download"] = True
        try:
            cli_help = subprocess.run(
                ["modelscope", "download", "-h"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            help_text = f"{cli_help.stdout}\n{cli_help.stderr}"
            runtime["capabilities"]["cli_dataset_download"] = "--dataset" in help_text
        except Exception:
            runtime["capabilities"]["cli_dataset_download"] = False

    version_tuple = parse_version(str(runtime["modelscope_version"]))
    if version_tuple < parse_version(MIN_COMPATIBLE_VERSION):
        runtime["notes"].append(
            f"Current modelscope version {runtime['modelscope_version']} is below tested minimum "
            f"{MIN_COMPATIBLE_VERSION}. Some capabilities may be unavailable."
        )
    if version_tuple < parse_version(RECOMMENDED_MODELSCOPE_VERSION):
        runtime["notes"].append(
            f"Recommended version is {RECOMMENDED_MODELSCOPE_VERSION} for best compatibility."
        )
    return runtime


def resolve_token(token_arg: Optional[str]) -> Optional[str]:
    if token_arg and token_arg.strip():
        return token_arg.strip()
    env_token = os.getenv("MODELSCOPE_API_TOKEN", "").strip()
    return env_token or None


def run_model_search(args: argparse.Namespace, runtime: Dict[str, Any]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    notes: List[str] = list(runtime["notes"])
    token = resolve_token(args.token)
    hub_api = runtime["HubApi"]()

    sdk_failed = None
    if runtime["capabilities"]["model_search"] and args.owner:
        try:
            raw = call_with_supported_kwargs(
                hub_api.list_models,
                {
                    "owner_or_group": args.owner or "",
                    "page_number": args.page,
                    "page_size": args.size,
                    "token": token,
                    "endpoint": runtime["endpoint"],
                },
            )
            items = [normalize_model_item(item) for item in ensure_list(raw)]
        except Exception as exc:
            sdk_failed = str(exc)
    elif not args.owner:
        notes.append("No owner provided. Using OpenAPI global model search path.")

    if not items:
        try:
            openapi_data = request_openapi(
                endpoint=runtime["endpoint"],
                path="/openapi/v1/models",
                params={
                    "page_number": args.page,
                    "page_size": args.size,
                    "search": args.query or None,
                    "author": args.owner or None,
                },
                token=token,
            )
            items = [normalize_model_item(item) for item in ensure_list(openapi_data)]
            notes.append("Model search used OpenAPI fallback.")
            if sdk_failed:
                notes.append(f"SDK search fallback reason: {sdk_failed}")
        except Exception as exc:
            if sdk_failed:
                raise MSHubError(
                    code="model_search_failed",
                    message="Model search failed in both SDK and OpenAPI paths.",
                    next_step="Provide --owner or check network/endpoint and retry.",
                    details={"sdk_error": sdk_failed, "openapi_error": str(exc)},
                ) from exc
            raise

    results = filter_and_rank(items, args.query or "", args.top)
    return {
        "ok": True,
        "command": "model search",
        "query": {
            "keyword": args.query or "",
            "owner": args.owner or "",
            "page": args.page,
            "size": args.size,
            "top": args.top,
        },
        "count": len(results),
        "results": results,
        "runtime": {
            "modelscope_version": runtime["modelscope_version"],
            "recommended_version": RECOMMENDED_MODELSCOPE_VERSION,
            "minimum_tested_version": MIN_COMPATIBLE_VERSION,
            "capabilities": runtime["capabilities"],
        },
        "notes": notes,
    }


def run_dataset_search(args: argparse.Namespace, runtime: Dict[str, Any]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    notes: List[str] = list(runtime["notes"])
    token = resolve_token(args.token)
    hub_api = runtime["HubApi"]()

    sdk_failed = None
    if runtime["capabilities"]["dataset_search"]:
        try:
            raw = call_with_supported_kwargs(
                hub_api.list_datasets,
                {
                    "owner_or_group": args.owner or "",
                    "page_number": args.page,
                    "page_size": args.size,
                    "search": args.query or None,
                    "token": token,
                    "endpoint": runtime["endpoint"],
                },
            )
            items = [normalize_dataset_item(item) for item in ensure_list(raw)]
        except Exception as exc:
            sdk_failed = str(exc)

    if not items:
        openapi_data = request_openapi(
            endpoint=runtime["endpoint"],
            path="/openapi/v1/datasets",
            params={
                "page_number": args.page,
                "page_size": args.size,
                "search": args.query or None,
                "author": args.owner or None,
            },
            token=token,
        )
        items = [normalize_dataset_item(item) for item in ensure_list(openapi_data)]
        notes.append("Dataset search used OpenAPI fallback.")
        if sdk_failed:
            notes.append(f"SDK search fallback reason: {sdk_failed}")

    results = filter_and_rank(items, args.query or "", args.top)
    return {
        "ok": True,
        "command": "dataset search",
        "query": {
            "keyword": args.query or "",
            "owner": args.owner or "",
            "page": args.page,
            "size": args.size,
            "top": args.top,
        },
        "count": len(results),
        "results": results,
        "runtime": {
            "modelscope_version": runtime["modelscope_version"],
            "recommended_version": RECOMMENDED_MODELSCOPE_VERSION,
            "minimum_tested_version": MIN_COMPATIBLE_VERSION,
            "capabilities": runtime["capabilities"],
        },
        "notes": notes,
    }


def run_model_download(args: argparse.Namespace, runtime: Dict[str, Any]) -> Dict[str, Any]:
    # Validate format early for clearer error reporting.
    split_repo_id(args.repo_id)
    token = resolve_token(args.token)
    local_dir = make_local_dir("model", args.repo_id, args.local_dir)
    include_patterns = compile_patterns(args.include)
    exclude_patterns = compile_patterns(args.exclude)
    notes: List[str] = list(runtime["notes"])
    revision = args.revision or DEFAULT_REVISION

    # Lightweight compatibility path: when filters are set, download matched files one by one.
    # This avoids pulling full model weights in older SDKs that ignore pattern arguments.
    if (include_patterns or exclude_patterns) and runtime.get("model_file_download_fn"):
        hub_api = runtime["HubApi"]()
        try:
            model_files = call_with_supported_kwargs(
                hub_api.get_model_files,
                {"model_id": args.repo_id, "revision": revision},
            )
            selected: List[str] = []
            for entry in model_files if isinstance(model_files, list) else []:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("Type", "")).lower() != "blob":
                    continue
                path = str(pick_value(entry, ("Path", "Name"), ""))
                if not path:
                    continue
                if path_selected(path, include_patterns, exclude_patterns):
                    selected.append(path)

            if not selected:
                raise MSHubError(
                    code="model_no_files_selected",
                    message="No model files matched the selected include/exclude patterns.",
                    next_step="Adjust --include/--exclude patterns and retry.",
                    details={"repo_id": args.repo_id},
                )

            downloader = runtime["model_file_download_fn"]
            downloaded_files: List[str] = []
            for file_path in selected:
                call_with_supported_kwargs(
                    downloader,
                    {
                        "model_id": args.repo_id,
                        "file_path": file_path,
                        "revision": revision,
                        "cache_dir": str(local_dir),
                    },
                )
                downloaded_files.append(file_path)

            notes.append("Model download used lightweight file-level compatibility path.")
            return {
                "ok": True,
                "command": "model download",
                "repo_id": args.repo_id,
                "revision": revision,
                "local_dir": str(local_dir.resolve()),
                "download_path": str(local_dir.resolve()),
                "file_count": len(downloaded_files),
                "method": "legacy_model_file_download",
                "runtime": {
                    "modelscope_version": runtime["modelscope_version"],
                    "recommended_version": RECOMMENDED_MODELSCOPE_VERSION,
                    "minimum_tested_version": MIN_COMPATIBLE_VERSION,
                    "capabilities": runtime["capabilities"],
                },
                "notes": notes,
            }
        except Exception as exc:
            notes.append(f"File-level model download path failed: {exc}")

    sdk_error = None
    model_fn = runtime.get("snapshot_model_fn")
    if callable(model_fn):
        try:
            call_kwargs = {
                "model_id": args.repo_id,
                "revision": revision,
                "local_dir": str(local_dir),
                "cache_dir": str(local_dir),
                "allow_file_pattern": include_patterns or None,
                "ignore_file_pattern": exclude_patterns or None,
                "token": token,
            }
            target_path = call_with_supported_kwargs(model_fn, call_kwargs)
            return {
                "ok": True,
                "command": "model download",
                "repo_id": args.repo_id,
                "revision": revision,
                "local_dir": str(local_dir.resolve()),
                "download_path": str(Path(str(target_path or local_dir)).resolve()),
                "method": "sdk_snapshot_download",
                "runtime": {
                    "modelscope_version": runtime["modelscope_version"],
                    "recommended_version": RECOMMENDED_MODELSCOPE_VERSION,
                    "minimum_tested_version": MIN_COMPATIBLE_VERSION,
                    "capabilities": runtime["capabilities"],
                },
                "notes": notes,
            }
        except Exception as exc:
            sdk_error = str(exc)

    if runtime["capabilities"]["cli_download"]:
        candidates: List[List[str]] = []
        modern_cmd = ["modelscope", "download", "--model", args.repo_id]
        if args.revision:
            modern_cmd += ["--revision", args.revision]
        modern_cmd += ["--local_dir", str(local_dir)]
        if include_patterns:
            modern_cmd += ["--include", *include_patterns]
        if exclude_patterns:
            modern_cmd += ["--exclude", *exclude_patterns]
        candidates.append(modern_cmd)

        legacy_cmd = ["modelscope", "download", args.repo_id]
        if args.revision:
            legacy_cmd += ["--revision", args.revision]
        legacy_cmd += ["--cache_dir", str(local_dir)]
        candidates.append(legacy_cmd)

        cli_error = None
        for cmd in candidates:
            try:
                completed = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3600,
                )
                if completed.returncode == 0:
                    notes.append("Model download used CLI fallback.")
                    if sdk_error:
                        notes.append(f"SDK fallback reason: {sdk_error}")
                    return {
                        "ok": True,
                        "command": "model download",
                        "repo_id": args.repo_id,
                        "revision": revision,
                        "local_dir": str(local_dir.resolve()),
                        "download_path": str(local_dir.resolve()),
                        "method": "cli_download",
                        "runtime": {
                            "modelscope_version": runtime["modelscope_version"],
                            "recommended_version": RECOMMENDED_MODELSCOPE_VERSION,
                            "minimum_tested_version": MIN_COMPATIBLE_VERSION,
                            "capabilities": runtime["capabilities"],
                        },
                        "notes": notes,
                    }
                cli_error = (completed.stderr or completed.stdout).strip()[:1000]
            except Exception as exc:
                cli_error = str(exc)

        raise MSHubError(
            code="model_download_failed",
            message="Model download failed in both SDK and CLI paths.",
            next_step="Check repo_id/network permissions, then retry. If problem persists, use recommended modelscope version.",
            details={"sdk_error": sdk_error, "cli_error": cli_error},
        )

    raise MSHubError(
        code="model_download_unavailable",
        message="Model download capability is unavailable in current environment.",
        next_step="Install modelscope CLI or upgrade to recommended version.",
        details={"sdk_error": sdk_error},
    )

def dataset_repo_file_url(endpoint: str, owner: str, name: str, revision: str, path: str) -> str:
    encoded_path = quote(path, safe="/")
    return (
        f"{normalize_endpoint(endpoint)}/api/v1/datasets/{owner}/{name}/repo"
        f"?Revision={quote(revision)}&FilePath={encoded_path}"
    )


def model_repo_file_url(endpoint: str, repo_id: str, revision: str, path: str) -> str:
    encoded_path = quote(path, safe="/")
    return (
        f"{normalize_endpoint(endpoint)}/api/v1/models/{repo_id}/repo"
        f"?Revision={quote(revision)}&FilePath={encoded_path}"
    )


def download_file_with_requests(
    url: str,
    destination: Path,
    token: Optional[str],
    cookies: Optional[Any] = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request_kwargs: Dict[str, Any] = {
        "url": url,
        "timeout": REQUEST_TIMEOUT,
        "stream": True,
    }
    headers = build_openapi_headers(token)
    if headers:
        request_kwargs["headers"] = headers
    if cookies is not None:
        request_kwargs["cookies"] = cookies
    response = requests.get(**request_kwargs)
    if response.status_code >= 400:
        raise MSHubError(
            code="dataset_file_download_failed",
            message=f"Failed to download file from repo: HTTP {response.status_code}",
            next_step="Check visibility/token and retry.",
            details={"url": url, "status_code": response.status_code},
        )
    with destination.open("wb") as output:
        for chunk in response.iter_content(chunk_size=1024 * 128):
            if chunk:
                output.write(chunk)


def fetch_readme_content(
    entity: str,
    repo_id: str,
    revision: str,
    endpoint: str,
    token: Optional[str],
) -> Dict[str, Any]:
    candidate_paths = ["README.md", "readme.md", "README.MD"]
    for readme_path in candidate_paths:
        if entity == "model":
            url = model_repo_file_url(endpoint, repo_id, revision, readme_path)
        else:
            owner, name = split_repo_id(repo_id)
            url = dataset_repo_file_url(endpoint, owner, name, revision, readme_path)
        response = requests.get(
            url,
            headers=build_openapi_headers(token),
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 200:
            content_type = response.headers.get("content-type", "")
            text = response.text if "text" in content_type or "markdown" in content_type or "octet-stream" in content_type else response.content.decode("utf-8", errors="ignore")
            return {
                "ok": True,
                "path": readme_path,
                "content": text,
                "content_preview": text[:2000],
                "content_length": len(text),
            }
    return {
        "ok": False,
        "path": None,
        "content": "",
        "content_preview": "",
        "content_length": 0,
        "error": "README.md not found or inaccessible",
    }


def run_dataset_download(args: argparse.Namespace, runtime: Dict[str, Any]) -> Dict[str, Any]:
    token = resolve_token(args.token)
    local_dir = make_local_dir("dataset", args.repo_id, args.local_dir)
    include_patterns = compile_patterns(args.include)
    exclude_patterns = compile_patterns(args.exclude)
    notes: List[str] = list(runtime["notes"])
    revision = args.revision or DEFAULT_REVISION
    owner, name = split_repo_id(args.repo_id)

    dataset_fn = runtime.get("snapshot_dataset_fn")
    if callable(dataset_fn):
        try:
            call_kwargs = {
                "dataset_id": args.repo_id,
                "revision": revision,
                "local_dir": str(local_dir),
                "cache_dir": str(local_dir),
                "allow_file_pattern": include_patterns or None,
                "ignore_file_pattern": exclude_patterns or None,
                "token": token,
            }
            target_path = call_with_supported_kwargs(dataset_fn, call_kwargs)
            return {
                "ok": True,
                "command": "dataset download",
                "repo_id": args.repo_id,
                "revision": revision,
                "local_dir": str(local_dir.resolve()),
                "download_path": str(Path(str(target_path or local_dir)).resolve()),
                "method": "sdk_dataset_snapshot_download",
                "runtime": {
                    "modelscope_version": runtime["modelscope_version"],
                    "recommended_version": RECOMMENDED_MODELSCOPE_VERSION,
                    "minimum_tested_version": MIN_COMPATIBLE_VERSION,
                    "capabilities": runtime["capabilities"],
                },
                "notes": notes,
            }
        except Exception as exc:
            notes.append(f"SDK dataset snapshot path failed: {exc}")

    hub_api = runtime["HubApi"]()
    cookies = None

    legacy_error = None
    try:
        dataset_id, _dataset_type = call_with_supported_kwargs(
            hub_api.get_dataset_id_and_type,
            {"dataset_name": name, "namespace": owner},
        )
        file_entries = call_with_supported_kwargs(
            hub_api.get_dataset_meta_file_list,
            {
                "dataset_name": name,
                "namespace": owner,
                "dataset_id": dataset_id,
                "revision": revision,
            },
        )
        if not isinstance(file_entries, list):
            raise MSHubError(
                code="dataset_meta_unexpected",
                message="Dataset file list response is not a list.",
                next_step="Retry with a public dataset or upgrade modelscope.",
                details={"repo_id": args.repo_id},
            )

        downloaded_files: List[str] = []
        for entry in file_entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("Type", "")).lower() != "blob":
                continue
            path = str(pick_value(entry, ("Path", "Name"), ""))
            if not path:
                continue
            if not path_selected(path, include_patterns, exclude_patterns):
                continue
            url = dataset_repo_file_url(runtime["endpoint"], owner, name, revision, path)
            destination = local_dir / path
            download_file_with_requests(url, destination, token=token, cookies=cookies)
            downloaded_files.append(path)

        if not downloaded_files:
            raise MSHubError(
                code="dataset_no_files_selected",
                message="No dataset files matched the selected include/exclude patterns.",
                next_step="Adjust --include/--exclude patterns and retry.",
                details={"repo_id": args.repo_id},
            )

        notes.append("Dataset download used legacy file-list compatibility path.")
        return {
            "ok": True,
            "command": "dataset download",
            "repo_id": args.repo_id,
            "revision": revision,
            "local_dir": str(local_dir.resolve()),
            "download_path": str(local_dir.resolve()),
            "file_count": len(downloaded_files),
            "method": "legacy_file_list_download",
            "runtime": {
                "modelscope_version": runtime["modelscope_version"],
                "recommended_version": RECOMMENDED_MODELSCOPE_VERSION,
                "minimum_tested_version": MIN_COMPATIBLE_VERSION,
                "capabilities": runtime["capabilities"],
            },
            "notes": notes,
        }
    except Exception as exc:
        legacy_error = str(exc)

    if runtime["capabilities"]["cli_dataset_download"]:
        cmd = ["modelscope", "download", "--dataset", args.repo_id, "--local_dir", str(local_dir)]
        if args.revision:
            cmd += ["--revision", args.revision]
        if include_patterns:
            cmd += ["--include", *include_patterns]
        if exclude_patterns:
            cmd += ["--exclude", *exclude_patterns]
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if completed.returncode == 0:
            notes.append("Dataset download used CLI fallback.")
            return {
                "ok": True,
                "command": "dataset download",
                "repo_id": args.repo_id,
                "revision": revision,
                "local_dir": str(local_dir.resolve()),
                "download_path": str(local_dir.resolve()),
                "method": "cli_download",
                "runtime": {
                    "modelscope_version": runtime["modelscope_version"],
                    "recommended_version": RECOMMENDED_MODELSCOPE_VERSION,
                    "minimum_tested_version": MIN_COMPATIBLE_VERSION,
                    "capabilities": runtime["capabilities"],
                },
                "notes": notes,
            }
        cli_error = (completed.stderr or completed.stdout).strip()[:1000]
    else:
        cli_error = "CLI dataset download is unavailable in current modelscope CLI."

    if (
        not token
        and isinstance(legacy_error, str)
        and "dict' object has no attribute 'request'" in legacy_error
    ):
        raise MSHubError(
            code="dataset_auth_or_visibility_error",
            message="Dataset may be gated/private or require authentication in current environment.",
            next_step="Set MODELSCOPE_API_TOKEN (or --token) and retry, or choose a public dataset.",
            details={"legacy_error": legacy_error, "cli_error": cli_error},
        )

    raise MSHubError(
        code="dataset_download_failed",
        message="Dataset download failed in available compatibility paths.",
        next_step=(
            "Check repo_id/network/token. If issue persists, upgrade modelscope to "
            f"{RECOMMENDED_MODELSCOPE_VERSION}."
        ),
        details={"legacy_error": legacy_error, "cli_error": cli_error},
    )


def search_with_readme(
    query: str,
    *,
    entity: str = "model",
    top: int = DEFAULT_TOP_N,
    owner: str = "",
    page: int = 1,
    size: int = 20,
    revision: str = DEFAULT_REVISION,
    endpoint: str = DEFAULT_ENDPOINT,
    token: Optional[str] = None,
    include_readme: bool = True,
) -> Dict[str, Any]:
    if entity not in ("model", "dataset"):
        raise ValueError("entity must be 'model' or 'dataset'")

    runtime = detect_runtime(endpoint)
    args = argparse.Namespace(
        entity=entity,
        action="search",
        query=query,
        owner=owner,
        page=page,
        size=size,
        top=top,
        revision=revision,
        endpoint=endpoint,
        token=token,
        include=None,
        exclude=None,
        local_dir=None,
        with_readme=include_readme,
    )
    payload = run_model_search(args, runtime) if entity == "model" else run_dataset_search(args, runtime)

    if include_readme and payload.get("ok"):
        resolved_token = resolve_token(token)
        for item in payload.get("results", []):
            repo_id = item.get("repo_id")
            if not repo_id:
                item["homepage"] = {"ok": False, "error": "Missing repo_id"}
                continue
            item["homepage"] = fetch_readme_content(
                entity=entity,
                repo_id=repo_id,
                revision=revision,
                endpoint=endpoint,
                token=resolved_token,
            )
    return payload

def render_text(payload: Dict[str, Any]) -> None:
    if payload.get("ok") is not True:
        error = payload.get("error", {})
        print(f"[ERROR] {error.get('code', 'unknown_error')}: {error.get('message', '')}")
        next_step = error.get("next_step")
        if next_step:
            print(f"Next step: {next_step}")
        details = error.get("details")
        if details:
            print(f"Details: {details}")
        return

    command = payload.get("command", "")
    print(f"[OK] {command}")
    notes = payload.get("notes") or []
    for note in notes:
        print(f"- note: {note}")

    if "search" in command:
        results = payload.get("results", [])
        print(f"Returned {payload.get('count', 0)} result(s).")
        for index, item in enumerate(results, start=1):
            print(
                f"{index}. {item.get('repo_id', '')} | {item.get('name', '')} "
                f"| downloads={item.get('downloads')} | likes={item.get('likes')} "
                f"| updated={item.get('updated_at', '')}"
            )
            homepage = item.get("homepage")
            if isinstance(homepage, dict) and homepage.get("ok"):
                print(f"   homepage: {homepage.get('path')} ({homepage.get('content_length')} chars)")
    elif "download" in command:
        print(f"- repo_id: {payload.get('repo_id')}")
        print(f"- revision: {payload.get('revision')}")
        print(f"- local_dir: {payload.get('local_dir')}")
        print(f"- method: {payload.get('method')}")
        if payload.get("file_count") is not None:
            print(f"- file_count: {payload.get('file_count')}")


def emit(payload: Dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        render_text(payload)


def parser_builder() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mshub.py",
        description=(
            "ModelScope lightweight helper (V1): model search, dataset search, "
            "model download, dataset download."
        ),
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help="ModelScope endpoint. Defaults to https://www.modelscope.cn",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional access token. Falls back to MODELSCOPE_API_TOKEN.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output for programmatic consumption.",
    )

    entity_subparsers = parser.add_subparsers(dest="entity", required=True)
    for entity in ("model", "dataset"):
        entity_parser = entity_subparsers.add_parser(entity)
        action_subparsers = entity_parser.add_subparsers(dest="action", required=True)

        search_parser = action_subparsers.add_parser("search", help=f"Search {entity} repositories.")
        search_parser.add_argument("-q", "--query", default="", help="Keyword query.")
        search_parser.add_argument("--owner", default="", help="Optional owner or org filter.")
        search_parser.add_argument("--page", type=int, default=1, help="Page number.")
        search_parser.add_argument("--size", type=int, default=20, help="Page size.")
        search_parser.add_argument("--top", type=int, default=DEFAULT_TOP_N, help="Top N output rows.")
        search_parser.add_argument(
            "--with-readme",
            action="store_true",
            help="Fetch README.md content for returned repositories.",
        )

        download_parser = action_subparsers.add_parser(
            "download", help=f"Download a {entity} repository snapshot."
        )
        download_parser.add_argument("--repo-id", required=True, help="Repository id, e.g. owner/name.")
        download_parser.add_argument(
            "--revision",
            default=DEFAULT_REVISION,
            help="Repository revision/branch/tag. Defaults to master.",
        )
        download_parser.add_argument(
            "--local-dir",
            default=None,
            help="Destination directory. Defaults to ./downloads/<entity>/<owner--name>.",
        )
        download_parser.add_argument(
            "--include",
            nargs="*",
            default=None,
            help="Optional glob patterns to include.",
        )
        download_parser.add_argument(
            "--exclude",
            nargs="*",
            default=None,
            help="Optional glob patterns to exclude.",
        )
    return parser


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    runtime = detect_runtime(args.endpoint)
    if args.entity == "model" and args.action == "search":
        payload = run_model_search(args, runtime)
    elif args.entity == "dataset" and args.action == "search":
        payload = run_dataset_search(args, runtime)
    elif args.entity == "model" and args.action == "download":
        payload = run_model_download(args, runtime)
    elif args.entity == "dataset" and args.action == "download":
        payload = run_dataset_download(args, runtime)
    else:
        raise MSHubError(
            code="unsupported_command",
            message=f"Unsupported command: {args.entity} {args.action}",
            next_step="Run mshub.py --help to list supported commands.",
        )

    if getattr(args, "with_readme", False) and payload.get("ok") and "search" in payload.get("command", ""):
        token = resolve_token(args.token)
        for item in payload.get("results", []):
            repo_id = item.get("repo_id")
            if not repo_id:
                item["homepage"] = {"ok": False, "error": "Missing repo_id"}
                continue
            item["homepage"] = fetch_readme_content(
                entity=args.entity,
                repo_id=repo_id,
                revision=args.revision if hasattr(args, "revision") else DEFAULT_REVISION,
                endpoint=args.endpoint,
                token=token,
            )
    return payload


def main() -> int:
    parser = parser_builder()
    raw_argv = sys.argv[1:]
    json_anywhere = "--json" in raw_argv
    if json_anywhere:
        raw_argv = [arg for arg in raw_argv if arg != "--json"]
    args = parser.parse_args(raw_argv)
    if json_anywhere:
        args.json = True
    try:
        payload = execute(args)
        emit(payload, json_output=args.json)
        return 0
    except MSHubError as exc:
        payload = {
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "next_step": exc.next_step,
                "details": exc.details,
            },
        }
        emit(payload, json_output=args.json)
        return 1
    except KeyboardInterrupt:
        payload = {
            "ok": False,
            "error": {
                "code": "interrupted",
                "message": "Interrupted by user.",
                "next_step": "Run the command again when ready.",
                "details": {},
            },
        }
        emit(payload, json_output=args.json)
        return 130
    except Exception as exc:
        payload = {
            "ok": False,
            "error": {
                "code": "unexpected_error",
                "message": str(exc),
                "next_step": "Re-run with --json and inspect details. If needed, upgrade modelscope.",
                "details": {"exception_type": type(exc).__name__},
            },
        }
        emit(payload, json_output=args.json)
        return 1


if __name__ == "__main__":
    sys.exit(main())
