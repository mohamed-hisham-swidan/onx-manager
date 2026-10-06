from app.modules.server.application.read_models import is_secret_property_key


def test_secret_property_key_positive():
    redacted_keys = [
        "rcon.password",
        "RCON_PASSWORD",
        "serverPassword",
        "api-key",
        "my-token",
        "my_secret",
        "password",
        "secret",
        "token",
        "apikey",
        "auth.token",
        "api_key",
        "server-password",
    ]
    for key in redacted_keys:
        assert is_secret_property_key(key) is True, f"Expected {key} to be redacted"


def test_secret_property_key_negative():
    visible_keys = [
        "monkey",
        "turkey",
        "level-seed",
        "query.port",
        "motd",
        "whitelist",
        "server-port",
        "difficulty",
        "gamemode",
        "max-players",
        "secretkey",  # Accepted consequence of dropping bare-key suffix per spec
    ]
    for key in visible_keys:
        assert is_secret_property_key(key) is False, f"Expected {key} to be visible"
