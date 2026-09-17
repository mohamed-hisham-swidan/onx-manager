from __future__ import annotations

import os
from typing import Any

from app.core.exceptions import TestIsolationViolationError
from app.modules.versioning.domain.deployment import TestServerDeployment


def write_test_server_properties(
    deployment: TestServerDeployment,
    base_properties: dict[str, Any] | None = None,
    server_port: int = 25565,
    rcon_port: int | None = None,
    rcon_password: str | None = None,
    bot_count: int = 10,
) -> str:
    """Writes server.properties strictly for an isolated test deployment.

    SAFETY-CRITICAL INVARIANT (§3.5.3, §3.4):
    1. Accepts ONLY TestServerDeployment at type-level and checks isinstance at runtime.
    2. Enforces online-mode=false AND enforce-secure-profile=false unconditionally.
    3. Production online_mode or secure profile flags are NEVER read or preserved.
    4. Writes strictly to deployment.properties_path() inside .onx/tests/<test_id>/.
    5. Scales max-players >= bot_count + 5 to prevent connection rejection in test container.
    """
    if not isinstance(deployment, TestServerDeployment):
        raise TestIsolationViolationError(
            "write_test_server_properties accepts only TestServerDeployment, "
            f"received: {type(deployment).__name__}"
        )

    target_path = deployment.properties_path()
    norm = os.path.normpath(target_path)
    if not (".onx" in norm and "tests" in norm):
        raise TestIsolationViolationError(
            f"Test server.properties must reside inside .onx/tests/<test_id>/, got: {target_path}"
        )

    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    props: dict[str, str] = {}
    if base_properties:
        for k, v in base_properties.items():
            props[str(k).strip()] = str(v).strip()

    # Apply test overrides
    props["server-port"] = str(server_port)
    props["query.port"] = str(server_port)

    if rcon_port is not None:
        props["enable-rcon"] = "true"
        props["rcon.port"] = str(rcon_port)
        if rcon_password:
            props["rcon.password"] = rcon_password
    else:
        props["enable-rcon"] = "false"

    # HARD INVARIANT: Offline-mode isolation guarantee
    props["online-mode"] = "false"
    props["enforce-secure-profile"] = "false"

    # HARD INVARIANT: Capacity scaling for bot verification (§3.4)
    base_max = 20
    if base_properties and "max-players" in base_properties:
        try:
            base_max = int(base_properties["max-players"])
        except (ValueError, TypeError):
            base_max = 20
    props["max-players"] = str(max(base_max, bot_count + 5))

    # Format into server.properties format
    lines = [
        "# Minecraft server properties for ONX Isolated Test Container",
        "# Generated automatically by versioning test runner - DO NOT EDIT MANUALLY",
    ]
    for key in sorted(props.keys()):
        lines.append(f"{key}={props[key]}")

    content = "\n".join(lines) + "\n"
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Also ensure eula.txt exists in test deployment
    eula_path = deployment.eula_path()
    with open(eula_path, "w", encoding="utf-8") as f:
        f.write("eula=true\n")

    return target_path
