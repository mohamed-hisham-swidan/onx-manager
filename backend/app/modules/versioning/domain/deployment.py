import os
from dataclasses import dataclass

from app.core.exceptions import TestIsolationViolationError


@dataclass(frozen=True)
class TestServerDeployment:
    """Marker type wrapping an isolated test-directory root path.

    Safety Invariant (§3.5.3):
    write_test_server_properties() accepts ONLY TestServerDeployment at the type
    level, preventing production ServerDeployment from being used.
    """

    __test__ = False

    test_id: str

    test_dir: str
    startup_jar: str = "server.jar"
    primary_world: str = "world"

    def __post_init__(self) -> None:
        norm = os.path.normpath(self.test_dir)
        # Defense in depth: test_dir must reside under an isolated .onx/tests path
        if not (".onx" in norm and "tests" in norm):
            raise TestIsolationViolationError(
                "TestServerDeployment path must be an isolated .onx/tests directory, "
                f"got: {self.test_dir}"
            )

    @property
    def server_dir(self) -> str:
        return self.test_dir

    def properties_path(self) -> str:
        return os.path.join(self.test_dir, "server.properties")

    def eula_path(self) -> str:
        return os.path.join(self.test_dir, "eula.txt")

    def world_path(self, world_name: str | None = None) -> str:
        return os.path.join(self.test_dir, world_name or self.primary_world)
