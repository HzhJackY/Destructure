"""Local, non-persistent LLM configuration loader. Secrets never enter registry/audit."""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any

def default_config_path(project_root: Path) -> Path:
    return Path(os.environ.get("FMR_LLM_CONFIG") or (Path(project_root) / "config" / "llm_config.yaml"))

def load_local_llm_config(project_root: Path) -> dict[str, Any]:
    path = default_config_path(project_root)
    if not path.exists(): return {}
    text = path.read_text(encoding="utf-8").strip()
    try: return json.loads(text)
    except json.JSONDecodeError: pass
    # Small YAML subset, intentionally enough for a local credential file.
    result: dict[str, Any] = {}; current: dict[str, Any] = result
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"): continue
        if ":" not in line: continue
        key, value = line.strip().split(":", 1); value = value.strip().strip("\"'")
        if value: current[key] = value
    return result

def llm_runtime_settings(project_root: Path) -> dict[str, Any]:
    cfg = load_local_llm_config(project_root)
    api_key = os.environ.get("OPENAI_API_KEY") or cfg.get("api_key") or cfg.get("key")
    return {"provider": os.environ.get("FMR_LLM_PROVIDER") or cfg.get("provider", "openai"), "model": os.environ.get("FMR_LLM_MODEL") or cfg.get("model"), "base_url": os.environ.get("FMR_LLM_BASE_URL") or cfg.get("base_url"), "api_key": api_key}


def build_local_provider(project_root: Path):
    """Build a supported provider from the local file without persisting a key."""
    settings = llm_runtime_settings(project_root)
    from llm_providers import DeepSeekProvider, GeminiProvider
    provider = str(settings["provider"] or "").lower()
    if provider == "deepseek":
        return DeepSeekProvider(model=settings.get("model") or "deepseek-v4-flash", api_key=settings.get("api_key"), base_url=settings.get("base_url") or "https://api.deepseek.com")
    if provider == "gemini":
        return GeminiProvider(model=settings.get("model") or "gemini-3.5-flash", api_key=settings.get("api_key"))
    raise ValueError("当前本地配置仅支持 deepseek 或 gemini；请使用相应兼容端点。")
