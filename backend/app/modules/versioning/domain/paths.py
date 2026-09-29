from __future__ import annotations

from pathlib import Path


def resolve_test_dir(
    server_dir: Path | str,
    test_id: str,
) -> Path:
    """Canonical safe constructor for isolated test staging directories.

    Grounds resolution in the server's authoritative deployment directory
    (e.g. server.deployment.server_dir), enforcing that test artifacts reside strictly under:
        <server_dir>/.onx/tests/<test_id>

    Guarantees separator-safe and prefix-safe path traversal escape prevention.
    """
    if not test_id or not str(test_id).strip():
        raise ValueError("test_id cannot be empty")

    test_id_str = str(test_id).strip()
    has_separator = "/" in test_id_str or "\\" in test_id_str
    if has_separator or ".." in test_id_str or Path(test_id_str).name != test_id_str:
        raise ValueError(
            f"Invalid test_id '{test_id}': path separators and traversal tokens are not allowed"
        )

    if not server_dir or not str(server_dir).strip():
        raise ValueError(
            "server_dir cannot be empty; explicit authoritative deployment directory is required"
        )

    base_dir = (Path(server_dir).resolve() / ".onx" / "tests").resolve()
    target_dir = (base_dir / test_id_str).resolve()

    # Separator-safe and prefix-safe traversal guard
    if not target_dir.is_relative_to(base_dir) or target_dir == base_dir:
        raise ValueError(
            f"Path traversal detected: test dir '{target_dir}' escapes base '{base_dir}'"
        )
    return target_dir
