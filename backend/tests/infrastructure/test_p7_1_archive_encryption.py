"""P7-1: Tier-2 archive creation with mandatory 64 KiB AES-256-GCM encryption."""

from __future__ import annotations

import json
import os
import struct
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.backup.application.commands.create_backup import CreateBackupCommand
from app.modules.backup.application.services.archive_service import (
    ARCHIVE_MAGIC,
    ARCHIVE_VERSION,
    create_tier_2_archive,
)
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.shared.value_objects import MinecraftVersion, ServerId


@pytest.fixture
async def app_db():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    yield
    await engine.dispose()
    database._engine = None
    database._session_factory = None


def _make_server_dir(class_c_present: bool = True) -> Path:
    root = Path(tempfile.mkdtemp(prefix="p7-1-archive-server-"))
    (root / "server.properties").write_text("level-name=world\ngamemode=survival\n")
    (root / "eula.txt").write_text("eula=true\n")
    if class_c_present:
        (root / "ops.json").write_text("{}")  # Class C present -> encryption mandatory
    (root / "whitelist.json").write_text("[]")
    (root / "world").mkdir()
    (root / "world" / "level.dat").write_bytes(b"\x00\x01\x02\x03")
    (root / "plugins").mkdir()
    (root / "plugins" / "plugin_db").mkdir()
    (root / "plugins" / "plugin_db" / "data.bin").write_bytes(b"\x04\x05\x06\x07")
    return root


def _make_server(server_id: ServerId, server_dir: Path) -> Server:
    return Server.create(
        server_id=server_id,
        name="arch-test",
        server_type=ServerType.VANILLA,
        minecraft_version=MinecraftVersion.parse("1.21"),
        memory=MemoryAllocation(min_mb=1024, max_mb=2048),
        java_args=JavaArguments([]),
        properties=ServerProperties(port=PortNumber(25565), gamemode="survival", difficulty="easy"),
        deployment=ServerDeployment(
            location_type=LocationType.LOCAL, location_uri="",
            root_path=str(server_dir), working_directory=".",
            startup_jar="server.jar",
        ),
    )


async def _persist_server(session: AsyncSession, server: Server):
    from app.modules.server.infrastructure.repository import SQLServerRepository

    repo = SQLServerRepository(session)
    await repo.save(server)
    await session.commit()


@pytest.mark.asyncio
async def test_tier_2_archive_encrypted_when_class_c_present(app_db):  # noqa: ARG001
    """F012: Tier-2 archive is encrypted when Class C (ops.json) is present."""
    server_dir = _make_server_dir(class_c_present=True)
    server_id = ServerId("srv-arch-1")
    async with database.session_factory() as session:
        await _persist_server(session, _make_server(server_id, server_dir))

    cmd = CreateBackupCommand(server_id=str(server_id), backup_type="full", pinned=False)
    async with database.session_factory() as session:
        result = await create_tier_2_archive(cmd, server_id, session)
    assert result.tier == "tier_2"
    assert result.encrypted is True

    data = Path(result.storage_path).read_bytes()
    assert data[: len(ARCHIVE_MAGIC)] == ARCHIVE_MAGIC
    header_len = struct.unpack(">Q", data[len(ARCHIVE_MAGIC) : len(ARCHIVE_MAGIC) + 8])[0]
    header = json.loads(
        data[len(ARCHIVE_MAGIC) + 8 : len(ARCHIVE_MAGIC) + 8 + header_len].decode("utf-8")
    )
    assert header["version"] == ARCHIVE_VERSION
    assert header["encrypted"] is True
    assert "wrapped_dek" in header and "dek_nonce" in header
    assert header["class_c_present"] is True
    assert header["tier"] == "tier_2"


@pytest.mark.asyncio
async def test_tier_2_archive_not_encrypted_without_class_c(app_db):  # noqa: ARG001
    """F013: Tier-2 archive is NOT encrypted when no Class C and local storage."""
    server_dir = _make_server_dir(class_c_present=False)
    server_id = ServerId("srv-arch-2")
    async with database.session_factory() as session:
        await _persist_server(session, _make_server(server_id, server_dir))

    cmd = CreateBackupCommand(server_id=str(server_id), backup_type="full", pinned=False)
    async with database.session_factory() as session:
        result = await create_tier_2_archive(cmd, server_id, session)
    assert result.tier == "tier_2"
    assert result.encrypted is False

    data = Path(result.storage_path).read_bytes()
    assert data[: len(ARCHIVE_MAGIC)] == ARCHIVE_MAGIC
    header_len = struct.unpack(">Q", data[len(ARCHIVE_MAGIC) : len(ARCHIVE_MAGIC) + 8])[0]
    header = json.loads(
        data[len(ARCHIVE_MAGIC) + 8 : len(ARCHIVE_MAGIC) + 8 + header_len].decode("utf-8")
    )
    assert header["encrypted"] is False
    assert header["compression"] in ("zst", "gz", "tar.gz", "tar.zst")


@pytest.mark.asyncio
async def test_tier_2_archive_tar_content_valid(app_db):  # noqa: ARG001
    """F014: Non-encrypted tier-2 archive contains a valid tar with server files."""
    server_dir = _make_server_dir(class_c_present=False)
    server_id = ServerId("srv-arch-3")
    async with database.session_factory() as session:
        await _persist_server(session, _make_server(server_id, server_dir))

    cmd = CreateBackupCommand(server_id=str(server_id), backup_type="full", pinned=False)
    async with database.session_factory() as session:
        result = await create_tier_2_archive(cmd, server_id, session)
    assert result.encrypted is False

    data = Path(result.storage_path).read_bytes()
    header_len = struct.unpack(">Q", data[len(ARCHIVE_MAGIC) : len(ARCHIVE_MAGIC) + 8])[0]
    payload_len = struct.unpack(
        ">Q",
        data[len(ARCHIVE_MAGIC) + 8 + header_len : len(ARCHIVE_MAGIC) + 16 + header_len],
    )[0]
    payload = data[
        len(ARCHIVE_MAGIC) + 16 + header_len : len(ARCHIVE_MAGIC) + 16 + header_len + payload_len
    ]
    with tarfile.open(fileobj=BytesIO(payload), mode="r:*") as tar:
        names = {m.name for m in tar.getmembers()}
        assert any("server.properties" in n for n in names)
        assert any("whitelist.json" in n for n in names)
        assert not any("ops.json" in n for n in names)  # no Class C


def test_archive_magic_and_version_constants():
    """F015: Archive magic and version constants are correct."""
    assert ARCHIVE_MAGIC == b"ONXARCH2"
    assert ARCHIVE_VERSION == 1


def test_dek_wrap_unwrap_roundtrip():
    """F016: DEK wrap/unwrap with KEK round-trips correctly."""
    from app.modules.storage.encryption import load_or_create_backup_key

    kek = load_or_create_backup_key()
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    wrapped = AESGCM(kek).encrypt(nonce, dek, b"onx-archive-dek")
    unwrapped = AESGCM(kek).decrypt(nonce, wrapped, b"onx-archive-dek")
    assert unwrapped == dek
