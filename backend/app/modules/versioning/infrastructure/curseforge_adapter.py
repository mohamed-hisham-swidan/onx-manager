"""CurseForge ``manifest.json`` adapter and manual-upload unblocker (P5.5).

The adapter reuses the ``.mrpack`` quarantine/override rules. CurseForge file
metadata is fetched exclusively from the official API; CDN ``401``/``403`` and
``downloadUrl: null`` become explicit manual-download blockers instead of
silent skips.
"""

from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import aiohttp

from app.core.allowlist import validate_canonical_relpath
from app.core.exceptions import (
    CaseCollisionError,
    CorruptedDownloadError,
    CurseForgeApiKeyMissingError,
    DownloadError,
    ModpackFormatError,
    NotFoundError,
    ValidationError,
)
from app.core.http_client import get_http_client
from app.modules.plugin.infrastructure.providers.modrinth import ModrinthProvider
from app.modules.shared.value_objects import MinecraftVersion
from app.modules.versioning.domain.lockfile import EnvServer, Origin
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.download_allowlist import (
    VerifiedDownloadResult,
    download_verified_to_cas,
    validate_download_url,
)
from app.modules.versioning.infrastructure.modpack_parser import (
    MAX_CLASS_B_ROUTED_BYTES,
    MAX_INDEX_BYTES,
    InstallPlan,
    InstallPlanFile,
    InstallPlanOverride,
    ManualDownloadBlocker,
    _member_is_dir,
    classify_and_validate_target_path,
    read_zip_member_bounded,
    replace_plan,
    validate_archive_quarantine,
    validate_forge_mc_version,
)

logger = logging.getLogger(__name__)

CURSEFORGE_API_BASE = "https://api.curseforge.com/v1"
CURSEFORGE_BATCH_CHUNK_SIZE = 200
_CF_LOADER_PREFIXES = (
    ("neoforge-", "neoforge"),
    ("forge-", "forge"),
    ("fabric-", "fabric"),
    ("quilt-", "quilt"),
)
_HEX_SHA1_CHARS = frozenset("0123456789abcdefABCDEF")


def _chunks(values: Sequence[int], size: int) -> list[list[int]]:
    return [list(values[index : index + size]) for index in range(0, len(values), size)]


def _is_sha1(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(ch in _HEX_SHA1_CHARS for ch in value)
    )


def _manifest_dict(manifest_bytes: bytes) -> dict[str, object]:
    try:
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModpackFormatError(
            "manifest.json is not valid UTF-8 JSON",
            field="manifest.json",
        ) from exc
    if not isinstance(payload, dict):
        raise ModpackFormatError(
            "manifest.json must be a JSON object",
            field="manifest.json",
        )
    return payload


def _parse_loader(manifest: dict[str, object]) -> tuple[MinecraftVersion, str, str]:
    minecraft = manifest.get("minecraft")
    if not isinstance(minecraft, dict):
        raise ModpackFormatError(
            "manifest.json is missing the minecraft object",
            field="minecraft",
        )
    raw_version = minecraft.get("version")
    try:
        mc_version = MinecraftVersion.parse(
            raw_version if isinstance(raw_version, str) else ""
        )
    except ValueError as exc:
        raise ModpackFormatError(
            "manifest.json has an invalid Minecraft version",
            field="minecraft.version",
        ) from exc

    raw_loaders = minecraft.get("modLoaders")
    if not isinstance(raw_loaders, list):
        raise ModpackFormatError(
            "manifest.json is missing minecraft.modLoaders",
            field="minecraft.modLoaders",
        )

    candidates: list[tuple[str, str, bool]] = []
    for item in raw_loaders:
        if not isinstance(item, dict):
            raise ModpackFormatError(
                "minecraft.modLoaders entries must be objects",
                field="minecraft.modLoaders",
            )
        loader_ref = item.get("id")
        if not isinstance(loader_ref, str) or not loader_ref:
            raise ModpackFormatError(
                "minecraft.modLoaders entry is missing a loader id",
                field="minecraft.modLoaders",
            )
        for prefix, loader_id in _CF_LOADER_PREFIXES:
            if loader_ref.startswith(prefix):
                candidates.append(
                    (
                        loader_id,
                        loader_ref[len(prefix) :],
                        bool(item.get("primary", False)),
                    )
                )
                break

    distinct = {loader for loader, _version, _primary in candidates}
    if len(distinct) != 1:
        raise ModpackFormatError(
            "CurseForge pack must declare exactly one loader",
            field="minecraft.modLoaders",
        )
    loader_id = next(iter(distinct))
    preferred = next(
        (version for loader, version, primary in candidates if loader == loader_id and primary),
        None,
    )
    loader_version = preferred or next(
        version for loader, version, _primary in candidates if loader == loader_id
    )
    if not loader_version:
        raise ModpackFormatError(
            "CurseForge pack has an empty loader version",
            field="minecraft.modLoaders",
        )
    if loader_id == "forge":
        validate_forge_mc_version(str(raw_version))
    return mc_version, loader_id, loader_version


def _parse_overrides_prefix(manifest: dict[str, object]) -> str:
    raw = manifest.get("overrides", "overrides")
    if not isinstance(raw, str) or not raw:
        raise ModpackFormatError(
            "manifest.json has an invalid overrides directory",
            field="overrides",
        )
    prefix = raw[:-1] if raw.endswith("/") else raw
    try:
        validate_canonical_relpath(prefix)
    except ValueError as exc:
        raise ModpackFormatError(
            "manifest.json has an invalid overrides directory",
            field="overrides",
        ) from exc
    return prefix


def _parse_manifest_files(
    manifest: dict[str, object],
) -> list[tuple[int, int, bool]]:
    raw_files = manifest.get("files", [])
    if not isinstance(raw_files, list):
        raise ModpackFormatError("manifest.json files must be a list", field="files")
    parsed: list[tuple[int, int, bool]] = []
    for entry in raw_files:
        if not isinstance(entry, dict):
            raise ModpackFormatError(
                "manifest.json file entries must be objects",
                field="files",
            )
        project_id = entry.get("projectID")
        file_id = entry.get("fileID")
        if type(project_id) is not int or project_id <= 0:
            raise ModpackFormatError(
                "manifest.json file entry has an invalid projectID",
                field="files.projectID",
            )
        if type(file_id) is not int or file_id <= 0:
            raise ModpackFormatError(
                "manifest.json file entry has an invalid fileID",
                field="files.fileID",
            )
        required = entry.get("required", True)
        if not isinstance(required, bool):
            raise ModpackFormatError(
                "manifest.json file entry has an invalid required flag",
                field="files.required",
            )
        parsed.append((project_id, file_id, required))
    return parsed


def _sha1_from_hashes(meta: dict[str, object]) -> str:
    hashes = meta.get("hashes")
    if not isinstance(hashes, list):
        raise ModpackFormatError(
            "CurseForge file metadata is missing hashes",
            field="curseforge.hashes",
        )
    for item in hashes:
        if isinstance(item, dict) and item.get("algo") == 1:
            value = item.get("value")
            if _is_sha1(value):
                return str(value).lower()
            raise ModpackFormatError(
                "CurseForge file metadata has an invalid SHA-1",
                field="curseforge.hashes",
            )
    raise ModpackFormatError(
        "CurseForge file metadata is missing the SHA-1 hash",
        field="curseforge.hashes",
    )


async def _fetch_file_metadata(
    api_key: str,
    file_ids: Sequence[int],
    *,
    client: aiohttp.ClientSession,
) -> dict[int, dict[str, object]]:
    endpoint = f"{CURSEFORGE_API_BASE}/mods/files"
    metadata: dict[int, dict[str, object]] = {}
    for chunk in _chunks(list(dict.fromkeys(file_ids)), CURSEFORGE_BATCH_CHUNK_SIZE):
        try:
            async with client.post(
                endpoint,
                headers={"x-api-key": api_key, "Accept": "application/json"},
                json={"fileIds": chunk},
                allow_redirects=False,
            ) as resp:
                status = int(resp.status)
                if status in (401, 403):
                    raise CurseForgeApiKeyMissingError(
                        "CurseForge API key was rejected"
                    )
                if status != 200:
                    raise DownloadError(endpoint, status)
                try:
                    payload = await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as exc:
                    raise ModpackFormatError(
                        "CurseForge API returned invalid JSON",
                        field="curseforge.response",
                    ) from exc
        except (CurseForgeApiKeyMissingError, DownloadError, ModpackFormatError):
            raise
        except (aiohttp.ClientError, OSError, TimeoutError) as exc:
            raise DownloadError(endpoint, 0, str(exc)[:200]) from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ModpackFormatError(
                "CurseForge API response is missing data",
                field="curseforge.response",
            )
        for item in payload["data"]:
            if isinstance(item, dict) and type(item.get("id")) is int:
                metadata[int(item["id"])] = item
    return metadata


def _curseforge_file_fields(
    meta: dict[str, object],
) -> tuple[str, int, str]:
    raw_name = meta.get("fileName")
    if not isinstance(raw_name, str) or not raw_name or "/" in raw_name:
        raise ModpackFormatError(
            "CurseForge file metadata has an invalid fileName",
            field="curseforge.fileName",
        )
    file_length = meta.get("fileLength")
    if type(file_length) is not int or file_length < 0:
        raise ModpackFormatError(
            "CurseForge file metadata has an invalid fileLength",
            field="curseforge.fileLength",
        )
    sha1 = _sha1_from_hashes(meta)
    return raw_name, file_length, sha1


def _load_override_members(
    infos: Sequence[zipfile.ZipInfo],
    overrides_prefix: str,
) -> dict[str, tuple[zipfile.ZipInfo, str]]:
    prefix = f"{overrides_prefix}/"
    effective: dict[str, tuple[zipfile.ZipInfo, str]] = {}
    by_casefold: dict[str, str] = {}

    for info in infos:
        if _member_is_dir(info):
            continue
        name = info.filename
        if not name.startswith(prefix):
            continue
        relpath = name[len(prefix) :]
        if not relpath:
            continue
        casefold_path = relpath.casefold()
        previous = by_casefold.get(casefold_path)
        if previous is not None:
            raise CaseCollisionError(
                "Casefold collision between override members",
                path_a=previous,
                path_b=relpath,
            )
        effective[relpath] = (info, "curseforge-overrides")
        by_casefold[casefold_path] = relpath
    return effective


async def parse_curseforge_zip(
    archive_path: str | Path,
    *,
    api_key: str | None,
    install_optional_server_files: bool = True,
    extra_allowed_hosts: Iterable[str] = (),
    modrinth_client: ModrinthProvider | None = None,
    cf_http_client: aiohttp.ClientSession | None = None,
    project_id: str = "local",
    version_id: str = "local",
) -> tuple[InstallPlan, dict[str, bytes]]:
    """Parse a CurseForge modpack ZIP into the shared ``InstallPlan`` shape."""
    if not api_key or not api_key.strip():
        raise CurseForgeApiKeyMissingError()

    path = Path(archive_path)
    try:
        zf = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ModpackFormatError(
            f"Not a valid modpack ZIP archive: {path.name[:128]!r}",
            field="archive",
        ) from exc

    with zf:
        infos = validate_archive_quarantine(zf)
        manifest_info = next(
            (info for info in infos if info.filename == "manifest.json"),
            None,
        )
        if manifest_info is None:
            raise ModpackFormatError(
                "CurseForge archive is missing manifest.json",
                field="manifest.json",
            )
        manifest_bytes = read_zip_member_bounded(
            zf, manifest_info, max_bytes=MAX_INDEX_BYTES
        )
        index_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        manifest = _manifest_dict(manifest_bytes)
        mc_version, loader_id, loader_version = _parse_loader(manifest)
        overrides_prefix = _parse_overrides_prefix(manifest)
        manifest_files = _parse_manifest_files(manifest)

        session = cf_http_client or get_http_client()
        metadata = await _fetch_file_metadata(
            api_key.strip(),
            [file_id for _project_id, file_id, _required in manifest_files],
            client=session,
        )

        plan_files: list[InstallPlanFile] = []
        blockers: list[ManualDownloadBlocker] = []
        skipped_optional: list[str] = []
        discarded_paths: list[str] = []
        warnings: list[str] = []
        seen_paths: dict[str, str] = {}

        for cf_project_id, file_id, required in manifest_files:
            meta = metadata.get(file_id)
            if meta is None:
                raise ModpackFormatError(
                    f"CurseForge file metadata is missing for fileID {file_id}",
                    field="curseforge.response",
                )
            raw_name, file_length, sha1 = _curseforge_file_fields(meta)
            target_path = f"mods/{raw_name}"
            if not required and not install_optional_server_files:
                skipped_optional.append(target_path)
                continue
            classification = classify_and_validate_target_path(target_path, file_length)
            if classification in ("DISCARD", "SKIP"):
                discarded_paths.append(target_path)
                if classification == "SKIP":
                    warnings.append(f"skipped_path:{target_path}")
                continue
            casefold_path = target_path.casefold()
            previous = seen_paths.get(casefold_path)
            if previous is not None:
                if previous == target_path:
                    raise ModpackFormatError(
                        f"Duplicate CurseForge file path: {target_path[:128]!r}",
                        field="curseforge.files",
                    )
                raise CaseCollisionError(
                    "Casefold collision between CurseForge files",
                    path_a=previous,
                    path_b=target_path,
                )
            seen_paths[casefold_path] = target_path

            download_url = meta.get("downloadUrl")
            if not isinstance(download_url, str) or not download_url:
                blockers.append(
                    ManualDownloadBlocker(
                        path=target_path,
                        filename=raw_name,
                        project_id=cf_project_id,
                        file_id=file_id,
                        webpage_url=(
                            f"https://www.curseforge.com/projects/{cf_project_id}"
                            f"/files/{file_id}"
                        ),
                        expected_size=file_length,
                        expected_sha1=sha1,
                        required=required,
                        reason="download_url_null",
                    )
                )
                continue
            validate_download_url(
                download_url, extra_allowed_hosts=extra_allowed_hosts
            )
            plan_files.append(
                InstallPlanFile(
                    path=target_path,
                    sha1=sha1,
                    size=file_length,
                    downloads=(download_url,),
                    env_server=(
                        EnvServer.REQUIRED.value
                        if required
                        else EnvServer.OPTIONAL.value
                    ),
                    optional=not required,
                    origin=Origin.CURSEFORGE_UNCLASSIFIED,
                    source_layer="curseforge",
                    curseforge_project_id=cf_project_id,
                    curseforge_file_id=file_id,
                )
            )

        effective = _load_override_members(infos, overrides_prefix)
        index_by_casefold = {f.path.casefold(): f.path for f in plan_files}
        removed_paths: set[str] = set()
        for relpath in effective:
            index_path = index_by_casefold.get(relpath.casefold())
            if index_path is None:
                continue
            if index_path != relpath:
                raise CaseCollisionError(
                    "Casefold collision between CurseForge files and overrides",
                    path_a=index_path,
                    path_b=relpath,
                )
            removed_paths.add(index_path)
        if removed_paths:
            plan_files = [f for f in plan_files if f.path not in removed_paths]
            for removed in sorted(removed_paths):
                warnings.append(f"override_supersedes_curseforge_file:{removed}")

        override_members: list[tuple[str, object, str, bytes]] = []
        override_jar_digests: dict[str, str] = {}
        for relpath in sorted(effective):
            info, layer = effective[relpath]
            classification = classify_and_validate_target_path(
                relpath, info.file_size  # type: ignore[attr-defined]
            )
            if classification in ("DISCARD", "SKIP"):
                discarded_paths.append(relpath)
                if classification == "SKIP":
                    warnings.append(f"skipped_path:{relpath}")
                continue
            max_bytes = (
                MAX_CLASS_B_ROUTED_BYTES
                if classification in ("B", "B-ROUTED-CAS")
                else None
            )
            data = read_zip_member_bounded(
                zf,
                info,  # type: ignore[arg-type]
                max_bytes=max_bytes,
            )
            if classification in ("A-JAR", "A-CAS", "B-ROUTED-CAS", "B"):
                digest = hashlib.sha512(data).hexdigest()
                override_members.append((relpath, info, layer, data))
                if relpath.lower().startswith(("mods/", "plugins/")) and relpath.lower().endswith(
                    ".jar"
                ):
                    override_jar_digests[digest] = relpath

        client_only_hashes: set[str] = set()
        matched_versions: Mapping[str, object] = {}
        if override_jar_digests:
            client = modrinth_client or ModrinthProvider()
            (
                client_only_hashes,
                matched_versions,
                _matched_projects,
            ) = await client.classify_client_only_jars_by_sha512(
                sorted(override_jar_digests)
            )

        overrides: list[InstallPlanOverride] = []
        override_blobs: dict[str, bytes] = {}
        skipped_client_override_jars: list[str] = []
        for relpath, info, layer, data in override_members:
            digest = hashlib.sha512(data).hexdigest()
            if digest in client_only_hashes:
                skipped_client_override_jars.append(relpath)
                logger.info("skipped_client_override_jar path=%s", relpath)
                continue
            overrides.append(
                InstallPlanOverride(
                    path=relpath,
                    archive_path=info.filename,  # type: ignore[attr-defined]
                    source_layer=layer,
                    classification=classify_and_validate_target_path(
                        relpath, len(data)
                    ),
                    sha256=hashlib.sha256(data).hexdigest(),
                    sha512=digest,
                    sha1=hashlib.sha1(data).hexdigest(),
                    size=len(data),
                )
            )
            override_blobs[relpath] = data

        raw_name = manifest.get("name")
        version_label = (
            str(raw_name).strip()[:256]
            if isinstance(raw_name, str) and raw_name.strip()
            else f"{project_id}:{version_id}"
        )
        plan = InstallPlan(
            source="curseforge",
            project_id=project_id,
            version_id=version_id,
            version_label=version_label,
            index_sha256=index_sha256,
            mc_version=str(mc_version),
            loader_id=loader_id,
            loader_version=loader_version,
            files=tuple(sorted(plan_files, key=lambda f: f.path)),
            overrides=tuple(sorted(overrides, key=lambda o: o.path)),
            manual_blockers=tuple(
                sorted(blockers, key=lambda b: (b.path, b.file_id or -1))
            ),
            skipped_optional_files=tuple(sorted(skipped_optional)),
            skipped_client_override_jars=tuple(sorted(skipped_client_override_jars)),
            discarded_paths=tuple(sorted(set(discarded_paths))),
            warnings=tuple(warnings),
        )
        return plan, override_blobs


async def download_curseforge_plan_files(
    plan: InstallPlan,
    cas: ArtifactCas,
    *,
    extra_allowed_hosts: Iterable[str] = (),
    modrinth_client: ModrinthProvider | None = None,
    http_client: aiohttp.ClientSession | None = None,
) -> tuple[InstallPlan, dict[str, VerifiedDownloadResult]]:
    """Download every plan file, converting CDN 401/403 into manual blockers."""
    downloaded: dict[str, VerifiedDownloadResult] = {}
    kept_files: list[InstallPlanFile] = []
    new_blockers: list[ManualDownloadBlocker] = []
    warnings = list(plan.warnings)

    for plan_file in plan.files:
        if not plan_file.downloads:
            kept_files.append(plan_file)
            continue
        try:
            result = await download_verified_to_cas(
                plan_file.downloads[0],
                cas,
                expected_size=plan_file.size,
                expected_sha1=plan_file.sha1,
                extra_allowed_hosts=extra_allowed_hosts,
                client=http_client,
            )
        except DownloadError as exc:
            if exc.status in (401, 403):
                new_blockers.append(
                    ManualDownloadBlocker(
                        path=plan_file.path,
                        filename=plan_file.path.rsplit("/", 1)[-1],
                        project_id=plan_file.curseforge_project_id,
                        file_id=plan_file.curseforge_file_id,
                        webpage_url=(
                            f"https://www.curseforge.com/projects/"
                            f"{plan_file.curseforge_project_id}/files/"
                            f"{plan_file.curseforge_file_id}"
                            if plan_file.curseforge_project_id is not None
                            and plan_file.curseforge_file_id is not None
                            else ""
                        ),
                        expected_size=plan_file.size,
                        expected_sha1=plan_file.sha1,
                        expected_sha512=plan_file.sha512,
                        required=not plan_file.optional,
                        reason=f"cdn_http_{exc.status}",
                    )
                )
                warnings.append(
                    f"manual_download_required:{plan_file.path}:cdn_http_{exc.status}"
                )
                continue
            raise
        downloaded[plan_file.path] = result
        kept_files.append(
            replace(
                plan_file,
                sha512=result.sha512,
                sha256=result.sha256,
                size=result.size,
            )
        )

    client_only_hashes: set[str] = set()
    matched_versions: Mapping[str, object] = {}
    if downloaded:
        client = modrinth_client or ModrinthProvider()
        (
            client_only_hashes,
            matched_versions,
            _matched_projects,
        ) = await client.classify_client_only_jars_by_sha512(
            [result.sha512 for result in downloaded.values()]
        )

    final_files: list[InstallPlanFile] = []
    skipped_client: list[str] = list(plan.skipped_client_files)
    skipped_override_jars: list[str] = list(plan.skipped_client_override_jars)
    for plan_file in kept_files:
        if not plan_file.downloads:
            final_files.append(plan_file)
            continue
        result = downloaded.get(plan_file.path)
        if result is None:
            continue
        if result.sha512 in client_only_hashes:
            if plan_file.path not in skipped_client:
                skipped_client.append(plan_file.path)
            if plan_file.path not in skipped_override_jars:
                skipped_override_jars.append(plan_file.path)
            warning = f"skipped_client_override_jar:{plan_file.path}"
            if warning not in warnings:
                warnings.append(warning)
            logger.info("skipped_client_override_jar path=%s", plan_file.path)
            continue
        record = matched_versions.get(result.sha512)
        if record is not None:
            project_id = getattr(record, "project_id", None)
            version_id = getattr(record, "version_id", None)
            final_files.append(
                replace(
                    plan_file,
                    origin=Origin.CURSEFORGE,
                    project_id=str(project_id) if project_id else None,
                    version_id=str(version_id) if version_id else None,
                )
            )
        else:
            final_files.append(
                replace(
                    plan_file,
                    origin=Origin.CURSEFORGE_UNCLASSIFIED,
                    project_id=None,
                    version_id=None,
                )
            )

    blockers = list(plan.manual_blockers) + new_blockers
    return (
        replace_plan(
            plan,
            files=final_files,
            manual_blockers=blockers,
            skipped_client_files=skipped_client,
            skipped_client_override_jars=skipped_override_jars,
            warnings=warnings,
        ),
        downloaded,
    )


async def resolve_manual_download_upload(
    plan: InstallPlan,
    *,
    file_id: int | None = None,
    path: str | None = None,
    data: bytes,
    cas: ArtifactCas,
    modrinth_client: ModrinthProvider | None = None,
) -> tuple[InstallPlan, VerifiedDownloadResult | None]:
    """Verify an operator upload, store it in CAS, and clear the blocker."""
    if file_id is None and not path:
        raise ValidationError(
            "Provide either file_id or path for the manual upload",
            field="file_id",
        )
    blocker_index: int | None = None
    for index, blocker in enumerate(plan.manual_blockers):
        if blocker.resolved:
            continue
        if file_id is not None and blocker.file_id == file_id:
            blocker_index = index
            break
        if file_id is None and path is not None and blocker.path == path:
            blocker_index = index
            break
    if blocker_index is None:
        raise NotFoundError("Matching manual download blocker not found")

    blocker = plan.manual_blockers[blocker_index]
    if not isinstance(data, (bytes, bytearray)):
        raise ValidationError("Uploaded file must be bytes", field="data")
    payload = bytes(data)
    if blocker.expected_size is not None and len(payload) != blocker.expected_size:
        raise CorruptedDownloadError(
            blocker.path,
            f"size mismatch: expected {blocker.expected_size}, got {len(payload)}",
        )
    sha1 = hashlib.sha1(payload).hexdigest()
    sha512 = hashlib.sha512(payload).hexdigest()
    sha256 = hashlib.sha256(payload).hexdigest()
    if blocker.expected_sha1 is not None and sha1 != blocker.expected_sha1.lower():
        raise CorruptedDownloadError(blocker.path, "sha1 mismatch")
    if blocker.expected_sha512 is not None and sha512 != blocker.expected_sha512.lower():
        raise CorruptedDownloadError(blocker.path, "sha512 mismatch")

    matched_version = None
    if modrinth_client is not None:
        (
            client_only_hashes,
            matched_versions,
            _matched_projects,
        ) = await modrinth_client.classify_client_only_jars_by_sha512([sha512])
        if sha512 in client_only_hashes:
            resolved = replace(
                blocker,
                resolved=True,
                resolved_sha256=sha256,
            )
            blockers = list(plan.manual_blockers)
            blockers[blocker_index] = resolved
            skipped_client = list(plan.skipped_client_files)
            if blocker.path not in skipped_client:
                skipped_client.append(blocker.path)
            skipped_override_jars = list(plan.skipped_client_override_jars)
            if blocker.path not in skipped_override_jars:
                skipped_override_jars.append(blocker.path)
            warnings = list(plan.warnings)
            warning = f"skipped_client_override_jar:{blocker.path}"
            if warning not in warnings:
                warnings.append(warning)
            logger.info("skipped_client_override_jar path=%s", blocker.path)
            return (
                replace_plan(
                    plan,
                    manual_blockers=blockers,
                    skipped_client_files=skipped_client,
                    skipped_client_override_jars=skipped_override_jars,
                    warnings=warnings,
                ),
                None,
            )
        matched_version = matched_versions.get(sha512)

    digest = cas.put_bytes(payload)
    if digest != sha256:
        raise CorruptedDownloadError(blocker.path, "CAS digest mismatch")

    if matched_version is not None:
        origin = Origin.CURSEFORGE
        project_id = getattr(matched_version, "project_id", None) or None
        version_id = getattr(matched_version, "version_id", None) or None
    else:
        origin = Origin.CURSEFORGE_UNCLASSIFIED
        project_id = None
        version_id = None

    resolved = replace(blocker, resolved=True, resolved_sha256=sha256)
    blockers = list(plan.manual_blockers)
    blockers[blocker_index] = resolved
    new_file = InstallPlanFile(
        path=blocker.path,
        sha1=sha1,
        size=len(payload),
        downloads=(),
        sha512=sha512,
        sha256=sha256,
        env_server=(
            EnvServer.REQUIRED.value
            if blocker.required
            else EnvServer.OPTIONAL.value
        ),
        optional=not blocker.required,
        origin=origin,
        project_id=str(project_id) if project_id else None,
        version_id=str(version_id) if version_id else None,
        source_layer="curseforge-manual",
        curseforge_project_id=blocker.project_id,
        curseforge_file_id=blocker.file_id,
    )
    files = [f for f in plan.files if f.path != blocker.path] + [new_file]
    updated = replace_plan(plan, files=files, manual_blockers=blockers)
    return (
        updated,
        VerifiedDownloadResult(
            sha256=sha256,
            sha512=sha512,
            sha1=sha1,
            size=len(payload),
            final_url="manual-upload",
            redirect_count=0,
        ),
    )


__all__ = [
    "CURSEFORGE_API_BASE",
    "CURSEFORGE_BATCH_CHUNK_SIZE",
    "download_curseforge_plan_files",
    "parse_curseforge_zip",
    "resolve_manual_download_upload",
]
