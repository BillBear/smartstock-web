"""Runtime metadata helpers for local validation and future cloud deploys."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Dict, Any, Optional


def resolve_git_commit(repo_root: Optional[Path] = None) -> str:
    """Return current git commit when available; never raise during startup."""
    root = repo_root or Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(root),
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def build_runtime_metadata(settings: Any, git_commit_getter: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    """Build a secret-safe version payload shared by health and deployment checks."""
    getter = git_commit_getter or resolve_git_commit
    configured_commit = str(getattr(settings, "GIT_COMMIT", "") or "").strip()
    git_commit = configured_commit or str(getter() or "").strip()
    token = str(getattr(settings, "TUSHARE_TOKEN", "") or "")
    return {
        "app_name": getattr(settings, "APP_NAME", "SmartStock AI"),
        "app_env": getattr(settings, "APP_ENV", "local"),
        "app_version": getattr(settings, "APP_VERSION", ""),
        "git_commit": git_commit,
        "api_prefix": getattr(settings, "API_PREFIX", "/api"),
        "mock_fallback_enabled": bool(getattr(settings, "ENABLE_MOCK_FALLBACK", False)),
        "use_mock_data": bool(getattr(settings, "USE_MOCK_DATA", False)),
        "tushare_configured": bool(token),
    }
