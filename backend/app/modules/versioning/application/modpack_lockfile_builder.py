"""``base_overrides`` CAS storage and Lockfile Format 2.1 assembly (P5.5).

Class-B override blobs (``<= 1 MiB``) live in the CAS and are referenced by
``lockfile.base_overrides``. Class-A overrides and ``1..16 MiB`` Class-B
overrides live in the CAS and appear in ``lockfile.files[]``. The builder fails
closed while any manual CurseForge download remains unresolved.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Set

from app.core.allowlist import classify, validate_canonical_relpath
from app.core.exceptions import (
    ManualDownloadRequiredError,
    ModpackFormatError,
    OversizedGitTrackedFileError,
    ValidationError,
)
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LecRef,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    ModpackRef,
    Origin,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.download_allowlist import (
    VerifiedDownloadResult,
)
from app.modules.versioning.infrastructure.modpack_parser import (
    MAX_CLASS_B_FILE_BYTES,
    InstallPlan,
)

_OVERRIDE_CAS_CLASSIFICATIONS = frozenset({"A-JAR", "A-CAS", "B-ROUTED-CAS"})


def store_base_overrides_in_cas(
    cas: ArtifactCas,
    class_b_blobs: Mapping[str, bytes],
) -> dict[str, str]:
    """Validate and store Class-B blobs, returning ``{relpath: sha256}``."""
    stored: dict[str, str] = {}
    for relpath, blob in class_b_blobs.items():
        try:
            validate_canonical_relpath(relpath)
        except ValueError as exc:
            raise ModpackFormatError(
                f"Invalid base_overrides path: {relpath[:128]!r}",
                field="base_overrides",
            ) from exc
        if classify(relpath) != "B":
            raise ModpackFormatError(
                f"base_overrides path is not Class-B: {relpath[:128]!r}",
                field="base_overrides",
            )
        if len(blob) > MAX_CLASS_B_FILE_BYTES:
            raise OversizedGitTrackedFileError(
                relpath, len(blob), MAX_CLASS_B_FILE_BYTES
            )
        stored[relpath] = cas.put_bytes(blob)
    return dict(sorted(stored.items()))


def build_lockfile_from_install_plan(
    plan: InstallPlan,
    *,
    cas: ArtifactCas,
    downloaded_files: Mapping[str, VerifiedDownloadResult],
    override_blobs: Mapping[str, bytes],
    lec_key: str | None = None,
) -> LockfileV21:
    """Assemble a deterministic, validated Format 2.1 lockfile from a plan."""
    if plan.has_unresolved_blockers:
        blocker = next(b for b in plan.manual_blockers if not b.resolved)
        raise ManualDownloadRequiredError(
            filename=blocker.filename,
            webpage_url=blocker.webpage_url,
            expected_size=blocker.expected_size,
            expected_sha1=blocker.expected_sha1,
            expected_sha512=blocker.expected_sha512,
            project_id=blocker.project_id,
            file_id=blocker.file_id,
        )

    class_b_blobs: dict[str, bytes] = {}
    for override in plan.overrides:
        if override.classification != "B":
            continue
        blob = override_blobs.get(override.path)
        if blob is None:
            raise ValidationError(
                f"Missing Class-B override blob: {override.path[:128]!r}",
                field="overrides",
            )
        class_b_blobs[override.path] = blob
    base_overrides = store_base_overrides_in_cas(cas, class_b_blobs)

    files: list[LockfileFile] = []
    for plan_file in plan.files:
        verified = downloaded_files.get(plan_file.path)
        if verified is not None:
            sha256 = verified.sha256
            sha512 = verified.sha512
            sha1 = verified.sha1
            size = verified.size
        elif plan_file.sha256 is not None:
            sha256 = plan_file.sha256
            sha512 = plan_file.sha512
            sha1 = plan_file.sha1
            size = plan_file.size
        else:
            raise ValidationError(
                f"Missing verified download for '{plan_file.path[:128]}'",
                field="files",
            )
        if not cas.has(sha256):
            raise ValidationError(
                f"Verified file is missing from the CAS: {plan_file.path[:128]!r}",
                field="files",
            )
        files.append(
            LockfileFile(
                path=plan_file.path,
                sha256=sha256,
                size=size,
                optional=bool(plan_file.optional),
                env_server=EnvServer(plan_file.env_server),
                origin=plan_file.origin,
                sha512=sha512,
                sha1=sha1,
                project_id=plan_file.project_id,
                version_id=plan_file.version_id,
            )
        )

    for override in plan.overrides:
        if override.classification not in _OVERRIDE_CAS_CLASSIFICATIONS:
            continue
        blob = override_blobs.get(override.path)
        if blob is None:
            raise ValidationError(
                f"Missing override blob: {override.path[:128]!r}",
                field="overrides",
            )
        sha256 = cas.put_bytes(blob)
        files.append(
            LockfileFile(
                path=override.path,
                sha256=sha256,
                size=len(blob),
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.OVERRIDE,
                sha512=hashlib.sha512(blob).hexdigest(),
                sha1=hashlib.sha1(blob).hexdigest(),
                project_id=None,
                version_id=None,
            )
        )

    files.sort(key=lambda entry: entry.path)
    seen: dict[str, str] = {}
    for entry in files:
        casefold_path = entry.path.casefold()
        previous = seen.get(casefold_path)
        if previous is not None:
            raise ModpackFormatError(
                f"Duplicate path in install plan: {entry.path[:128]!r}",
                field="files",
            )
        seen[casefold_path] = entry.path

    modpack = ModpackRef(
        source=plan.source,
        project_id=plan.project_id,
        version_id=plan.version_id,
        version_label=plan.version_label,
        index_sha256=plan.index_sha256,
    )
    lec = LecRef(key=lec_key) if lec_key is not None else None
    return LockfileV21(
        format=2,
        mc=plan.mc_version,
        loader=LoaderRef(id=plan.loader_id, version=plan.loader_version),
        base_overrides=base_overrides,
        files=tuple(files),
        lec=lec,
        modpack=modpack,
    )


def advance_base_overrides_per_file(
    current_base_overrides: Mapping[str, str],
    target_base_overrides: Mapping[str, str],
    *,
    resolved_paths: Set[str],
    removed_paths: Set[str] = frozenset(),
) -> dict[str, str]:
    """Advance only cleanly resolved paths (OD-v8.7-9)."""
    advanced: dict[str, str] = {}
    for path, sha256 in current_base_overrides.items():
        if path in removed_paths:
            continue
        if path in resolved_paths:
            target = target_base_overrides.get(path)
            if target is not None:
                advanced[path] = target
            continue
        advanced[path] = sha256
    for path in resolved_paths:
        if path in removed_paths or path in advanced:
            continue
        target = target_base_overrides.get(path)
        if target is not None:
            advanced[path] = target
    return dict(sorted(advanced.items()))


__all__ = [
    "advance_base_overrides_per_file",
    "build_lockfile_from_install_plan",
    "store_base_overrides_in_cas",
]
