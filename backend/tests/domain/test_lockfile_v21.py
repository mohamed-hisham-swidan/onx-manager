"""Tests for Lockfile Format 2.1 domain model, parser, serializer, and LEC grammar."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from app.core.exceptions import (
    CaseCollisionError,
    LockfileFormatError,
    LockfileInvalidError,
)
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LoaderRef,
    LockfileFile,
    LockfileV21,
    ModpackRef,
    Origin,
    dump_lockfile,
    parse_lec_key,
    parse_lockfile,
)

SAMPLE_SHA256 = "a" * 64
SAMPLE_SHA512 = "b" * 128
SAMPLE_SHA1 = "c" * 40


def make_valid_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "format": 2,
        "mc": "1.20.4",
        "loader": {"id": "paper", "version": "499"},
        "lec": {"key": "paper/1.20.4/499"},
        "modpack": {
            "source": "modrinth",
            "project_id": "P7dR8mSH",
            "version_id": "998R2rNP",
            "version_label": "1.4.2",
            "index_sha256": SAMPLE_SHA256,
        },
        "base_overrides": {
            "config/fancymenu/options.txt": SAMPLE_SHA256,
        },
        "files": [
            {
                "path": "mods/example.jar",
                "sha256": SAMPLE_SHA256,
                "sha512": SAMPLE_SHA512,
                "sha1": SAMPLE_SHA1,
                "size": 1797522,
                "optional": False,
                "env_server": "required",
                "origin": "modrinth",
                "project_id": "P7dR8mSH",
                "version_id": "998R2rNP",
            }
        ],
    }
    doc.update(overrides)
    return doc


# --- 1. Valid Documents ---


def test_valid_minimal_doc() -> None:
    doc = {
        "format": 2,
        "mc": "1.20.4",
        "loader": {"id": "vanilla", "version": "1.20.4"},
        "base_overrides": {},
        "files": [],
    }
    raw = json.dumps(doc).encode("utf-8")
    lf = parse_lockfile(raw)
    assert lf.format == 2
    assert lf.mc == "1.20.4"
    assert lf.loader.id == "vanilla"
    assert lf.loader.version == "1.20.4"
    assert len(lf.base_overrides) == 0
    assert len(lf.files) == 0
    assert lf.lec is None
    assert lf.modpack is None


def test_valid_full_doc_roundtrip() -> None:
    doc = make_valid_doc()
    raw = json.dumps(doc).encode("utf-8")
    lf = parse_lockfile(raw)
    dumped = dump_lockfile(lf)
    lf2 = parse_lockfile(dumped)
    assert lf == lf2


@pytest.mark.parametrize(
    ("loader_id", "loader_ver", "lec_key"),
    [
        ("paper", "499", "paper/1.20.4/499"),
        ("fabric", "0.16.10", "fabric/1.20.4/0.16.10/1.0.1"),
        ("quilt", "0.26.0", "quilt/1.20.4/0.26.0"),
        ("neoforge", "20.4.80-beta", "neoforge/1.20.4/20.4.80-beta"),
        ("forge", "49.0.30", "forge/1.20.4/49.0.30"),
    ],
)
def test_valid_five_loaders(loader_id: str, loader_ver: str, lec_key: str) -> None:
    doc = make_valid_doc(
        loader={"id": loader_id, "version": loader_ver},
        lec={"key": lec_key},
    )
    raw = json.dumps(doc).encode("utf-8")
    lf = parse_lockfile(raw)
    assert lf.loader.id == loader_id
    assert lf.lec is not None
    assert lf.lec.key == lec_key


def test_valid_unicode_version_label() -> None:
    doc = make_valid_doc()
    doc["modpack"]["version_label"] = "v1.0-Über-🚀"
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    lf = parse_lockfile(raw)
    assert lf.modpack is not None
    assert lf.modpack.version_label == "v1.0-Über-🚀"


@pytest.mark.parametrize("origin", list(Origin))
def test_valid_all_origins(origin: Origin) -> None:
    doc = make_valid_doc()
    doc["files"][0]["origin"] = origin.value
    raw = json.dumps(doc).encode("utf-8")
    lf = parse_lockfile(raw)
    assert lf.files[0].origin == origin


@pytest.mark.parametrize("env_server", list(EnvServer))
def test_valid_all_env_servers(env_server: EnvServer) -> None:
    doc = make_valid_doc()
    doc["files"][0]["env_server"] = env_server.value
    raw = json.dumps(doc).encode("utf-8")
    lf = parse_lockfile(raw)
    assert lf.files[0].env_server == env_server


# --- 2. Format Rejection ---


@pytest.mark.parametrize("bad_format", [1, 3, "2", 2.0, True, None])
def test_reject_format_values(bad_format: Any) -> None:
    doc = make_valid_doc(format=bad_format)
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(LockfileFormatError) as exc_info:
        parse_lockfile(raw)
    assert exc_info.value.code == "LOCKFILE_FORMAT_UNSUPPORTED"


def test_reject_missing_format() -> None:
    doc = make_valid_doc()
    del doc["format"]
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(LockfileFormatError):
        parse_lockfile(raw)


def test_reject_legacy_format_2_missing_base_overrides() -> None:
    doc = make_valid_doc()
    del doc["base_overrides"]
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(LockfileFormatError) as exc_info:
        parse_lockfile(raw)
    assert exc_info.value.code == "LOCKFILE_FORMAT_UNSUPPORTED"


@pytest.mark.parametrize(
    "raw_input",
    [
        b"[]",
        b'"string"',
        b"123",
        b"null",
        b"",
        b"   \n\t",
    ],
)
def test_reject_top_level_non_object(raw_input: bytes) -> None:
    with pytest.raises((LockfileFormatError, LockfileInvalidError)):
        parse_lockfile(raw_input)


# --- 3. Shape and Type Rejection ---


@pytest.mark.parametrize("req_field", ["mc", "loader", "files"])
def test_reject_missing_required_top_field(req_field: str) -> None:
    doc = make_valid_doc()
    del doc[req_field]
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(raw)


@pytest.mark.parametrize(
    ("field", "bad_val"),
    [
        ("mc", 1204),
        ("loader", "paper"),
        ("lec", "paper/1.20.4/499"),
        ("modpack", ["source", "modrinth"]),
        ("base_overrides", ["config/test.txt"]),
        ("files", {}),
    ],
)
def test_reject_wrong_top_field_types(field: str, bad_val: Any) -> None:
    doc = make_valid_doc(**{field: bad_val})
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises((LockfileInvalidError, LockfileFormatError)):
        parse_lockfile(raw)


def test_reject_loader_version_over_64() -> None:
    doc = make_valid_doc()
    doc["loader"]["version"] = "1" * 65
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


def test_loader_id_validation() -> None:
    # Uppercase "Fabric" rejected
    doc = make_valid_doc()
    doc.pop("lec", None)
    doc["loader"]["id"] = "Fabric"
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))

    # 33-char id rejected
    doc = make_valid_doc()
    doc.pop("lec", None)
    doc["loader"]["id"] = "a" * 33
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))

    # 32-char lowercase accepted
    doc = make_valid_doc()
    doc.pop("lec", None)
    doc["loader"]["id"] = "a" * 32
    lf = parse_lockfile(json.dumps(doc).encode("utf-8"))
    assert lf.loader.id == "a" * 32


@pytest.mark.parametrize("bad_mc", ["1.20.4\n", "1.20.4\r", "1.20.4\t", "1.20.4\x00"])
def test_reject_mc_control_characters(bad_mc: str) -> None:
    doc = make_valid_doc(mc=bad_mc)
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))

    with pytest.raises(LockfileInvalidError):
        LockfileV21(
            format=2,
            mc=bad_mc,
            loader=LoaderRef(id="paper", version="499"),
            base_overrides={},
            files=(),
        )


def test_mc_valid_parses() -> None:
    doc = make_valid_doc(mc="1.20.4")
    lf = parse_lockfile(json.dumps(doc).encode("utf-8"))
    assert lf.mc == "1.20.4"


def test_base_overrides_wrong_type_consistency() -> None:
    doc = make_valid_doc()
    doc["base_overrides"] = []
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))

    with pytest.raises(LockfileInvalidError):
        LockfileV21(
            format=2,
            mc="1.20.4",
            loader=LoaderRef(id="vanilla", version="1.20.4"),
            base_overrides=[],  # type: ignore[arg-type]
            files=(),
        )


@pytest.mark.parametrize(
    "field_path",
    [
        "files_path",
        "base_overrides_key",
        "modpack_project_id",
        "modpack_version_id",
        "modpack_version_label",
        "files_project_id",
        "files_version_id",
    ],
)
def test_reject_lone_surrogates(field_path: str) -> None:
    doc = make_valid_doc()
    if field_path == "files_path":
        doc["files"][0]["path"] = "mods/test_\ud800.jar"
    elif field_path == "base_overrides_key":
        doc["base_overrides"] = {"config/test_\ud800.txt": SAMPLE_SHA256}
    elif field_path == "modpack_project_id":
        doc["modpack"]["project_id"] = "proj_\ud800"
    elif field_path == "modpack_version_id":
        doc["modpack"]["version_id"] = "ver_\ud800"
    elif field_path == "modpack_version_label":
        doc["modpack"]["version_label"] = "label_\ud800"
    elif field_path == "files_project_id":
        doc["files"][0]["project_id"] = "proj_\ud800"
    elif field_path == "files_version_id":
        doc["files"][0]["version_id"] = "ver_\ud800"

    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(raw)


@pytest.mark.parametrize("bad_val", [42, ["not_a_string"], {"nested": "obj"}])
@pytest.mark.parametrize("target_field", ["project_id", "version_id"])
def test_reject_non_str_project_version_id(bad_val: Any, target_field: str) -> None:
    doc = make_valid_doc()
    doc["files"][0][target_field] = bad_val
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(raw)


def test_reject_unknown_top_keys() -> None:
    doc = make_valid_doc(extra_unknown_key=123)
    raw = json.dumps(doc).encode("utf-8")
    with pytest.raises(LockfileInvalidError) as exc_info:
        parse_lockfile(raw)
    assert exc_info.value.code == "LOCKFILE_INVALID"


def test_reject_unknown_keys_in_nested_objects() -> None:
    doc = make_valid_doc()
    doc["loader"]["extra"] = "val"
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))

    doc = make_valid_doc()
    doc["lec"]["extra"] = "val"
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))

    doc = make_valid_doc()
    doc["modpack"]["extra"] = "val"
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))

    doc = make_valid_doc()
    doc["files"][0]["extra"] = "val"
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


@pytest.mark.parametrize("opt_field", ["sha512", "sha1", "project_id", "version_id"])
def test_reject_null_in_optional_fields(opt_field: str) -> None:
    doc = make_valid_doc()
    doc["files"][0][opt_field] = None
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


@pytest.mark.parametrize(
    ("field", "bad_hash"),
    [
        ("sha512", "invalid_sha512"),
        ("sha512", "A" * 128),
        ("sha512", "0" * 127),
        ("sha1", "invalid_sha1"),
        ("sha1", "A" * 40),
        ("sha1", "0" * 39),
    ],
)
def test_reject_bad_hash_format_in_files(field: str, bad_hash: str) -> None:
    doc = make_valid_doc()
    doc["files"][0][field] = bad_hash
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


@pytest.mark.parametrize(
    "bad_hash",
    [
        "invalid_sha256",
        "A" * 64,
        "0" * 63,
        "0" * 65,
    ],
)
def test_reject_bad_modpack_index_sha256(bad_hash: str) -> None:
    doc = make_valid_doc()
    doc["modpack"]["index_sha256"] = bad_hash
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


@pytest.mark.parametrize("bad_size", [True, -1, 1.5, "100", 1e999])
def test_reject_invalid_size(bad_size: Any) -> None:
    doc = make_valid_doc()
    doc["files"][0]["size"] = bad_size
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


@pytest.mark.parametrize("bad_opt", [0, 1, "true", None])
def test_reject_invalid_optional_bool(bad_opt: Any) -> None:
    doc = make_valid_doc()
    doc["files"][0]["optional"] = bad_opt
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


@pytest.mark.parametrize(
    "bad_hash",
    [
        "A" * 64,  # uppercase
        "a" * 63,  # too short
        "a" * 65,  # too long
        "g" * 64,  # non hex
        None,
    ],
)
def test_reject_bad_sha256(bad_hash: Any) -> None:
    doc = make_valid_doc()
    doc["files"][0]["sha256"] = bad_hash
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


# --- 4. JSON Strictness ---


def test_reject_malformed_json() -> None:
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(b"{\"format\": 2, ")


def test_reject_invalid_utf8() -> None:
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(b"\xff\xfe\x00\x00")


def test_reject_trailing_junk() -> None:
    raw = json.dumps(make_valid_doc()).encode("utf-8") + b"   junk"
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(raw)


def test_reject_duplicate_raw_keys() -> None:
    raw = (
        b'{"format": 2, "mc": "1.20.4", "mc": "1.20.4", '
        b'"loader": {"id": "vanilla", "version": "1.20.4"}, '
        b'"base_overrides": {}, "files": []}'
    )
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(raw)


def test_reject_duplicate_raw_keys_in_base_overrides() -> None:
    raw = (
        b'{"format": 2, "mc": "1.20.4", "loader": {"id": "vanilla", "version": "1.20.4"}, '
        b'"base_overrides": {"a.txt": "'
        + SAMPLE_SHA256.encode("utf-8")
        + b'", "a.txt": "'
        + SAMPLE_SHA256.encode("utf-8")
        + b'"}, "files": []}'
    )
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(raw)


def test_reject_nan_infinity() -> None:
    raw = (
        b'{"format": 2, "mc": "1.20.4", '
        b'"loader": {"id": "vanilla", "version": "1.20.4"}, '
        b'"base_overrides": {}, '
        b'"files": [{"path": "mods/a.jar", "sha256": "'
        + SAMPLE_SHA256.encode("utf-8")
        + b'", "size": NaN, "optional": false, '
        b'"env_server": "required", "origin": "modrinth"}]}'
    )
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(raw)


def test_reject_bom() -> None:
    raw = b"\xef\xbb\xbf" + json.dumps(make_valid_doc()).encode("utf-8")
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(raw)


# --- 5. Paths and Collisions ---


@pytest.mark.parametrize(
    "bad_path",
    [
        "/mods/test.jar",
        "mods/../test.jar",
        "./mods/test.jar",
        "mods//test.jar",
        "mods\\test.jar",
        "mods:test.jar",
        "mods/test.jar\x00",
        "mods/test.jar\n",
        "mods/test.jar ",
        "mods/test.jar.",
        "mods/test.%2e%2e.jar",
        "mods/test%2f.jar",
        "mods/test%5c.jar",
        "mods/test%00.jar",
    ],
)
def test_reject_hostile_paths_in_files(bad_path: str) -> None:
    doc = make_valid_doc()
    doc["files"][0]["path"] = bad_path
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


def test_reject_duplicate_path_in_files() -> None:
    doc = make_valid_doc()
    file_entry = copy.deepcopy(doc["files"][0])
    doc["files"].append(file_entry)
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


def test_reject_casefold_collision_in_files() -> None:
    doc = make_valid_doc()
    f2 = copy.deepcopy(doc["files"][0])
    f2["path"] = "MODS/example.jar"
    doc["files"].append(f2)
    with pytest.raises(CaseCollisionError) as exc_info:
        parse_lockfile(json.dumps(doc).encode("utf-8"))
    assert exc_info.value.code == "CASE_COLLISION"


def test_reject_collision_between_files_and_base_overrides() -> None:
    doc = make_valid_doc()
    doc["base_overrides"]["mods/example.jar"] = SAMPLE_SHA256
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


def test_reject_casefold_collision_between_files_and_base_overrides() -> None:
    doc = make_valid_doc()
    doc["base_overrides"]["MODS/EXAMPLE.JAR"] = SAMPLE_SHA256
    with pytest.raises(CaseCollisionError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


def test_casefold_unicode_collision() -> None:
    # German Eszett ß casefolds to "ss"
    doc = make_valid_doc()
    doc["files"] = [
        {
            "path": "config/groß.txt",
            "sha256": SAMPLE_SHA256,
            "size": 10,
            "optional": False,
            "env_server": "required",
            "origin": "override",
        },
        {
            "path": "config/gross.txt",
            "sha256": SAMPLE_SHA256,
            "size": 10,
            "optional": False,
            "env_server": "required",
            "origin": "override",
        },
    ]
    with pytest.raises(CaseCollisionError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


def test_reject_casefold_collision_within_base_overrides() -> None:
    doc = make_valid_doc()
    doc["base_overrides"] = {
        "config/A.txt": SAMPLE_SHA256,
        "config/a.txt": SAMPLE_SHA256,
    }
    with pytest.raises(CaseCollisionError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


def test_casefold_ligature_collision() -> None:
    doc = make_valid_doc()
    doc["files"] = [
        {
            "path": "config/\ufb01le.txt",
            "sha256": SAMPLE_SHA256,
            "size": 10,
            "optional": False,
            "env_server": "required",
            "origin": "override",
        },
        {
            "path": "config/file.txt",
            "sha256": SAMPLE_SHA256,
            "size": 10,
            "optional": False,
            "env_server": "required",
            "origin": "override",
        },
    ]
    with pytest.raises(CaseCollisionError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


def test_reject_non_nfc_path() -> None:
    # NFD for "é" is e + combining acute (\u0301)
    doc = make_valid_doc()
    doc["files"][0]["path"] = "config/e\u0301.txt"
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


# --- 6. LEC Grammar and Consistency ---


@pytest.mark.parametrize(
    ("key", "expected_loader", "expected_mc", "expected_ver", "expected_inst"),
    [
        ("paper/1.20.4/499", "paper", "1.20.4", "499", None),
        ("fabric/1.20.4/0.16.10/1.0.1", "fabric", "1.20.4", "0.16.10", "1.0.1"),
        ("quilt/1.20.4/0.26.0", "quilt", "1.20.4", "0.26.0", None),
        ("neoforge/1.20.4/20.4.80-beta", "neoforge", "1.20.4", "20.4.80-beta", None),
        ("forge/1.20.4/49.0.30", "forge", "1.20.4", "49.0.30", None),
    ],
)
def test_parse_lec_key_valid(
    key: str,
    expected_loader: str,
    expected_mc: str,
    expected_ver: str,
    expected_inst: str | None,
) -> None:
    parts = parse_lec_key(key)
    assert parts.loader == expected_loader
    assert parts.mc == expected_mc
    assert parts.version == expected_ver
    assert parts.installer == expected_inst
    assert parts.loader_version == expected_ver


@pytest.mark.parametrize(
    "bad_key",
    [
        "unknown/1.20.4/1",
        "paper/1.20.4",  # wrong segment count
        "paper/1.20.4/499/extra",
        "fabric/1.20.4/0.16.10",  # fabric requires 4
        "paper/1.20.4/0",  # paper build cannot be 0
        "paper/1.20.4/012",  # paper build cannot have leading zero
        "paper/1.20.4/-5",
        "paper/not_a_version/499",
        "paper/1.20.4/%20",
        "paper/1.20.4/build..",
        "paper/1.20.4/" + "a" * 65,  # segment too long
        "a" * 260,  # overlong key
    ],
)
def test_parse_lec_key_invalid(bad_key: str) -> None:
    with pytest.raises(LockfileInvalidError):
        parse_lec_key(bad_key)


def test_lec_consistency_loader_mismatch() -> None:
    doc = make_valid_doc(
        loader={"id": "paper", "version": "499"},
        lec={"key": "quilt/1.20.4/499"},
    )
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


def test_lec_consistency_mc_mismatch() -> None:
    doc = make_valid_doc(
        mc="1.20.4",
        loader={"id": "paper", "version": "499"},
        lec={"key": "paper/1.21.1/499"},
    )
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


def test_lec_consistency_version_mismatch() -> None:
    doc = make_valid_doc(
        loader={"id": "paper", "version": "500"},
        lec={"key": "paper/1.20.4/499"},
    )
    with pytest.raises(LockfileInvalidError):
        parse_lockfile(json.dumps(doc).encode("utf-8"))


def test_lec_consistency_fabric_installer_independence() -> None:
    # Installer version does not have to match loader version
    doc = make_valid_doc(
        loader={"id": "fabric", "version": "0.16.10"},
        lec={"key": "fabric/1.20.4/0.16.10/some-other-installer"},
    )
    lf = parse_lockfile(json.dumps(doc).encode("utf-8"))
    assert lf.loader.version == "0.16.10"
    assert lf.lec is not None
    assert lf.lec.key == "fabric/1.20.4/0.16.10/some-other-installer"


# --- 7. Serialization ---


def test_dump_lockfile_determinism() -> None:
    lf = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="vanilla", version="1.20.4"),
        base_overrides={"z.txt": SAMPLE_SHA256, "a.txt": SAMPLE_SHA256},
        files=(
            LockfileFile(
                path="mods/b.jar",
                sha256=SAMPLE_SHA256,
                size=200,
                optional=False,
                env_server=EnvServer.REQUIRED,
                origin=Origin.MODRINTH,
            ),
            LockfileFile(
                path="mods/a.jar",
                sha256=SAMPLE_SHA256,
                size=100,
                optional=True,
                env_server=EnvServer.OPTIONAL,
                origin=Origin.USER,
            ),
        ),
    )
    b1 = dump_lockfile(lf)
    b2 = dump_lockfile(lf)
    assert b1 == b2
    assert b1.endswith(b"\n")

    parsed_doc = json.loads(b1.decode("utf-8"))
    # Base overrides must be sorted
    assert list(parsed_doc["base_overrides"].keys()) == ["a.txt", "z.txt"]
    # Files must preserve order
    assert [f["path"] for f in parsed_doc["files"]] == ["mods/b.jar", "mods/a.jar"]


def test_dump_lockfile_golden_bytes() -> None:
    lf = LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )
    expected = (
        b'{\n'
        b'  "format": 2,\n'
        b'  "mc": "1.20.4",\n'
        b'  "loader": {\n'
        b'    "id": "paper",\n'
        b'    "version": "499"\n'
        b'  },\n'
        b'  "base_overrides": {},\n'
        b'  "files": []\n'
        b'}\n'
    )
    assert dump_lockfile(lf) == expected


# --- 8. Error Secrecy ---


def test_error_secrecy_sentinels() -> None:
    sentinel_source = "SECRET_SOURCE_TOKEN_12345"
    sentinel_proj = "SECRET_PROJ_99999"
    sentinel_ver = "SECRET_VER_88888"
    sentinel_label = "SECRET_LABEL_77777"

    # Inject forbidden control character into sentinel label
    with pytest.raises(LockfileInvalidError) as exc_info:
        ModpackRef(
            source=sentinel_source,
            project_id=sentinel_proj,
            version_id=sentinel_ver,
            version_label=sentinel_label + "\x00",
            index_sha256=SAMPLE_SHA256,
        )
    err_str = str(exc_info.value)
    err_repr = repr(exc_info.value)
    assert sentinel_label not in err_str
    assert sentinel_label not in err_repr
    assert sentinel_source not in err_str
    assert sentinel_proj not in err_str
    assert sentinel_ver not in err_str


def test_error_details_bounded_10k_sentinel() -> None:
    sentinel = "PLANTED_SECRET_SENTINEL_98765"

    # (a) rejected 10k-char path (invalid shape, e.g. traversal segment at end)
    long_path = "mods/" + "p" * 5000 + sentinel + "q" * 5000 + "/../bad"
    doc_a = make_valid_doc()
    doc_a["files"][0]["path"] = long_path
    with pytest.raises(LockfileInvalidError) as exc_a:
        parse_lockfile(json.dumps(doc_a).encode("utf-8"))

    # (b) 10k duplicate JSON key
    k_b = "dup_" + "d" * 5000 + sentinel + "e" * 5000
    raw_b = (
        f'{{"format": 2, "mc": "1.20.4", "loader": {{"id": "paper", "version": "499"}}, '
        f'"base_overrides": {{}}, "files": [], "{k_b}": 1, "{k_b}": 2}}'
    ).encode()
    with pytest.raises(LockfileInvalidError) as exc_b:
        parse_lockfile(raw_b)

    # (c) 10k unknown top-level key
    k_c = "unk_" + "u" * 5000 + sentinel + "v" * 5000
    raw_c = (
        f'{{"format": 2, "mc": "1.20.4", "loader": {{"id": "paper", "version": "499"}}, '
        f'"base_overrides": {{}}, "files": [], "{k_c}": 1}}'
    ).encode()
    with pytest.raises(LockfileInvalidError) as exc_c:
        parse_lockfile(raw_c)

    # (d) 10k casefold-collision pair
    p1 = "mods/" + "c" * 5000 + sentinel + "w" * 5000 + ".jar"
    p2 = "mods/" + "C" * 5000 + sentinel + "w" * 5000 + ".jar"
    doc_d = make_valid_doc()
    doc_d["files"] = [
        {
            "path": p1,
            "sha256": SAMPLE_SHA256,
            "size": 10,
            "optional": False,
            "env_server": "required",
            "origin": "override",
        },
        {
            "path": p2,
            "sha256": SAMPLE_SHA256,
            "size": 10,
            "optional": False,
            "env_server": "required",
            "origin": "override",
        },
    ]
    with pytest.raises(CaseCollisionError) as exc_d:
        parse_lockfile(json.dumps(doc_d).encode("utf-8"))

    for exc in (exc_a.value, exc_b.value, exc_c.value, exc_d.value):
        s = str(exc)
        r = repr(exc)
        assert len(s) < 1000
        assert sentinel not in s
        assert sentinel not in r
        if hasattr(exc, "details") and exc.details:
            for v in exc.details.values():
                if isinstance(v, str):
                    assert len(v) <= 128
                    assert sentinel not in v
