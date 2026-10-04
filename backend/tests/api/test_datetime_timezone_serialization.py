import datetime

import pytest
from fastapi.encoders import jsonable_encoder
from httpx import ASGITransport, AsyncClient

from app.api.v1.schemas.backup import BackupResponse
from app.api.v1.schemas.operation import OperationSummaryResponse
from app.api.v1.schemas.server import ServerResponse
from app.api.v1.schemas.versioning import CommitResponse
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.main import app
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId
from app.registration import register_handlers


@pytest.fixture(scope="module")
def buses():
    event_bus = EventBus()
    command_bus = CommandBus()
    query_bus = QueryBus()
    register_handlers(command_bus, query_bus, event_bus)
    return command_bus, query_bus, event_bus


@pytest.fixture(autouse=True)
def _override_deps(buses) -> None:
    command_bus, query_bus, event_bus = buses
    from app.api import deps

    async def get_cb() -> CommandBus:
        return command_bus

    async def get_qb() -> QueryBus:
        return query_bus

    async def get_eb() -> EventBus:
        return event_bus

    app.dependency_overrides[deps.get_command_bus] = get_cb
    app.dependency_overrides[deps.get_query_bus] = get_qb
    app.dependency_overrides[deps.get_event_bus] = get_eb


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def auth_header() -> dict[str, str]:
    token = create_access_token(
        user_id="admin_user",
        roles=["admin", "owner"],
        permissions=["admin:full", "global.settings"],
    )
    return {"Authorization": f"Bearer {token}"}


class TestDatetimeSerializationUnits:
    """Unit tests for response schemas datetime serialization."""

    def test_server_response_naive_datetime_serialized_with_z(self) -> None:
        sr = ServerResponse(
            server_id="s1",
            name="test",
            server_type="purpur",
            minecraft_version="1.20.4",
            status="starting",
            group_id="default",
            port=25565,
            motd="motd",
            max_players=20,
            gamemode="survival",
            difficulty="normal",
            created_at=datetime.datetime(2026, 10, 3, 11, 0, 0),
            updated_at=datetime.datetime(2026, 10, 3, 11, 0, 7),
        )
        dumped = sr.model_dump(mode="json")
        assert dumped["created_at"].endswith("Z") or "+00:00" in dumped["created_at"], (
            f"created_at was {dumped['created_at']}"
        )
        assert dumped["updated_at"].endswith("Z") or "+00:00" in dumped["updated_at"], (
            f"updated_at was {dumped['updated_at']}"
        )

        encoded = jsonable_encoder(sr)
        assert encoded["created_at"].endswith("Z") or "+00:00" in encoded["created_at"]
        assert encoded["updated_at"].endswith("Z") or "+00:00" in encoded["updated_at"]

    def test_commit_response_string_iso_serialized_with_z(self) -> None:
        cr = CommitResponse(
            id="c1",
            server_id="s1",
            message="Initial commit",
            manifest={},
            created_at="2026-10-03T11:00:00",
        )
        dumped = cr.model_dump(mode="json")
        assert dumped["created_at"].endswith("Z") or "+00:00" in dumped["created_at"], (
            f"created_at was {dumped['created_at']}"
        )

    def test_backup_response_naive_datetime_serialized_with_z(self) -> None:
        br = BackupResponse(
            backup_id="b1",
            server_id="s1",
            backup_type="full",
            status="completed",
            size_bytes=1024,
            checksum="abc",
            error_message="",
            created_at=datetime.datetime(2026, 10, 3, 11, 0, 0),
            completed_at=datetime.datetime(2026, 10, 3, 11, 2, 0),
        )
        dumped = br.model_dump(mode="json")
        assert dumped["created_at"].endswith("Z") or "+00:00" in dumped["created_at"]
        assert dumped["completed_at"].endswith("Z") or "+00:00" in dumped["completed_at"]

    def test_operation_summary_response_serialized_with_z(self) -> None:
        op = OperationSummaryResponse(
            id="op1",
            type="server.start",
            target_type="server",
            status="RUNNING",
            created_at="2026-10-03T11:00:00",
            started_at="2026-10-03T11:00:01",
        )
        dumped = op.model_dump(mode="json")
        assert dumped["created_at"].endswith("Z") or "+00:00" in dumped["created_at"]
        assert dumped["started_at"].endswith("Z") or "+00:00" in dumped["started_at"]

    def test_auth_api_key_response_serialized_with_z(self) -> None:
        from app.api.v1.schemas.auth import ApiKeyResponse

        resp = ApiKeyResponse(
            api_key_id="k1",
            name="test-key",
            prefix="onx_",
            permissions=["server.read"],
            is_revoked=False,
            created_at=datetime.datetime(2026, 10, 3, 11, 0, 0),
            expires_at=datetime.datetime(2026, 11, 3, 11, 0, 0),
        )
        dumped = resp.model_dump(mode="json")
        assert dumped["created_at"].endswith("Z") or "+00:00" in dumped["created_at"]
        assert dumped["expires_at"].endswith("Z") or "+00:00" in dumped["expires_at"]

    def test_invite_responses_serialized_with_z(self) -> None:
        from app.api.v1.routers.invites import CreateInviteResponse, InviteListItemResponse

        cir = CreateInviteResponse(
            invite_id="inv1",
            token="tok1",
            token_prefix="tok",
            global_role="member",
            status="pending",
            max_uses=1,
            expires_at="2026-10-03T12:00:00",
        )
        dumped_cir = cir.model_dump(mode="json")
        assert dumped_cir["expires_at"].endswith("Z")

        ilir = InviteListItemResponse(
            invite_id="inv1",
            token_prefix="tok",
            creator_id="u1",
            global_role="member",
            status="pending",
            max_uses=1,
            use_count=0,
            expires_at="2026-10-03T12:00:00",
            created_at="2026-10-03T11:00:00",
        )
        dumped_ilir = ilir.model_dump(mode="json")
        assert dumped_ilir["expires_at"].endswith("Z")
        assert dumped_ilir["created_at"].endswith("Z")

    def test_invite_list_item_response_keys_match_query_handler(self) -> None:
        from app.api.v1.routers.invites import InviteListItemResponse

        expected_keys = {
            "invite_id",
            "token_prefix",
            "creator_id",
            "email",
            "global_role",
            "server_id",
            "server_role",
            "status",
            "max_uses",
            "use_count",
            "expires_at",
            "used_at",
            "created_at",
        }
        assert set(InviteListItemResponse.model_fields.keys()) == expected_keys

        item = InviteListItemResponse(
            invite_id="inv1",
            token_prefix="tok",
            creator_id="u1",
            email="user@example.com",
            global_role="admin",
            server_id="s1",
            server_role="operator",
            status="ACTIVE",
            max_uses=5,
            use_count=1,
            expires_at="2026-10-03T12:00:00",
            used_at="2026-10-03T11:30:00",
            created_at="2026-10-03T10:00:00",
        )
        dumped = item.model_dump(mode="json")
        assert set(dumped.keys()) == expected_keys
        assert dumped["expires_at"].endswith("Z")
        assert dumped["used_at"].endswith("Z")
        assert dumped["created_at"].endswith("Z")

    def test_plugin_responses_serialized_with_z(self) -> None:
        from app.api.v1.schemas.plugin import PluginResponse, PluginVersionResponse

        pr = PluginResponse(
            plugin_id="p1",
            server_id="s1",
            name="Essentials",
            version="1.0.0",
            description="",
            author="Dev",
            status="enabled",
            dependencies=[],
            installed_at=datetime.datetime(2026, 10, 3, 11, 0, 0),
            updated_at=datetime.datetime(2026, 10, 3, 11, 0, 0),
        )
        dumped_pr = pr.model_dump(mode="json")
        assert dumped_pr["installed_at"].endswith("Z")
        assert dumped_pr["updated_at"].endswith("Z")

        pvr = PluginVersionResponse(
            version_id="v1",
            project_id="proj1",
            name="1.0.0",
            version_number="1.0.0",
            date_published="2026-10-03T11:00:00",
        )
        dumped_pvr = pvr.model_dump(mode="json")
        assert dumped_pvr["date_published"].endswith("Z")

    def test_websocket_message_serialization_with_z(self) -> None:
        import json

        from app.websocket.serializers import WSMessage

        dt = datetime.datetime(2026, 10, 3, 11, 0, 0)
        msg = WSMessage(type="state", data={"timestamp": dt})
        raw = msg.to_json()
        parsed = json.loads(raw.decode("utf-8"))
        assert parsed["timestamp"].endswith("Z")


class TestDatetimeSerializationApi:
    """Integration API tests asserting that endpoints return UTC timezone indicators."""

    @pytest.mark.asyncio
    async def test_get_server_detail_datetimes_have_timezone_indicator(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        sid = ServerId("tz-test-server-1")
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = Server.create(
                server_id=sid,
                name="TZ Server",
                server_type=ServerType.VANILLA,
                minecraft_version=MinecraftVersion.parse("1.20.4"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(port=PortNumber(25568)),
            )
            server.start()
            await repo.save(server)
            await session.commit()

        get_resp = await client.get(f"/api/v1/servers/{sid}", headers=auth_header)
        assert get_resp.status_code == 200
        data = get_resp.json()

        assert data["created_at"].endswith("Z") or "+00:00" in data["created_at"], (
            f"created_at was {data['created_at']}"
        )
        assert data["updated_at"].endswith("Z") or "+00:00" in data["updated_at"], (
            f"updated_at was {data['updated_at']}"
        )

    @pytest.mark.asyncio
    async def test_get_server_list_datetimes_have_timezone_indicator(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        sid = ServerId("tz-test-server-list")
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = Server.create(
                server_id=sid,
                name="TZ List Server",
                server_type=ServerType.VANILLA,
                minecraft_version=MinecraftVersion.parse("1.20.4"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(port=PortNumber(25569)),
            )
            server.start()
            await repo.save(server)
            await session.commit()

        get_resp = await client.get("/api/v1/servers", headers=auth_header)
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert len(data) > 0
        found = next((s for s in data if s["server_id"] == str(sid)), None)
        assert found is not None
        assert found["created_at"].endswith("Z") or "+00:00" in found["created_at"]
        assert found["updated_at"].endswith("Z") or "+00:00" in found["updated_at"]

    @pytest.mark.asyncio
    async def test_get_metrics_timestamps_have_z_indicator(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        from app.modules.monitoring.domain.aggregate import MetricPoint
        from app.modules.monitoring.infrastructure.repository import SQLMetricRepository

        sid = ServerId("tz-metrics-server")
        async with database.session_factory() as session:
            s_repo = SQLServerRepository(session)
            server = Server.create(
                server_id=sid,
                name="TZ Metrics Server",
                server_type=ServerType.VANILLA,
                minecraft_version=MinecraftVersion.parse("1.20.4"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(port=PortNumber(25570)),
            )
            await s_repo.save(server)
            m_repo = SQLMetricRepository(session)
            await m_repo.record(
                sid,
                MetricPoint(tps=20.0, players=2, ram_used_mb=512, cpu_percent=12.5),
            )
            await session.commit()

        resp = await client.get(
            f"/api/v1/monitoring/metrics?server_id={sid}&limit=5",
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["timestamp"].endswith("Z")

    @pytest.mark.asyncio
    async def test_get_alerts_last_triggered_at_has_z_indicator(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        from app.modules.monitoring.domain.aggregate import (
            AlertCondition,
            AlertRule,
            AlertSeverity,
        )
        from app.modules.monitoring.infrastructure.repository import SQLAlertRuleRepository

        sid = ServerId("tz-alerts-server")
        async with database.session_factory() as session:
            repo = SQLAlertRuleRepository(session)
            rule = AlertRule(
                server_id=sid,
                metric_name="cpu_percent",
                condition=AlertCondition.GREATER_THAN,
                threshold=85.0,
                severity=AlertSeverity.WARNING,
            )
            rule._last_triggered_at = datetime.datetime(2026, 10, 3, 14, 0, 0)
            await repo.save(rule)
            await session.commit()

        resp = await client.get(
            f"/api/v1/monitoring/alerts?server_id={sid}",
            headers=auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        found = next((r for r in data if r["server_id"] == str(sid)), None)
        assert found is not None
        assert found["last_triggered_at"] is not None
        assert found["last_triggered_at"].endswith("Z")

    @pytest.mark.asyncio
    async def test_post_and_get_schedules_timestamps_have_z_indicator(
        self, client: AsyncClient, auth_header: dict[str, str]
    ) -> None:
        # POST /api/v1/schedules returns raw dict with created_at
        post_resp = await client.post(
            "/api/v1/schedules",
            json={
                "name": "tz-backup-job",
                "cron_expression": "0 2 * * *",
                "task_name": "backup",
                "enabled": True,
            },
            headers=auth_header,
        )
        assert post_resp.status_code == 201
        post_data = post_resp.json()
        assert post_data["created_at"].endswith("Z")

        # GET /api/v1/schedules returns list of dicts with created_at and last_run_at
        get_resp = await client.get("/api/v1/schedules", headers=auth_header)
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        found = next((s for s in get_data if s["name"] == "tz-backup-job"), None)
        assert found is not None
        assert found["created_at"].endswith("Z")


class TestBaseResponseStringProtectionAndConformance:
    """Validate that BaseResponse wildcard serializer protects non-timestamp strings
    and preserves standard Pydantic serialization behaviors.
    """

    def test_file_content_response_content_unchanged_with_iso_shape(self) -> None:
        """FileContentResponse.content == '2026-10-03T12:00:00' must NOT be rewritten with Z."""
        from app.api.v1.schemas.files import FileContentResponse

        resp = FileContentResponse(
            path="/srv/timestamp.txt",
            content="2026-10-03T12:00:00",
        )
        dumped = resp.model_dump(mode="json")
        assert dumped["content"] == "2026-10-03T12:00:00"

    def test_arbitrary_string_fields_with_iso_shape_unchanged(self) -> None:
        """Commit message, server name, and console line with ISO shape must NOT be rewritten."""
        from app.api.v1.schemas.server import ConsoleResponse, ServerResponse
        from app.api.v1.schemas.versioning import CommitResponse

        iso_str = "2026-10-03T12:00:00"

        # Commit message
        c = CommitResponse(
            id="c1",
            server_id="s1",
            message=iso_str,
            manifest={},
            created_at="2026-10-03 12:00:00",
        )
        c_dump = c.model_dump(mode="json")
        assert c_dump["message"] == iso_str
        assert c_dump["created_at"] == "2026-10-03T12:00:00Z"

        # Server name
        s = ServerResponse(
            server_id="s1",
            name=iso_str,
            server_type="purpur",
            minecraft_version="1.20.4",
            status="starting",
            group_id="default",
            port=25565,
            motd="motd",
            max_players=20,
            gamemode="survival",
            difficulty="normal",
            created_at=datetime.datetime(2026, 10, 3, 12, 0, 0),
            updated_at=datetime.datetime(2026, 10, 3, 12, 0, 0),
        )
        s_dump = s.model_dump(mode="json")
        assert s_dump["name"] == iso_str
        assert s_dump["created_at"] == "2026-10-03T12:00:00Z"
        assert s_dump["updated_at"] == "2026-10-03T12:00:00Z"

        # Console line
        con = ConsoleResponse(
            server_id="s1",
            lines=[iso_str],
        )
        con_dump = con.model_dump(mode="json")
        assert con_dump["lines"][0] == iso_str

    def test_plain_wildcard_preserves_enums_aliases_exclude_none_and_nested_models(self) -> None:
        """Confirm that plain wildcard serializer preserves enums, aliases,
        exclude_none/unset, and nested models.
        """
        from enum import StrEnum

        from pydantic import Field

        from app.api.v1.schemas.common import BaseResponse

        class ExampleStatus(StrEnum):
            PENDING = "pending"
            COMPLETED = "completed"

        class NestedModel(BaseResponse):
            nested_id: str
            nested_created_at: datetime.datetime
            status: ExampleStatus

        class ParentModel(BaseResponse):
            server_name: str
            created_at: datetime.datetime
            aliased_code: str = Field(alias="aliasedCode")
            status: ExampleStatus
            optional_value: str | None = None
            default_value: str = "default"
            nested: NestedModel

        obj = ParentModel(
            server_name="2026-10-03T12:00:00",
            created_at=datetime.datetime(2026, 10, 3, 12, 0, 0),
            aliasedCode="CODE-123",
            status=ExampleStatus.COMPLETED,
            optional_value=None,
            nested=NestedModel(
                nested_id="nest-1",
                nested_created_at=datetime.datetime(2026, 10, 3, 14, 0, 0),
                status=ExampleStatus.PENDING,
            ),
        )

        dumped = obj.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            exclude_unset=True,
        )

        assert dumped["server_name"] == "2026-10-03T12:00:00"
        assert dumped["created_at"] == "2026-10-03T12:00:00Z"
        assert dumped["aliasedCode"] == "CODE-123"
        assert dumped["status"] == "completed"
        assert "optional_value" not in dumped
        assert "default_value" not in dumped
        assert dumped["nested"]["nested_id"] == "nest-1"
        assert dumped["nested"]["nested_created_at"] == "2026-10-03T14:00:00Z"
        assert dumped["nested"]["status"] == "pending"

    def test_enum_field_serialization(self) -> None:
        """Enum fields must serialize to their underlying scalar values."""
        from enum import Enum, StrEnum

        from app.api.v1.schemas.common import BaseResponse

        class ModeEnum(StrEnum):
            READONLY = "readonly"
            EDITABLE = "editable"

        class PriorityEnum(Enum):
            LOW = 1
            HIGH = 2

        class EnumModel(BaseResponse):
            mode: ModeEnum
            priority: PriorityEnum

        model = EnumModel(mode=ModeEnum.READONLY, priority=PriorityEnum.HIGH)
        dumped = model.model_dump(mode="json")
        assert dumped["mode"] == "readonly"
        assert dumped["priority"] == 2

    def test_nested_model_serialization(self) -> None:
        """Nested response models must serialize inner fields and datetimes recursively."""
        from app.api.v1.schemas.common import BaseResponse

        class Inner(BaseResponse):
            inner_name: str
            inner_at: datetime.datetime

        class Outer(BaseResponse):
            title: str
            inner: Inner
            inner_list: list[Inner]

        outer = Outer(
            title="Outer Title",
            inner=Inner(
                inner_name="nested-1",
                inner_at=datetime.datetime(2026, 10, 3, 10, 0, 0),
            ),
            inner_list=[
                Inner(
                    inner_name="item-1",
                    inner_at=datetime.datetime(2026, 10, 3, 11, 0, 0),
                )
            ],
        )
        dumped = outer.model_dump(mode="json")
        assert dumped["title"] == "Outer Title"
        assert dumped["inner"]["inner_name"] == "nested-1"
        assert dumped["inner"]["inner_at"] == "2026-10-03T10:00:00Z"
        assert dumped["inner_list"][0]["inner_name"] == "item-1"
        assert dumped["inner_list"][0]["inner_at"] == "2026-10-03T11:00:00Z"

    def test_exclude_none_and_exclude_unset_behavior(self) -> None:
        """exclude_none and exclude_unset must be honored by BaseResponse serialization."""
        from app.api.v1.schemas.common import BaseResponse

        class ConfigModel(BaseResponse):
            required_key: str
            unset_default: str = "default_val"
            optional_null: str | None = None

        m = ConfigModel(required_key="val")

        # exclude_none=True drops None
        dump_none = m.model_dump(mode="json", exclude_none=True)
        assert "optional_null" not in dump_none
        assert dump_none["required_key"] == "val"
        assert dump_none["unset_default"] == "default_val"

        # exclude_unset=True drops fields not explicitly passed
        dump_unset = m.model_dump(mode="json", exclude_unset=True)
        assert "unset_default" not in dump_unset
        assert "optional_null" not in dump_unset
        assert dump_unset["required_key"] == "val"

    def test_at_field_with_naive_datetime_and_with_naive_iso_string(self) -> None:
        """Fields ending with *_at must normalize both naive datetime and naive ISO string."""
        from app.api.v1.schemas.common import BaseResponse

        class TimestampModel(BaseResponse):
            created_at: datetime.datetime
            updated_at: str
            synced_at: str
            verified_at: str

        tm = TimestampModel(
            created_at=datetime.datetime(2026, 10, 3, 8, 30, 0),
            updated_at="2026-10-03 08:30:00",
            synced_at="2026-10-03T08:30:00",
            verified_at="2026-10-03T08:30:00Z",
        )
        dumped = tm.model_dump(mode="json")
        assert dumped["created_at"] == "2026-10-03T08:30:00Z"
        assert dumped["updated_at"] == "2026-10-03T08:30:00Z"
        assert dumped["synced_at"] == "2026-10-03T08:30:00Z"
        assert dumped["verified_at"] == "2026-10-03T08:30:00Z"

