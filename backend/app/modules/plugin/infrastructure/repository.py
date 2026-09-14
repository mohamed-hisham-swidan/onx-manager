from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plugin.domain.aggregate import Plugin, PluginStatus
from app.modules.plugin.domain.repository import PluginRepository
from app.modules.plugin.infrastructure.models import PluginModel
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId


class SQLPluginRepository(PluginRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, plugin_id: PluginId) -> Plugin:
        model = await self._session.get(PluginModel, str(plugin_id))
        if model is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(f"Plugin '{plugin_id}' not found")
        return self._model_to_domain(model)

    async def list_by_server(self, server_id: ServerId) -> list[Plugin]:
        stmt = (
            select(PluginModel)
            .where(PluginModel.server_id == str(server_id))
            .where(PluginModel.pending_deletion.is_(False))
            .order_by(PluginModel.name)
        )
        result = await self._session.execute(stmt)
        return [self._model_to_domain(m) for m in result.scalars().all()]

    async def list_all_by_server(self, server_id: ServerId) -> list[Plugin]:
        stmt = (
            select(PluginModel)
            .where(PluginModel.server_id == str(server_id))
            .order_by(PluginModel.name)
        )
        result = await self._session.execute(stmt)
        return [self._model_to_domain(m) for m in result.scalars().all()]

    async def list_pending_deletions(self, server_id: ServerId) -> list[Plugin]:
        stmt = (
            select(PluginModel)
            .where(PluginModel.server_id == str(server_id))
            .where(PluginModel.pending_deletion.is_(True))
            .order_by(PluginModel.name)
        )
        result = await self._session.execute(stmt)
        return [self._model_to_domain(m) for m in result.scalars().all()]

    async def save(self, plugin: Plugin) -> None:
        model = await self._session.get(PluginModel, str(plugin.plugin_id))
        if model is None:
            model = PluginModel(id=str(plugin.plugin_id))
            self._session.add(model)

        model.server_id = str(plugin.server_id)
        model.name = plugin.name
        model.version = plugin.display_version
        model.description = plugin.description
        model.author = plugin.author
        model.website = plugin.website
        model.dependencies = ",".join(plugin.dependencies)
        model.status = plugin.status.value
        model.source = plugin.source
        model.project_type = plugin.project_type
        model.loader = plugin.loader
        model.mod_id = plugin.mod_id
        model.is_disabled_on_disk = plugin.is_disabled_on_disk
        model.filename = plugin.filename
        model.pending_deletion = plugin.pending_deletion
        model.pending_deletion_requested_at = plugin.pending_deletion_requested_at
        model.external_project_id = plugin.external_project_id
        model.external_version_id = plugin.external_version_id
        model.external_url = plugin.external_url
        model.checksum = plugin.checksum
        model.icon_url = plugin.icon_url
        model.installed_at = plugin.installed_at
        model.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def delete(self, plugin_id: PluginId) -> None:
        model = await self._session.get(PluginModel, str(plugin_id))
        if model:
            await self._session.delete(model)
            await self._session.flush()

    def _model_to_domain(self, model: PluginModel) -> Plugin:
        deps = [d.strip() for d in model.dependencies.split(",") if d.strip()]

        version_raw: str | None = None
        try:
            version = PluginVersion.parse(model.version)
        except ValueError:
            version_raw = model.version
            version = PluginVersion(0, 0, 0)

        plugin = Plugin(
            plugin_id=PluginId(model.id),
            server_id=ServerId(model.server_id),
            name=model.name,
            version=version,
            description=model.description,
            author=model.author,
            website=model.website,
            dependencies=deps,
            status=PluginStatus(model.status),
            source=model.source,
            filename=model.filename,
            pending_deletion=model.pending_deletion,
            pending_deletion_requested_at=model.pending_deletion_requested_at,
            external_project_id=model.external_project_id,
            external_version_id=model.external_version_id,
            external_url=model.external_url,
            checksum=model.checksum,
            version_raw=version_raw,
            project_type=getattr(model, "project_type", "plugin"),
            icon_url=getattr(model, "icon_url", None),
            loader=getattr(model, "loader", None),
            mod_id=getattr(model, "mod_id", None),
            is_disabled_on_disk=getattr(model, "is_disabled_on_disk", False),
            installed_at=model.installed_at,
            updated_at=model.updated_at,
        )

        status_map = {s.value: s for s in PluginStatus}
        plugin._status = status_map.get(model.status, PluginStatus.INSTALLED)

        return plugin
