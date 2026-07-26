from pydantic import BaseModel, Field


class ScanDirectoryRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=4096)


class PluginInfo(BaseModel):
    filename: str
    size_bytes: int
    name: str
    version: str
    main: str
    api_version: str


class ModInfo(BaseModel):
    filename: str
    size_bytes: int
    name: str
    version: str


class WorldInfo(BaseModel):
    name: str
    path: str
    size_bytes: int


class ServerPropertiesInfo(BaseModel):
    port: int = 25565
    motd: str = "A Minecraft Server"
    max_players: int = 20
    gamemode: str = "survival"
    difficulty: str = "easy"
    spawn_protection: int = 16
    pvp: bool = True
    enable_command_block: bool = False
    online_mode: bool = True
    whitelist: bool = False
    view_distance: int = 10
    simulation_distance: int = 10


class ScanResult(BaseModel):
    path: str
    name: str
    server_type: str
    minecraft_version: str
    eula_accepted: bool
    server_jar: str | None = None
    jar_size_bytes: int = 0
    properties: ServerPropertiesInfo
    plugins: list[PluginInfo] = []
    mods: list[ModInfo] = []
    worlds: list[WorldInfo] = []
    icon: str | None = None
    ops: list[str] = []
    banned_players: list[str] = []
    whitelisted_players: list[str] = []


class ImportServerRequest(BaseModel):
    source_path: str = Field(..., min_length=1, max_length=4096)
    name: str = Field(..., min_length=1, max_length=128)
    server_type: str = Field(default="vanilla")
    minecraft_version: str = Field(default="1.20.4")
    min_memory_mb: int = Field(default=1024, ge=128)
    max_memory_mb: int = Field(default=2048, ge=128)
    port: int = Field(default=25565, ge=1, le=65535)
    motd: str = Field(default="A Minecraft Server")
    max_players: int = Field(default=20, ge=1, le=500)
    gamemode: str = Field(default="survival")
    difficulty: str = Field(default="easy")
    spawn_protection: int = Field(default=16, ge=0)
    pvp: bool = True
    enable_command_block: bool = False
    online_mode: bool = True
    whitelist: bool = False
    view_distance: int = Field(default=10, ge=2, le=32)
    simulation_distance: int = Field(default=10, ge=2, le=32)