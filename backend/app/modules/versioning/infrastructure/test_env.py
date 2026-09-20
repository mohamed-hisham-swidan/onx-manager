from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import AppSettings
from app.modules.server.infrastructure.providers.docker import resolve_docker_image
from app.modules.versioning.infrastructure.compatibility import (
    StrategyResult,
    VerificationMode,
)

logger = logging.getLogger(__name__)


def resolve_test_docker_image(
    minecraft_version: str | None = None,
    strategy: StrategyResult | None = None,
) -> tuple[str, StrategyResult]:
    """Resolve the container image and effective strategy for isolated test execution.

    Pins to AppSettings.docker_test_image (itzg image digest) when strategy
    driver is 'fakeplayer_next'. If docker_test_image is unset/empty, it does
    NOT fall back to a raw JRE image under fakeplayer_next; instead it downgrades
    to SMOKE_TEST with reason 'itzg image not configured'.
    For all other strategies (e.g. vanilla, forge, smoke_test, mineflayer),
    preserves exact existing JRE image resolution via resolve_docker_image.
    """
    if strategy is not None and strategy.driver == "fakeplayer_next":
        settings = AppSettings()
        if settings.docker_test_image:
            return settings.docker_test_image, strategy

        downgraded = StrategyResult(
            mode=VerificationMode.SMOKE_TEST,
            driver="smoke_test",
            reason="itzg image not configured",
            downgraded_from="fakeplayer_next",
            artifact_ok=False,
        )
        fallback_img = resolve_docker_image(minecraft_version=minecraft_version)
        return fallback_img, downgraded

    effective_strat = strategy or StrategyResult(
        mode=VerificationMode.SMOKE_TEST,
        driver="smoke_test",
        reason="default strategy",
        downgraded_from=None,
        artifact_ok=False,
    )
    return resolve_docker_image(minecraft_version=minecraft_version), effective_strat


def build_test_container_env(
    server_type: str,
    minecraft_version: str | None,
    strategy: StrategyResult,
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build container environment variables for isolated test execution.

    Follows live-path defaulting pattern (docker.py:395-410).
    When strategy is fakeplayer_next:
    - Sets MODRINTH_PROJECTS=commandapi (itzg auto-resolves version-compatible CommandAPI jar)
    - Sets ENABLE_RCON=true, RCON_PORT=25575
    NOTE: RCON_PASSWORD is intentionally omitted here. In accordance with
    Fix B1 (Option b), the password is passed via process environment inheritance
    and docker run '-e RCON_PASSWORD' without argv value exposure.
    """
    env: dict[str, str] = {
        "EULA": "TRUE",
        "ONLINE_MODE": "FALSE",
    }
    if server_type:
        env["TYPE"] = server_type.upper()
    if minecraft_version:
        env["VERSION"] = str(minecraft_version)

    if strategy.driver == "fakeplayer_next":
        env["MODRINTH_PROJECTS"] = "commandapi"
        env["ENABLE_RCON"] = "true"
        env["RCON_PORT"] = "25575"

    if extra_env:
        env.update(extra_env)

    return env


def clean_test_plugins_dir(test_dir: Path) -> None:
    """Ensure <test_dir>/plugins/ exists and contains no stale or conflicting plugin jars.

    Strictly contained within test_dir to prevent directory traversal or symlink escapes.
    Preserves real user plugins under test; removes only:
    - Conflicting CommandAPI jars (itzg auto-stages CommandAPI; duplicate causes ambiguous name)
    - Download artifacts (*.part)
    - Jars with 'stale' in filename
    - Duplicate fakeplayer-*.jar copies (keeps exactly one)
    """
    # Reject directory traversal patterns
    if ".." in test_dir.parts:
        logger.warning("Directory traversal rejected in clean_test_plugins_dir: %s", test_dir)
        return

    test_dir_resolved = test_dir.resolve()
    plugins = test_dir / "plugins"

    # Refuse if plugins directory itself is a symlink
    if plugins.is_symlink():
        logger.warning("plugins directory is a symlink, skipping cleanup: %s", plugins)
        return

    if not plugins.exists():
        plugins.mkdir(parents=True, exist_ok=True)
        return

    plugins_resolved = plugins.resolve()

    # Containment assertions
    if not plugins_resolved.is_relative_to(test_dir_resolved):
        logger.warning(
            "plugins directory escapes test root: %s not in %s",
            plugins_resolved,
            test_dir_resolved,
        )
        return

    if plugins_resolved.parent != test_dir_resolved:
        logger.warning(
            "plugins directory is not a direct child of test root: %s",
            plugins_resolved,
        )
        return

    # 1. Match and remove *.part files (separate glob)
    for part_file in plugins.glob("*.part"):
        if part_file.is_symlink():
            continue
        try:
            part_file.unlink()
            logger.debug("Removed stale download part file: %s", part_file.name)
        except OSError as e:
            logger.warning("Failed removing %s: %s", part_file.name, e)

    # 2. Match *.jar files
    for jar in plugins.glob("*.jar"):
        if jar.is_symlink():
            continue
        name_lower = jar.name.lower()
        if name_lower.startswith("commandapi"):
            try:
                jar.unlink()
                logger.debug("Removed conflicting CommandAPI jar: %s", jar.name)
            except OSError as e:
                logger.warning("Failed removing %s: %s", jar.name, e)
            continue

        if "stale" in name_lower:
            try:
                jar.unlink()
                logger.debug("Removed stale plugin jar: %s", jar.name)
            except OSError as e:
                logger.warning("Failed removing %s: %s", jar.name, e)
            continue

    # 3. Deduplicate fakeplayer jars (keep exactly one fakeplayer-*.jar)
    fp_jars = [j for j in plugins.glob("fakeplayer*.jar") if not j.is_symlink()]
    if len(fp_jars) > 1:
        fp_jars.sort(key=lambda p: p.name, reverse=True)
        for dup in fp_jars[1:]:
            try:
                dup.unlink()
                logger.debug("Removed duplicate fakeplayer jar: %s", dup.name)
            except OSError as e:
                logger.warning("Failed removing duplicate fakeplayer jar %s: %s", dup.name, e)
