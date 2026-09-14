from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.identity import IDENTITY
from app.modules.health.domain.services import CrashClassifier
from app.modules.health.domain.value_objects import CrashClassification, EvidenceBundle
from app.modules.server.domain.diagnostics import FailureCode
from app.modules.server.infrastructure.providers.patterns import FAILURE_PATTERNS

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.health.crash_analyzer")

EXIT_CODE_MAP: dict[int, FailureCode] = {
    1: FailureCode.UNKNOWN_RUNTIME_FAILURE,
    137: FailureCode.MEMORY_EXHAUSTED,
    143: FailureCode.MEMORY_EXHAUSTED,
    127: FailureCode.FILE_NOT_FOUND,
    126: FailureCode.PERMISSION_ERROR,
}

EXIT_CODE_KEYWORDS: dict[int, list[str]] = {
    137: ["killed", "out of memory", "oom-killer", "oom"],
    143: ["killed", "sigterm"],
}

FORGE_BLAME_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:net\.(?:minecraftforge|neoforged)\.fml\.)?ModLoadingException:\s*"
        r"Mod\s+(?:§e)?([a-zA-Z0-9_\-\.]+)(?:§r)?\s+"
        r"(?:\(id\s+(?:§e)?([a-zA-Z0-9_\-\.]+)(?:§r)?\))?\s*encountered an error",
        re.IGNORECASE,
    ),
    re.compile(
        r"cpw\.mods\.fml\.common\.LoaderExceptionModCrash:\s*Caught exception from\s+([a-zA-Z0-9_\-\.]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"Multiple exceptions declaring failure for mod\s+([a-zA-Z0-9_\-\.]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"Mod\s+([a-zA-Z0-9_\-\.]+)\s+\([a-zA-Z0-9_\-\.]+\)\s+has failed to load correctly",
        re.IGNORECASE,
    ),
    re.compile(r"Blamed Mod:\s*([a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
]

FABRIC_BLAME_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"Mod\s+'([^']+)'\s+\(([a-zA-Z0-9_\-\.]+)\)\s+requires",
        re.IGNORECASE,
    ),
    re.compile(
        r"Could not find required mod:\s*([a-zA-Z0-9_\-\.]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"Unmet dependency for\s+([a-zA-Z0-9_\-\.]+)",
        re.IGNORECASE,
    ),
]

CRASH_REPORT_PATTERNS: list[tuple[re.Pattern[str], FailureCode, str]] = [
    (
        re.compile(
            r"net\.(?:minecraftforge|neoforged)\.fml\.ModLoadingException"
            r"|cpw\.mods\.fml\.common\.LoaderExceptionModCrash"
            r"|net\.minecraftforge\.fml\.loading\.EarlyLoadingException",
            re.IGNORECASE,
        ),
        FailureCode.MOD_CRASH,
        "Forge ModLoadingException in crash report",
    ),
    (
        re.compile(
            r"net\.fabricmc\.loader\.(?:impl\.)?(?:discovery\.)?ModResolutionException"
            r"|net\.fabricmc\.loader\.impl\.FormattedException"
            r"|Incompatible mod set found",
            re.IGNORECASE,
        ),
        FailureCode.MOD_CRASH,
        "Fabric ModResolutionException in crash report",
    ),
    (
        re.compile(r"java\.lang\.OutOfMemoryError"),
        FailureCode.MEMORY_EXHAUSTED,
        "OutOfMemoryError in crash report",
    ),
    (
        re.compile(
            r"java\.lang\.UnsupportedClassVersionError"
            r"|requires\s+running\s+the\s+server\s+with\s+Java\s+\d+"
            r"|requires\s+Java\s+\d+",
            re.IGNORECASE,
        ),
        FailureCode.JAVA_VERSION_MISMATCH,
        "Java version mismatch in crash report",
    ),
    (
        re.compile(r"java\.lang\.NoSuchMethodError"),
        FailureCode.UNKNOWN_RUNTIME_FAILURE,
        "NoSuchMethodError in crash report",
    ),
    (
        re.compile(r"java\.lang\.StackOverflowError"),
        FailureCode.UNKNOWN_RUNTIME_FAILURE,
        "StackOverflowError in crash report",
    ),
    (
        re.compile(r"Failed to load main class"),
        FailureCode.INVALID_JAR_PATH,
        "Main class not found",
    ),
    (
        re.compile(r"Unable to instantiate"),
        FailureCode.INVALID_LAUNCH_CONFIGURATION,
        "Plugin instantiation failure",
    ),
]


@dataclass(frozen=True)
class CrashReportAnalysis:
    failure_code: FailureCode
    summary: str
    blamed_mod: str | None = None
    stack_trace_snippet: str = ""
    suggested_remediation: str = ""


def extract_stack_trace_snippet(content: str, max_lines: int = 25) -> str:
    """Extract a concise stack trace snippet from raw crash report text."""
    lines = content.splitlines()
    if not lines:
        return ""
    start_idx = 0
    for idx, line in enumerate(lines):
        if any(marker in line for marker in ("Exception:", "Error:", "Time: ", "Description: ")):
            start_idx = idx
            break
    snippet_lines: list[str] = []
    for line in lines[start_idx : start_idx + max_lines]:
        if line.startswith("-- System Details --") or line.startswith("-- Mod List --"):
            break
        snippet_lines.append(line)
    return "\n".join(snippet_lines).strip()


class PatternCrashAnalyzer(CrashClassifier):
    def __init__(self, confidence_threshold: float = 0.0) -> None:
        self._confidence_threshold = confidence_threshold

    async def classify(self, evidence: EvidenceBundle) -> CrashClassification:
        failure_code, confidence, summary = self._analyze(evidence)
        suggested_action = self._suggest_action(failure_code)

        return CrashClassification(
            evidence_id=evidence.evidence_id,
            server_id=evidence.server_id,
            failure_code=failure_code.value,
            confidence=min(confidence, 1.0),
            summary=summary,
            suggested_action=suggested_action,
            timestamp=datetime.now(UTC),
        )

    def _analyze(self, evidence: EvidenceBundle) -> tuple[FailureCode, float, str]:
        log_lines = evidence.latest_log_tail
        crash_reports = evidence.crash_reports
        diag = evidence.provider_diagnostics or {}

        all_error_lines = list(log_lines)
        for report in crash_reports:
            content = report.get("content", "")
            if content:
                all_error_lines.extend(content.splitlines())

        for line in all_error_lines:
            for fp in FAILURE_PATTERNS:
                if fp.pattern.search(line):
                    return fp.failure_code, 0.95, f"Log pattern match: {fp.name}"

        for report in crash_reports:
            content = report.get("content", "")
            for pattern, code, label in CRASH_REPORT_PATTERNS:
                if pattern.search(content):
                    return code, 0.9, label

        if diag.get("failure_code"):
            try:
                fc = FailureCode(diag["failure_code"])
                return fc, 0.7, f"Provider-reported failure: {fc.value}"
            except ValueError:
                pass

        exit_code = diag.get("exit_code")
        if exit_code is not None and isinstance(exit_code, int) and exit_code in EXIT_CODE_MAP:
            fc = EXIT_CODE_MAP[exit_code]
            keywords = EXIT_CODE_KEYWORDS.get(exit_code, [])
            matched = any(kw in " ".join(log_lines).lower() for kw in keywords)
            confidence = 0.85 if matched else 0.6
            return fc, confidence, f"Exit code {exit_code}"

        if diag.get("failure_reason"):
            return FailureCode.UNKNOWN_RUNTIME_FAILURE, 0.4, f"Reason: {diag['failure_reason']}"

        if log_lines:
            last = log_lines[-1] if log_lines else ""
            return FailureCode.UNKNOWN_RUNTIME_FAILURE, 0.3, f"Process died. Last log: {last[:200]}"

        return FailureCode.UNKNOWN_RUNTIME_FAILURE, 0.2, "No diagnostic data available"

    @staticmethod
    def _suggest_action(failure_code: FailureCode) -> str:
        suggestions: dict[FailureCode, str] = {
            FailureCode.MEMORY_EXHAUSTED: "Increase -Xmx in launch config or reduce world size",
            FailureCode.PORT_CONFLICT: "Change server-port in server.properties",
            FailureCode.PORT_ALREADY_BOUND: (
                "Stop the other process using the port, or change server-port"
            ),
            FailureCode.JAVA_VERSION_MISMATCH: "Install correct Java version or update server jar",
            FailureCode.INVALID_JAR_PATH: "Verify server.jar exists in the server directory",
            FailureCode.MEMORY_CONFIGURATION_ERROR: "Fix JVM memory flags in launch configuration",
            FailureCode.NETWORK_BIND_FAILURE: "Check network interface and port availability",
            FailureCode.FILE_NOT_FOUND: "Restore missing files from backup",
            FailureCode.PERMISSION_ERROR: "Check file permissions on server directory",
            FailureCode.MOD_CRASH: "Check or disable the conflicting or failing mod",
            FailureCode.TMUX_SESSION_LOST: "Check tmux installation and session management",
            FailureCode.STARTUP_TIMEOUT: "Increase startup_timeout or check JVM health",
            FailureCode.RUNTIME_PROCESS_LOST: "Restart the server",
            FailureCode.INVALID_LAUNCH_CONFIGURATION: "Review launch configuration",
            FailureCode.INVALID_DEPLOYMENT: "Review deployment configuration",
            FailureCode.PROVIDER_LAUNCH_FAILED: "Check provider configuration and logs",
            FailureCode.JAVA_PROCESS_NOT_FOUND: "Reinstall Java and verify PATH",
        }
        return suggestions.get(failure_code, "Restart and monitor server logs")

    def analyze_crash_content(self, content: str) -> CrashReportAnalysis:
        blamed_mod: str | None = None
        for pat in FORGE_BLAME_PATTERNS:
            match = pat.search(content)
            if match:
                groups = [g for g in match.groups() if g]
                blamed_mod = groups[-1] if groups else None
                break

        if not blamed_mod:
            for pat in FABRIC_BLAME_PATTERNS:
                match = pat.search(content)
                if match:
                    groups = [g for g in match.groups() if g]
                    blamed_mod = groups[-1] if groups else None
                    break

        failure_code = FailureCode.UNKNOWN_RUNTIME_FAILURE
        summary = "Unknown crash"

        if blamed_mod:
            failure_code = FailureCode.MOD_CRASH
            summary = f"Mod failure: {blamed_mod}"
        else:
            for pattern, code, label in CRASH_REPORT_PATTERNS:
                if pattern.search(content):
                    failure_code = code
                    summary = label
                    break

        snippet = extract_stack_trace_snippet(content)

        if blamed_mod:
            remediation = (
                f"Disable, remove, or update blamed mod '{blamed_mod}'. "
                "Check for incompatible versions or missing dependencies."
            )
        else:
            remediation = self._suggest_action(failure_code)

        return CrashReportAnalysis(
            failure_code=failure_code,
            summary=summary,
            blamed_mod=blamed_mod,
            stack_trace_snippet=snippet,
            suggested_remediation=remediation,
        )
