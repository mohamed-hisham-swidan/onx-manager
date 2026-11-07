# Test & Development Server Sandbox

Automated tests use pytest's isolated `tmp_path` fixtures for server directories and temporary SQLite databases. Do not hand-create or leave persistent test server directories here or under `backend/data/servers/` (which is reserved for runtime server data).

Any ad-hoc sandbox directories or files created under `backend/data/servers_test/` are git-ignored and should be cleaned up after manual debugging (see `TEST_DB.md` for local sandbox database details).
