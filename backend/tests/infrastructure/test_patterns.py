from __future__ import annotations

from app.modules.server.domain.diagnostics import FailureCode
from app.modules.server.infrastructure.providers.patterns import (
    FAILURE_PATTERNS,
    detect_failure,
)


class TestFailurePatterns:
    def test_detect_out_of_memory(self) -> None:
        logs = ["[15:32:01] [Server thread/WARN]: java.lang.OutOfMemoryError: Java heap space"]
        code, name = detect_failure(logs)
        assert code == FailureCode.MEMORY_EXHAUSTED
        assert name == "OutOfMemoryError"

    def test_detect_port_in_use(self) -> None:
        logs = ["Exception: Port already in use: 25565"]
        code, name = detect_failure(logs)
        assert code == FailureCode.PORT_CONFLICT

    def test_detect_address_in_use(self) -> None:
        logs = ["Caused by: java.net.BindException: Address already in use"]
        code, name = detect_failure(logs)
        assert code == FailureCode.PORT_ALREADY_BOUND

    def test_detect_unsupported_class_version(self) -> None:
        logs = ["java.lang.UnsupportedClassVersionError: org/bukkit/craftbukkit/Main has been compiled by a more recent version of the Java Runtime"]
        code, name = detect_failure(logs)
        assert code == FailureCode.JAVA_VERSION_MISMATCH

    def test_detect_invalid_jar_path(self) -> None:
        logs = ["Error: Unable to access jarfile /opt/minecraft/server.jar"]
        code, name = detect_failure(logs)
        assert code == FailureCode.INVALID_JAR_PATH

    def test_detect_memory_config(self) -> None:
        logs = ["Could not reserve enough space for 2097152KB object heap"]
        code, name = detect_failure(logs)
        assert code == FailureCode.MEMORY_CONFIGURATION_ERROR

    def test_detect_bind_failure(self) -> None:
        logs = ["Failed to bind to port: java.net.BindException"]
        code, name = detect_failure(logs)
        assert code == FailureCode.NETWORK_BIND_FAILURE

    def test_detect_file_not_found(self) -> None:
        logs = ["java.io.FileNotFoundException: /opt/minecraft/server.properties (No such file or directory)"]
        code, name = detect_failure(logs)
        assert code == FailureCode.FILE_NOT_FOUND

    def test_detect_permission_error(self) -> None:
        logs = ["java.nio.file.AccessDeniedException: /opt/minecraft"]
        code, name = detect_failure(logs)
        assert code == FailureCode.PERMISSION_ERROR

    def test_detect_tmux_session_lost(self) -> None:
        logs = ["tmux: session not found: mcs-test-1"]
        code, name = detect_failure(logs)
        assert code == FailureCode.TMUX_SESSION_LOST

    def test_no_match_returns_none(self) -> None:
        logs = ["[INFO] Done! For help, type 'help'"]
        code, name = detect_failure(logs)
        assert code is None
        assert name == ""

    def test_multiple_lines_returns_first_match(self) -> None:
        logs = [
            "[INFO] Starting Minecraft server...",
            "Error: Unable to access jarfile server.jar",
            "java.lang.OutOfMemoryError: Java heap space",
        ]
        code, name = detect_failure(logs)
        assert code == FailureCode.INVALID_JAR_PATH
        assert name == "UnableToAccessJarfile"

    def test_empty_logs(self) -> None:
        code, name = detect_failure([])
        assert code is None
        assert name == ""

    def test_all_patterns_have_unique_codes(self) -> None:
        codes = [fp.failure_code for fp in FAILURE_PATTERNS]
        assert len(codes) == len(set(codes))

    def test_all_patterns_have_names(self) -> None:
        for fp in FAILURE_PATTERNS:
            assert fp.name, f"Pattern missing name: {fp.failure_code}"
