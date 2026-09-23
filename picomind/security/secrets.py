"""Detection rules for workspace files that may contain credentials."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

_ALLOWED_ENV_EXAMPLES = {".env.example", ".env.sample", ".env.template"}
_SENSITIVE_DIRECTORIES = {
    ".aws",
    ".azure",
    ".gnupg",
    ".kube",
    ".secrets",
    ".ssh",
}
_SENSITIVE_PATTERNS = (
    "*.key",
    "*.p12",
    "*.pem",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    "credentials",
    "credentials.*",
    "secret*.json",
    "secret*.toml",
    "secret*.txt",
    "secret*.yaml",
    "secret*.yml",
    "*secret*.json",
    "*secret*.toml",
    "*secret*.txt",
    "*secret*.yaml",
    "*secret*.yml",
    "*api*key*.json",
    "*api*key*.toml",
    "*api*key*.txt",
    "*api*key*.yaml",
    "*api*key*.yml",
    "api_key*",
    "apikey*",
    "deepseek api.txt",
)


def is_sensitive_path(value: str | Path) -> bool:
    """Return True when a path name strongly indicates credential material."""

    path = Path(str(value).strip().strip("\"'"))
    parts = {part.casefold() for part in path.parts}
    if parts & _SENSITIVE_DIRECTORIES:
        return True
    name = path.name.casefold()
    if not name:
        return False
    if name.startswith(".env") and name not in _ALLOWED_ENV_EXAMPLES:
        return True
    if name == "config.toml" and ".picomind" in parts:
        return True
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in _SENSITIVE_PATTERNS)


def is_sensitive_directory(value: str | Path) -> bool:
    return Path(str(value).strip().strip("\"'")).name.casefold() in _SENSITIVE_DIRECTORIES


def find_sensitive_reference(command: str) -> str | None:
    """Best-effort detection of sensitive file references in a shell command."""

    lowered = command.casefold()
    if "deepseek api.txt" in lowered:
        return "deepseek api.txt"
    tokens = _COMMAND_TOKEN_RE.findall(command)
    for pattern in ("*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*"):
        for token in tokens:
            if fnmatch.fnmatchcase(token.casefold(), pattern):
                return token
    for token in tokens:
        candidates = [token]
        if "=" in token:
            candidates.extend(part for part in token.split("=", 1) if part)
        for candidate in candidates:
            cleaned = candidate.strip("()[]{},")
            if is_sensitive_path(cleaned) or is_sensitive_directory(cleaned):
                return candidate
    return None


_COMMAND_TOKEN_RE = re.compile(r"[^\s\"'<>|&;]+")
