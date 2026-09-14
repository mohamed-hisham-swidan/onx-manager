from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.health.domain.value_objects import EvidenceBundle
from app.modules.health.infrastructure.crash_analyzer import PatternCrashAnalyzer
from app.modules.server.domain.diagnostics import FailureCode

pytestmark = pytest.mark.asyncio


def _make_bundle(
    log_lines: list[str] | None = None,
    crash_reports: list[dict] | None = None,
    provider_diagnostics: dict | None = None,
) -> EvidenceBundle:
    return EvidenceBundle(
        server_id="srv-1",
        evidence_id=uuid.uuid4().hex,
        latest_log_tail=log_lines or [],
        crash_reports=crash_reports or [],
        provider_diagnostics=provider_diagnostics,
        timestamp=datetime.now(UTC),
    )


class TestPatternCrashAnalyzer:
    async def test_classify_oom_from_log_line(self):
        bundle = _make_bundle(log_lines=["java.lang.OutOfMemoryError: Java heap space"])
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.MEMORY_EXHAUSTED.value
        assert result.confidence >= 0.9

    async def test_classify_port_conflict(self):
        bundle = _make_bundle(log_lines=["Port already in use: 25565"])
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.PORT_CONFLICT.value
        assert result.confidence >= 0.9

    async def test_classify_java_version_mismatch(self):
        bundle = _make_bundle(log_lines=["UnsupportedClassVersionError: major.minor version"])
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.JAVA_VERSION_MISMATCH.value
        assert result.confidence >= 0.9

    async def test_classify_paper_launcher_java_version_requirement(self):
        bundle = _make_bundle(
            log_lines=[
                "Minecraft 26.1 and newer requires running the server with Java 25 or above.",
            ],
        )
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.JAVA_VERSION_MISMATCH.value
        assert result.confidence >= 0.9

    async def test_classify_invalid_jar_path(self):
        bundle = _make_bundle(log_lines=["Unable to access jarfile server.jar"])
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.INVALID_JAR_PATH.value
        assert result.confidence >= 0.9

    async def test_classify_memory_config_error(self):
        bundle = _make_bundle(log_lines=["Could not reserve enough space"])
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.MEMORY_CONFIGURATION_ERROR.value
        assert result.confidence >= 0.9

    async def test_classify_crash_report_oom(self):
        bundle = _make_bundle(
            crash_reports=[
                {
                    "filename": "crash.txt",
                    "content": "java.lang.OutOfMemoryError\n\tat net.minecraft.server.Main.main",
                }
            ],
        )
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.MEMORY_EXHAUSTED.value

    async def test_classify_via_exit_code_137(self):
        bundle = _make_bundle(
            log_lines=["Killed"],
            provider_diagnostics={"exit_code": 137},
        )
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.MEMORY_EXHAUSTED.value
        assert result.confidence >= 0.8

    async def test_classify_via_exit_code_1(self):
        bundle = _make_bundle(
            provider_diagnostics={"exit_code": 1},
        )
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.UNKNOWN_RUNTIME_FAILURE.value

    async def test_classify_via_provider_diag(self):
        bundle = _make_bundle(
            provider_diagnostics={"failure_code": "TMUX_SESSION_LOST"},
        )
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.TMUX_SESSION_LOST.value
        assert result.confidence == 0.7

    async def test_classify_unknown_no_data(self):
        bundle = _make_bundle()
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.UNKNOWN_RUNTIME_FAILURE.value
        assert result.confidence == 0.2

    async def test_classify_with_failure_reason(self):
        bundle = _make_bundle(
            provider_diagnostics={"failure_reason": "Process was killed by SIGKILL"},
        )
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.UNKNOWN_RUNTIME_FAILURE.value
        assert result.confidence == 0.4
        assert "SIGKILL" in result.summary

    async def test_classify_with_last_log_line(self):
        bundle = _make_bundle(log_lines=["[Server thread/INFO] Done shutting down"])
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.UNKNOWN_RUNTIME_FAILURE.value
        assert "Done shutting down" in result.summary

    async def test_suggested_action_for_memory_exhausted(self):
        bundle = _make_bundle(log_lines=["OutOfMemoryError"])
        result = await PatternCrashAnalyzer().classify(bundle)
        assert "Increase -Xmx" in result.suggested_action

    async def test_suggested_action_for_port_conflict(self):
        bundle = _make_bundle(log_lines=["Port already in use"])
        result = await PatternCrashAnalyzer().classify(bundle)
        assert "Change server-port" in result.suggested_action

    async def test_suggested_action_for_java_version(self):
        bundle = _make_bundle(log_lines=["UnsupportedClassVersionError"])
        result = await PatternCrashAnalyzer().classify(bundle)
        assert "Install correct Java" in result.suggested_action

    async def test_classify_net_bind_failure(self):
        bundle = _make_bundle(log_lines=["Failed to bind to port", "BindException"])
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.NETWORK_BIND_FAILURE.value

    async def test_classify_permission_error(self):
        bundle = _make_bundle(log_lines=["Permission denied"])
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.PERMISSION_ERROR.value

    async def test_forge_mod_loading_exception_blames_mod(self):
        crash_text = (
            "---- Minecraft Crash Report ----\n"
            "// Who set us up the TNT?\n"
            "Time: 2026-09-14 01:00:00 UTC\n"
            "Description: Mod loading error\n"
            "\n"
            "net.minecraftforge.fml.ModLoadingException: Mod ironchest (id ironchest) "
            "encountered an error during the common_setup event phase\n"
            "\tat net.minecraftforge.fml.javafmlmod.FMLModContainer.acceptEvent"
            "(FMLModContainer.java:124)\n"
            "-- System Details --\n"
            "Details:\n"
            "\tMinecraft Version: 1.20.1\n"
        )
        bundle = _make_bundle(
            log_lines=[],
            crash_reports=[{"content": crash_text}],
        )
        result = await PatternCrashAnalyzer().classify(bundle)
        assert result.failure_code == FailureCode.MOD_CRASH.value

        analyzer = PatternCrashAnalyzer()
        analysis = analyzer.analyze_crash_content(crash_text)
        assert analysis.failure_code == FailureCode.MOD_CRASH
        assert analysis.blamed_mod == "ironchest"
        assert "ironchest" in analysis.suggested_remediation
        assert "ModLoadingException" in analysis.stack_trace_snippet

    async def test_forge_loader_exception_blames_mod(self):
        crash_text = (
            "Time: 2026-09-14 01:00:00\n"
            "cpw.mods.fml.common.LoaderExceptionModCrash: Caught exception from jei (11.6.0.1018)\n"
            "\tat cpw.mods.fml.common.LoadController.transition(LoadController.java:163)\n"
        )
        analyzer = PatternCrashAnalyzer()
        analysis = analyzer.analyze_crash_content(crash_text)
        assert analysis.failure_code == FailureCode.MOD_CRASH
        assert analysis.blamed_mod == "jei"
        assert "jei" in analysis.suggested_remediation

    async def test_fabric_mod_resolution_exception_blames_mod(self):
        crash_text = (
            "net.fabricmc.loader.impl.FormattedException: Some of your mods are incompatible!\n"
            "\t - Mod 'Sodium' (sodium) requires version 0.5.0 or later of mod "
            "'Fabric API' (fabric-api)\n"
            "-- System Details --\n"
        )
        analyzer = PatternCrashAnalyzer()
        analysis = analyzer.analyze_crash_content(crash_text)
        assert analysis.failure_code == FailureCode.MOD_CRASH
        assert analysis.blamed_mod == "sodium"
        assert "sodium" in analysis.suggested_remediation
