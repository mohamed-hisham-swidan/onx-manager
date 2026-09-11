import json
from pathlib import Path

import yaml


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def construct_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"Duplicate key found: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_events_yaml_integrity_f090() -> None:
    events_file = REPO_ROOT / "contracts" / "events.yaml"
    with open(events_file, encoding="utf-8") as f:
        events = yaml.load(f, Loader=UniqueKeyLoader)

    # Assert no duplicate key exception was raised and backup.completed is defined
    assert "backup.completed" in events["events"]
    backup_completed = events["events"]["backup.completed"]
    assert backup_completed["version"] == 2
    assert "size_human" in backup_completed["payload"]
    assert "checksum_algorithm" in backup_completed["payload"]


def test_plugin_yaml_integrity_f091() -> None:
    plugin_file = REPO_ROOT / "contracts" / "plugin.yaml"
    with open(plugin_file, encoding="utf-8") as f:
        plugin = yaml.load(f, Loader=UniqueKeyLoader)

    states = plugin["lifecycle"]["states"]
    assert states.count("DISABLED") == 1
    assert "ENABLING" in plugin["lifecycle"]["transitions"]["DISABLED"]
    assert "UNINSTALLING" in plugin["lifecycle"]["transitions"]["DISABLED"]


def test_config_schema_integrity_f092() -> None:
    config_schema_file = REPO_ROOT / "contracts" / "config.schema.json"
    with open(config_schema_file, encoding="utf-8") as f:
        config_schema = json.load(f)

    # local_windows must be recognized in provider_type enum
    assert "local_windows" in config_schema["properties"]["provider_type"]["enum"]

    # java_args must support array of strings or string
    java_args_schema = config_schema["properties"]["java_args"]
    assert "oneOf" in java_args_schema
    types = [sub["type"] for sub in java_args_schema["oneOf"]]
    assert "array" in types
    assert "string" in types
