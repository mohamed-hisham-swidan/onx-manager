from __future__ import annotations

import difflib
import json
import tomllib
from dataclasses import dataclass
from typing import Any

import tomli_w
import yaml

from app.modules.versioning.domain.lockfile import (
    LockfileV21,
    dump_lockfile,
    parse_lockfile,
)
from app.modules.versioning.infrastructure.secret_scanner import redact_conflict_value

SET_MERGEABLE_ARRAY_KEYS: frozenset[tuple[str, str]] = frozenset(
    {
        ("config/paper-global.yml", "MidTickChunkTasks.worlds"),
        ("spigot.yml", "commands.silent-commandblock-console-worlds"),
    }
)

STRUCTURED_EXTENSIONS: frozenset[str] = frozenset(
    {".yml", ".yaml", ".toml", ".json", ".properties"}
)

TEXT_DIFF3_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".json5",
        ".snbt",
        ".cfg",
        ".conf",
        ".js",
        ".zs",
        ".sk",
        ".dsc",
        ".mcfunction",
        ".txt",
        ".lang",
        ".mcmeta",
        ".xml",
    }
)

from app.core.allowlist import CLASS_D_PANEL_KEYS as _ALLOWLIST_CLASS_D  # noqa: E402

CLASS_D_PANEL_KEYS = _ALLOWLIST_CLASS_D


@dataclass(frozen=True)
class MergeConflictItem:
    path: str
    key_path: str
    reason: str
    base: Any
    ours: Any
    theirs: Any

    def to_dict(self) -> dict[str, Any]:
        import dataclasses
        from datetime import date, datetime, time

        def _safe(v):
            if dataclasses.is_dataclass(v) and not isinstance(v, type):
                return dataclasses.asdict(v)
            if isinstance(v, (datetime, date, time)):
                return v.isoformat()
            if isinstance(v, bytes):
                try:
                    return v.decode("utf-8")
                except UnicodeDecodeError:
                    return f"<bytes:{len(v)}>"
            return v

        return {
            "path": self.path,
            "key_path": self.key_path,
            "reason": self.reason,
            "base": _safe(self.base),
            "ours": _safe(self.ours),
            "theirs": _safe(self.theirs),
        }


@dataclass(frozen=True)
class FileMergeOutcome:
    path: str
    content: bytes | None
    conflicts: tuple[MergeConflictItem, ...] = ()
    warnings: tuple[str, ...] = ()
    used_strategy: str = ""


def _ast_equal(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        if isinstance(a, bool) or isinstance(b, bool):
            return False
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a == b
        return False
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_ast_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return False
        return all(_ast_equal(x, y) for x, y in zip(a, b))  # noqa: B905
    return a == b


def _canonical_ast_equal(a: Any, b: Any) -> bool:
    """Compare two parsed document ASTs using type-aware equality."""
    return _ast_equal(a, b)


def _normalize_server_properties(data: bytes) -> bytes | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    lines_out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        key = None
        val = None
        if "=" in line:
            k, v = line.split("=", 1)
            key, val = k.strip(), v.strip()
        elif ":" in line:
            k, v = line.split(":", 1)
            key, val = k.strip(), v.strip()
        else:
            return None
        if key in CLASS_D_PANEL_KEYS or key.startswith("management-server-"):
            continue
        lines_out.append(f"{key}={val}")
    lines_out.sort()
    return ("\n".join(lines_out) + ("\n" if lines_out else "")).encode("utf-8")


def _parse_properties_dict(text: str) -> dict[str, str] | None:
    result: dict[str, str] = {}
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
        elif ":" in line:
            k, v = line.split(":", 1)
        else:
            return None
        result[k.strip()] = v.strip()
    return result


def _parse_structured(relpath: str, data: bytes) -> tuple[Any, str] | None:
    lowered = relpath.lower()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if lowered.endswith((".yml", ".yaml")):
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            return None
        if doc is None:
            doc = {}
        return doc, "yaml"
    if lowered.endswith(".toml"):
        try:
            doc = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return None
        return doc, "toml"
    if lowered.endswith(".json"):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            return None
        return doc, "json"
    if lowered.endswith(".properties"):
        if relpath.endswith("server.properties"):
            nb = _normalize_server_properties(data)
            if nb is None:
                return None
            d = _parse_properties_dict(nb.decode("utf-8"))
            if d is None:
                return None
            return d, "properties"
        d = _parse_properties_dict(text)
        if d is None:
            return None
        return d, "properties"
    return None


def _dump_structured(fmt: str, ast: Any) -> bytes:
    if fmt == "yaml":
        out = yaml.safe_dump(ast, sort_keys=False, allow_unicode=True)
        return out.encode("utf-8")
    if fmt == "toml":
        out = tomli_w.dumps(ast)
        return out.encode("utf-8")
    if fmt == "json":
        out = json.dumps(ast, indent=2, ensure_ascii=False) + "\n"
        return out.encode("utf-8")
    if fmt == "properties":
        if isinstance(ast, dict):
            lines = sorted(f"{k}={v}" for k, v in ast.items())
            out = "\n".join(lines) + ("\n" if lines else "")
            return out.encode("utf-8")
        return b""
    return b""


def _is_object_array(b, o, t) -> tuple[bool, str | None]:
    lists = [x for x in (b, o, t) if isinstance(x, list)]
    all_elems: list[Any] = []
    for lst in lists:
        all_elems.extend(lst)
    if not all_elems:
        return False, None
    for el in all_elems:
        if el == {}:
            continue
        if el is None:
            return False, None
        if not isinstance(el, dict):
            return False, None
    for pk in ("id", "name", "modid", "Id"):
        ok = True
        for lst in lists:
            if not isinstance(lst, list):
                continue
            seen = set()
            for el in lst:
                if not isinstance(el, dict):
                    ok = False
                    break
                if el == {}:
                    ok = False
                    break
                if pk not in el:
                    ok = False
                    break
                val = el[pk]
                if isinstance(val, bool) or not isinstance(val, (str, int)):
                    ok = False
                    break
                if val is None:
                    ok = False
                    break
                if val in seen:
                    ok = False
                    break
                seen.add(val)
            if not ok:
                break
        if ok:
            for el in all_elems:
                if isinstance(el, dict) and el not in ({}, None):  # noqa: SIM102
                    if pk not in el:
                        ok = False
                        break
            if ok and any(isinstance(x, list) and len(x) > 0 for x in (b, o, t)):
                return True, pk
    return False, None


def _merge_ast_value(relpath, key_path, base, ours, theirs, conflicts, *, set_mergeable_array_keys):
    if isinstance(base, dict) and isinstance(ours, dict) and isinstance(theirs, dict):
        result = {}
        union = set(base) | set(ours) | set(theirs)
        ordered = [k for k in list(ours.keys()) if k in union]
        for k in list(theirs.keys()):
            if k in union and k not in ordered:
                ordered.append(k)
        for k in list(base.keys()):
            if k in union and k not in ordered:
                ordered.append(k)
        for k in ordered:
            if k not in union:
                continue
            child_kp = f"{key_path}.{k}" if key_path else str(k)
            in_b = k in base
            in_o = k in ours
            in_t = k in theirs
            if in_b and not in_o and not in_t:
                continue
            if (not in_b) and in_o and (not in_t):
                result[k] = ours[k]
                continue
            if (not in_b) and (not in_o) and in_t:
                result[k] = theirs[k]
                continue
            if (not in_b) and in_o and in_t:
                if _ast_equal(ours[k], theirs[k]):
                    result[k] = ours[k]
                elif isinstance(ours[k], dict) and isinstance(theirs[k], dict):
                    result[k] = _merge_ast_value(
                        relpath,
                        child_kp,
                        {},
                        ours[k],
                        theirs[k],
                        conflicts,
                        set_mergeable_array_keys=set_mergeable_array_keys,
                    )
                else:
                    conflicts.append(
                        MergeConflictItem(
                            path=relpath,
                            key_path=child_kp,
                            reason="scalar-conflict"
                            if type(ours[k]) is type(theirs[k])
                            else "type-mismatch",
                            base=redact_conflict_value(relpath, child_kp, None),
                            ours=redact_conflict_value(relpath, child_kp, ours[k]),
                            theirs=redact_conflict_value(relpath, child_kp, theirs[k]),
                        )
                    )
                continue
            if in_b and not in_o and in_t:
                if _ast_equal(theirs[k], base[k]):
                    continue
                else:
                    conflicts.append(
                        MergeConflictItem(
                            path=relpath,
                            key_path=child_kp,
                            reason="delete-modify-conflict",
                            base=redact_conflict_value(relpath, child_kp, base[k]),
                            ours=redact_conflict_value(relpath, child_kp, None),
                            theirs=redact_conflict_value(relpath, child_kp, theirs[k]),
                        )
                    )
                continue
            if in_b and in_o and not in_t:
                if _ast_equal(ours[k], base[k]):
                    continue
                else:
                    conflicts.append(
                        MergeConflictItem(
                            path=relpath,
                            key_path=child_kp,
                            reason="delete-modify-conflict",
                            base=redact_conflict_value(relpath, child_kp, base[k]),
                            ours=redact_conflict_value(relpath, child_kp, ours[k]),
                            theirs=redact_conflict_value(relpath, child_kp, None),
                        )
                    )
                continue
            if in_b and in_o and in_t:
                result[k] = _merge_ast_value(
                    relpath,
                    child_kp,
                    base[k],
                    ours[k],
                    theirs[k],
                    conflicts,
                    set_mergeable_array_keys=set_mergeable_array_keys,
                )
                continue
        return result

    if isinstance(base, list) and isinstance(ours, list) and isinstance(theirs, list):
        b_list, o_list, t_list = base, ours, theirs
        is_obj, pk = _is_object_array(b_list, o_list, t_list)
        if is_obj and pk is not None:
            b_map = {el[pk]: el for el in b_list if isinstance(el, dict) and pk in el}
            o_map = {el[pk]: el for el in o_list if isinstance(el, dict) and pk in el}
            t_map = {el[pk]: el for el in t_list if isinstance(el, dict) and pk in el}
            ordered_pks = [e[pk] for e in o_list if isinstance(e, dict)]
            for e in t_list:
                if isinstance(e, dict) and e[pk] not in ordered_pks:
                    ordered_pks.append(e[pk])
            result_list = []
            for pk_val in ordered_pks:
                in_b = pk_val in b_map
                in_o = pk_val in o_map
                in_t = pk_val in t_map
                child_kp = f"{key_path}[{pk}={pk_val}]"
                if in_b and not in_o and not in_t:
                    continue
                if (not in_b) and in_o and (not in_t):
                    result_list.append(o_map[pk_val])
                    continue
                if (not in_b) and (not in_o) and in_t:
                    result_list.append(t_map[pk_val])
                    continue
                if (not in_b) and in_o and in_t:
                    merged_el = _merge_ast_value(
                        relpath,
                        child_kp,
                        {},
                        o_map[pk_val],
                        t_map[pk_val],
                        conflicts,
                        set_mergeable_array_keys=set_mergeable_array_keys,
                    )
                    result_list.append(merged_el)
                    continue
                if in_b and not in_o and in_t:
                    if _ast_equal(t_map[pk_val], b_map[pk_val]):
                        continue
                    else:
                        conflicts.append(
                            MergeConflictItem(
                                path=relpath,
                                key_path=child_kp,
                                reason="object-array-conflict",
                                base=redact_conflict_value(relpath, child_kp, b_map[pk_val]),
                                ours=redact_conflict_value(relpath, child_kp, None),
                                theirs=redact_conflict_value(relpath, child_kp, t_map[pk_val]),
                            )
                        )
                    continue
                if in_b and in_o and not in_t:
                    if _ast_equal(o_map[pk_val], b_map[pk_val]):
                        continue
                    else:
                        conflicts.append(
                            MergeConflictItem(
                                path=relpath,
                                key_path=child_kp,
                                reason="object-array-conflict",
                                base=redact_conflict_value(relpath, child_kp, b_map[pk_val]),
                                ours=redact_conflict_value(relpath, child_kp, o_map[pk_val]),
                                theirs=redact_conflict_value(relpath, child_kp, None),
                            )
                        )
                    continue
                if in_b and in_o and in_t:
                    merged_el = _merge_ast_value(
                        relpath,
                        child_kp,
                        b_map[pk_val],
                        o_map[pk_val],
                        t_map[pk_val],
                        conflicts,
                        set_mergeable_array_keys=set_mergeable_array_keys,
                    )
                    result_list.append(merged_el)
                    continue
            return result_list

        if (relpath, key_path) in set_mergeable_array_keys:
            scalars = all(
                isinstance(x, (str, int, float, bool)) and not isinstance(x, (dict, list, tuple))
                for x in (b_list + o_list + t_list)
            )
            if scalars:
                b_keys = {(type(x), x) for x in b_list}
                removed_by_t = b_keys - {(type(x), x) for x in t_list}
                seen = set()
                result_list = []
                for x in o_list:
                    kx = (type(x), x)
                    if kx in removed_by_t:
                        continue
                    if kx in seen:
                        continue
                    seen.add(kx)
                    result_list.append(x)
                for x in t_list:
                    kx = (type(x), x)
                    if kx in b_keys:
                        continue
                    if kx in seen:
                        continue
                    seen.add(kx)
                    result_list.append(x)
                return result_list

        if _ast_equal(o_list, b_list):
            return list(t_list)
        if _ast_equal(t_list, b_list):
            return list(o_list)
        if _ast_equal(o_list, t_list):
            return list(o_list)
        reason = "scalar-array-conflict"
        all_elems = b_list + o_list + t_list
        if all_elems and all(isinstance(e, dict) for e in all_elems):
            reason = "object-array-conflict"
        conflicts.append(
            MergeConflictItem(
                path=relpath,
                key_path=key_path,
                reason=reason,
                base=redact_conflict_value(relpath, key_path, b_list),
                ours=redact_conflict_value(relpath, key_path, o_list),
                theirs=redact_conflict_value(relpath, key_path, t_list),
            )
        )
        return list(o_list)

    # scalars (including None, mismatched types)
    if _ast_equal(ours, base):
        return theirs
    if _ast_equal(theirs, base):
        return ours
    if _ast_equal(ours, theirs):
        return ours
    if type(ours) is not type(theirs):  # noqa: SIM108
        reason = "type-mismatch"
    else:
        reason = "scalar-conflict"
    conflicts.append(
        MergeConflictItem(
            path=relpath,
            key_path=key_path,
            reason=reason,
            base=redact_conflict_value(relpath, key_path, base),
            ours=redact_conflict_value(relpath, key_path, ours),
            theirs=redact_conflict_value(relpath, key_path, theirs),
        )
    )
    return ours


def merge_text_diff3(relpath, base_bytes, ours_bytes, theirs_bytes):
    if ours_bytes == theirs_bytes:
        return FileMergeOutcome(
            path=relpath, content=ours_bytes, conflicts=(), warnings=(), used_strategy="diff3-text"
        )
    if ours_bytes == base_bytes:
        return FileMergeOutcome(
            path=relpath,
            content=theirs_bytes,
            conflicts=(),
            warnings=(),
            used_strategy="diff3-text",
        )
    if theirs_bytes == base_bytes:
        return FileMergeOutcome(
            path=relpath, content=ours_bytes, conflicts=(), warnings=(), used_strategy="diff3-text"
        )

    b_text = base_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    o_text = ours_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    t_text = (
        theirs_bytes.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    )
    B = b_text.splitlines(keepends=True)  # noqa: N806
    O = o_text.splitlines(keepends=True)  # noqa: E741,N806
    T = t_text.splitlines(keepends=True)  # noqa: N806

    def changed_intervals(base_lines, other_lines):
        sm = difflib.SequenceMatcher(None, base_lines, other_lines)
        intervals = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            intervals.append((i1, i2, list(other_lines[j1:j2])))
        return intervals

    o_intervals = changed_intervals(B, O)
    t_intervals = changed_intervals(B, T)

    out_lines = []
    conf_list = []
    base_idx = 0

    def overlaps(iv, ss, se):
        s, e, _ = iv
        if s == e:
            # Zero-width insertion: anchored insertions at the cluster's
            # start boundary are part of the cluster (conflict, like git),
            # while insertions at the end boundary stay clean appends.
            return ss <= s < se or (ss == se == s)
        return not (e <= ss or s >= se)

    while base_idx <= len(B):
        o_cov = [
            iv for iv in o_intervals if iv[0] <= base_idx < iv[1] or (iv[0] == iv[1] == base_idx)
        ]
        t_cov = [
            iv for iv in t_intervals if iv[0] <= base_idx < iv[1] or (iv[0] == iv[1] == base_idx)
        ]
        if not o_cov and not t_cov:
            if base_idx < len(B):
                out_lines.append(B[base_idx])
            base_idx += 1
            continue
        cluster_o = list(o_cov)
        cluster_t = list(t_cov)
        span_start = min([iv[0] for iv in cluster_o + cluster_t])
        span_end = max([iv[1] for iv in cluster_o + cluster_t])
        while True:
            new_o = [iv for iv in o_intervals if overlaps(iv, span_start, span_end)]
            new_t = [iv for iv in t_intervals if overlaps(iv, span_start, span_end)]
            new_ss = min([iv[0] for iv in new_o + new_t])
            new_se = max([iv[1] for iv in new_o + new_t])
            if (
                new_ss == span_start
                and new_se == span_end
                and len(new_o) == len(cluster_o)
                and len(new_t) == len(cluster_t)
            ):
                cluster_o = new_o
                cluster_t = new_t
                break
            span_start, span_end = new_ss, new_se
            cluster_o = new_o
            cluster_t = new_t

        while base_idx < span_start:
            if base_idx < len(B):
                out_lines.append(B[base_idx])
            base_idx += 1

        o_repls = []
        for iv in sorted(cluster_o):
            o_repls.extend(iv[2])
        t_repls = []
        for iv in sorted(cluster_t):
            t_repls.extend(iv[2])
        base_slice = B[span_start:span_end]
        # remove processed intervals to ensure progress
        for iv in cluster_o:
            if iv in o_intervals:
                o_intervals.remove(iv)
        for iv in cluster_t:
            if iv in t_intervals:
                t_intervals.remove(iv)

        if cluster_o and not cluster_t:
            out_lines.extend(o_repls)
            base_idx = span_end
            continue
        if cluster_t and not cluster_o:
            out_lines.extend(t_repls)
            base_idx = span_end
            continue
        if o_repls == t_repls:
            out_lines.extend(o_repls)
            base_idx = span_end
            continue
        key_path = f"lines:{span_start + 1}-{max(span_start + 1, span_end)}"
        conf_list.append(
            MergeConflictItem(
                path=relpath,
                key_path=key_path,
                reason="text-hunk-conflict",
                base=redact_conflict_value(relpath, key_path, "".join(base_slice)),
                ours=redact_conflict_value(relpath, key_path, "".join(o_repls)),
                theirs=redact_conflict_value(relpath, key_path, "".join(t_repls)),
            )
        )
        out_lines.extend(o_repls)
        base_idx = span_end
        continue

    content = "".join(out_lines).encode("utf-8")
    return FileMergeOutcome(
        path=relpath,
        content=content,
        conflicts=tuple(conf_list),
        warnings=(),
        used_strategy="diff3-text",
    )


def merge_structured_config(relpath, base_bytes, ours_bytes, theirs_bytes, *, set_mergeable_array_keys=SET_MERGEABLE_ARRAY_KEYS):  # noqa: E501
    return merge_class_b_file(relpath, base_bytes, ours_bytes, theirs_bytes, set_mergeable_array_keys=set_mergeable_array_keys)  # noqa: E501




def merge_lockfile_bytes(relpath, base_bytes, ours_bytes, theirs_bytes):
    _WARN = f"'{relpath}': structured parse failed during merge; kept target ('ours') bytes untouched"  # noqa: E501,N806

    def _validate(bs):
        if bs is None:
            return None
        try:
            lf = parse_lockfile(bytes(bs))
            dumped = dump_lockfile(lf)
            return dumped if isinstance(dumped, bytes) else dumped.encode("utf-8")
        except Exception:
            return None

    if ours_bytes == theirs_bytes:
        v = _validate(ours_bytes)
        if v is not None:
            return FileMergeOutcome(path=relpath, content=v, conflicts=(), warnings=(), used_strategy="lockfile")  # noqa: E501
        return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=(_WARN,), used_strategy="ours-fallback")  # noqa: E501
    if base_bytes is not None and ours_bytes == base_bytes:
        v = _validate(theirs_bytes)
        if v is not None:
            return FileMergeOutcome(path=relpath, content=v, conflicts=(), warnings=(), used_strategy="lockfile")  # noqa: E501
        return FileMergeOutcome(path=relpath, content=theirs_bytes if theirs_bytes is not None else None, conflicts=(), warnings=(_WARN,), used_strategy="ours-fallback")  # noqa: E501
    if base_bytes is not None and theirs_bytes == base_bytes:
        v = _validate(ours_bytes)
        if v is not None:
            return FileMergeOutcome(path=relpath, content=v, conflicts=(), warnings=(), used_strategy="lockfile")  # noqa: E501
        return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=(_WARN,), used_strategy="ours-fallback")  # noqa: E501

    def _parse(b):
        if b is None:
            return None
        try:
            return parse_lockfile(bytes(b))
        except Exception:
            return None

    base_lf = _parse(base_bytes)
    ours_lf = _parse(ours_bytes)
    theirs_lf = _parse(theirs_bytes)

    conflicts = []

    if base_bytes is None and ours_bytes is None and theirs_bytes is not None:
        v = _validate(theirs_bytes)
        if v is not None:
            return FileMergeOutcome(path=relpath, content=v, conflicts=(), warnings=(), used_strategy="fast-forward")  # noqa: E501
        return FileMergeOutcome(path=relpath, content=theirs_bytes, conflicts=(), warnings=(_WARN,), used_strategy="ours-fallback")  # noqa: E501
    if base_bytes is None and theirs_bytes is None and ours_bytes is not None:
        v = _validate(ours_bytes)
        if v is not None:
            return FileMergeOutcome(path=relpath, content=v, conflicts=(), warnings=(), used_strategy="fast-forward")  # noqa: E501
        return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=(_WARN,), used_strategy="ours-fallback")  # noqa: E501
    if ours_bytes is None and theirs_bytes is not None:
        if base_bytes is not None and theirs_bytes == base_bytes:
            return FileMergeOutcome(path=relpath, content=None, conflicts=(), warnings=(), used_strategy="lockfile")  # noqa: E501
        conflicts.append(MergeConflictItem(path=relpath, key_path="", reason="delete-modify-conflict",  # noqa: E501
            base=redact_conflict_value(relpath, "", base_bytes.decode("utf-8", "replace") if base_bytes else None),  # noqa: E501
            ours=None,
            theirs=redact_conflict_value(relpath, "", theirs_bytes.decode("utf-8", "replace") if theirs_bytes else None)))  # noqa: E501
        return FileMergeOutcome(path=relpath, content=None, conflicts=tuple(conflicts), warnings=(), used_strategy="lockfile")  # noqa: E501
    if theirs_bytes is None and ours_bytes is not None:
        if base_bytes is not None and ours_bytes == base_bytes:
            return FileMergeOutcome(path=relpath, content=None, conflicts=(), warnings=(), used_strategy="lockfile")  # noqa: E501
        conflicts.append(MergeConflictItem(path=relpath, key_path="", reason="delete-modify-conflict",  # noqa: E501
            base=redact_conflict_value(relpath, "", base_bytes.decode("utf-8", "replace") if base_bytes else None),  # noqa: E501
            ours=redact_conflict_value(relpath, "", ours_bytes.decode("utf-8", "replace") if ours_bytes else None),  # noqa: E501
            theirs=None))
        return FileMergeOutcome(path=relpath, content=None, conflicts=tuple(conflicts), warnings=(), used_strategy="lockfile")  # noqa: E501
    if ours_bytes is None and theirs_bytes is None:
        return FileMergeOutcome(path=relpath, content=None, conflicts=(), warnings=(), used_strategy="lockfile")  # noqa: E501

    if base_lf is None or ours_lf is None or theirs_lf is None:
        warnings = [f"'{relpath}': structured parse failed during merge; kept target ('ours') bytes untouched"]  # noqa: E501
        return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=tuple(warnings), used_strategy="ours-fallback")  # noqa: E501

    # merge top-level scalar fields
    _CONFLICT = object()  # noqa: N806
    def merge_scalar_field(name):
        b = getattr(base_lf, name, None)
        o = getattr(ours_lf, name, None)
        t = getattr(theirs_lf, name, None)
        if _ast_equal(o, b):
            return t
        if _ast_equal(t, b):
            return o
        if _ast_equal(o, t):
            return o
        return _CONFLICT

    scalar_fields = ["mc", "loader", "lec", "modpack", "format"]
    merged_values = {}
    for f in scalar_fields:
        r = merge_scalar_field(f)
        b = getattr(base_lf, f, None)
        o = getattr(ours_lf, f, None)
        t = getattr(theirs_lf, f, None)
        if r is _CONFLICT and not (_ast_equal(o, t)):
            if not (_ast_equal(o, b) or _ast_equal(t, b) or _ast_equal(o, t)):
                conflicts.append(MergeConflictItem(path=relpath, key_path=f, reason="lockfile-conflict",  # noqa: E501
                    base=redact_conflict_value(relpath, f, b),
                    ours=redact_conflict_value(relpath, f, o),
                    theirs=redact_conflict_value(relpath, f, t)))
            merged_values[f] = o
        else:
            merged_values[f] = o if r is _CONFLICT else r

    base_bo = getattr(base_lf, "base_overrides", {}) or {}
    ours_bo = getattr(ours_lf, "base_overrides", {}) or {}
    theirs_bo = getattr(theirs_lf, "base_overrides", {}) or {}
    merged_bo = dict(ours_bo)
    all_bo_keys = set(base_bo) | set(ours_bo) | set(theirs_bo)
    for k in all_bo_keys:
        in_b = k in base_bo
        in_o = k in ours_bo
        in_t = k in theirs_bo
        if in_b and not in_o and not in_t:
            merged_bo.pop(k, None)
            continue
        if (not in_b) and in_o and (not in_t):
            merged_bo[k] = ours_bo[k]
            continue
        if (not in_b) and (not in_o) and in_t:
            merged_bo[k] = theirs_bo[k]
            continue
        if (not in_b) and in_o and in_t:
            if _ast_equal(ours_bo[k], theirs_bo[k]):
                merged_bo[k] = ours_bo[k]
            else:
                conflicts.append(MergeConflictItem(path=relpath, key_path=f"base_overrides.{k}", reason="lockfile-conflict",  # noqa: E501
                    base=redact_conflict_value(relpath, f"base_overrides.{k}", None),
                    ours=redact_conflict_value(relpath, f"base_overrides.{k}", ours_bo.get(k)),
                    theirs=redact_conflict_value(relpath, f"base_overrides.{k}", theirs_bo.get(k))))
            continue
        if in_b and not in_o and in_t:
            if _ast_equal(theirs_bo.get(k), base_bo.get(k)):
                merged_bo.pop(k, None)
            else:
                conflicts.append(MergeConflictItem(path=relpath, key_path=f"base_overrides.{k}", reason="lockfile-conflict",  # noqa: E501
                    base=redact_conflict_value(relpath, f"base_overrides.{k}", base_bo.get(k)),
                    ours=None,
                    theirs=redact_conflict_value(relpath, f"base_overrides.{k}", theirs_bo.get(k))))
            continue
        if in_b and in_o and not in_t:
            if _ast_equal(ours_bo.get(k), base_bo.get(k)):
                merged_bo.pop(k, None)
            else:
                conflicts.append(MergeConflictItem(path=relpath, key_path=f"base_overrides.{k}", reason="lockfile-conflict",  # noqa: E501
                    base=redact_conflict_value(relpath, f"base_overrides.{k}", base_bo.get(k)),
                    ours=redact_conflict_value(relpath, f"base_overrides.{k}", ours_bo.get(k)),
                    theirs=None))
            continue
        if in_b and in_o and in_t:
            b = base_bo.get(k)
            o = ours_bo.get(k)
            t = theirs_bo.get(k)
            if _ast_equal(o, b):
                merged_bo[k] = t
            elif _ast_equal(t, b) or _ast_equal(o, t):
                merged_bo[k] = o
            else:
                conflicts.append(MergeConflictItem(path=relpath, key_path=f"base_overrides.{k}", reason="lockfile-conflict",  # noqa: E501
                    base=redact_conflict_value(relpath, f"base_overrides.{k}", b),
                    ours=redact_conflict_value(relpath, f"base_overrides.{k}", o),
                    theirs=redact_conflict_value(relpath, f"base_overrides.{k}", t)))

    def files_map(lf):
        m = {}
        for f in getattr(lf, "files", ()) or ():
            m[getattr(f, "path", None)] = f
        return m

    base_fm = files_map(base_lf)
    ours_fm = files_map(ours_lf)
    theirs_fm = files_map(theirs_lf)
    merged_files_list = []
    all_file_paths = set(base_fm) | set(ours_fm) | set(theirs_fm)
    for pth in all_file_paths:
        in_b = pth in base_fm
        in_o = pth in ours_fm
        in_t = pth in theirs_fm
        if in_b and not in_o and not in_t:
            continue
        if (not in_b) and in_o and (not in_t):
            merged_files_list.append(ours_fm[pth])
            continue
        if (not in_b) and (not in_o) and in_t:
            merged_files_list.append(theirs_fm[pth])
            continue
        if (not in_b) and in_o and in_t:
            if _ast_equal(ours_fm[pth], theirs_fm[pth]):
                merged_files_list.append(ours_fm[pth])
            else:
                conflicts.append(MergeConflictItem(path=relpath, key_path=f"files[{pth}]", reason="lockfile-conflict",  # noqa: E501
                    base=None,
                    ours=redact_conflict_value(relpath, f"files[{pth}]", ours_fm[pth]),
                    theirs=redact_conflict_value(relpath, f"files[{pth}]", theirs_fm[pth])))
            continue
        if in_b and not in_o and in_t:
            if _ast_equal(theirs_fm[pth], base_fm[pth]):
                continue
            else:
                conflicts.append(MergeConflictItem(path=relpath, key_path=f"files[{pth}]", reason="lockfile-conflict",  # noqa: E501
                    base=redact_conflict_value(relpath, f"files[{pth}]", base_fm[pth]),
                    ours=None,
                    theirs=redact_conflict_value(relpath, f"files[{pth}]", theirs_fm[pth])))
            continue
        if in_b and in_o and not in_t:
            if _ast_equal(ours_fm[pth], base_fm[pth]):
                continue
            else:
                conflicts.append(MergeConflictItem(path=relpath, key_path=f"files[{pth}]", reason="lockfile-conflict",  # noqa: E501
                    base=redact_conflict_value(relpath, f"files[{pth}]", base_fm[pth]),
                    ours=redact_conflict_value(relpath, f"files[{pth}]", ours_fm[pth]),
                    theirs=None))
            continue
        if in_b and in_o and in_t:
            o = ours_fm[pth]
            t = theirs_fm[pth]
            b = base_fm[pth]
            if _ast_equal(o, b):
                merged_files_list.append(t)
            elif _ast_equal(t, b) or _ast_equal(o, t):
                merged_files_list.append(o)
            else:
                conflicts.append(MergeConflictItem(path=relpath, key_path=f"files[{pth}]", reason="lockfile-conflict",  # noqa: E501
                    base=redact_conflict_value(relpath, f"files[{pth}]", b),
                    ours=redact_conflict_value(relpath, f"files[{pth}]", o),
                    theirs=redact_conflict_value(relpath, f"files[{pth}]", t)))

    if conflicts:
        return FileMergeOutcome(path=relpath, content=None, conflicts=tuple(conflicts), warnings=(), used_strategy="lockfile")  # noqa: E501

    try:
        merged_lf = LockfileV21(
            format=merged_values.get("format", ours_lf.format),
            mc=merged_values.get("mc", ours_lf.mc),
            loader=merged_values.get("loader", ours_lf.loader),
            lec=merged_values.get("lec", ours_lf.lec),
            modpack=merged_values.get("modpack", ours_lf.modpack),
            base_overrides=merged_bo,
            files=tuple(merged_files_list),
        )
    except Exception:
        return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=(_WARN,), used_strategy="ours-fallback")  # noqa: E501

    try:
        out = dump_lockfile(merged_lf)
    except Exception:
        return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=(_WARN,), used_strategy="ours-fallback")  # noqa: E501
    return FileMergeOutcome(path=relpath, content=out, conflicts=(), warnings=(), used_strategy="lockfile")  # noqa: E501


def merge_class_b_file(relpath, base_bytes, ours_bytes, theirs_bytes, *, set_mergeable_array_keys=SET_MERGEABLE_ARRAY_KEYS):  # noqa: E501
    if ours_bytes is None and theirs_bytes is None:
        return FileMergeOutcome(path=relpath, content=None, conflicts=(), warnings=(), used_strategy="deleted")  # noqa: E501
    if ours_bytes is None and (theirs_bytes == base_bytes if base_bytes is not None else False):
        return FileMergeOutcome(path=relpath, content=None, conflicts=(), warnings=(), used_strategy="deleted")  # noqa: E501
    if theirs_bytes is None and (ours_bytes == base_bytes if base_bytes is not None else False):
        return FileMergeOutcome(path=relpath, content=None, conflicts=(), warnings=(), used_strategy="deleted")  # noqa: E501
    if base_bytes is None and ours_bytes is None and theirs_bytes is not None:
        return FileMergeOutcome(path=relpath, content=theirs_bytes, conflicts=(), warnings=(), used_strategy="fast-forward")  # noqa: E501
    if base_bytes is None and theirs_bytes is None and ours_bytes is not None:
        return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=(), used_strategy="fast-forward")  # noqa: E501
    if ours_bytes is None and theirs_bytes is not None and (base_bytes is None or theirs_bytes != base_bytes):  # noqa: E501
        conflicts = [MergeConflictItem(path=relpath, key_path="", reason="delete-modify-conflict",
            base=redact_conflict_value(relpath, "", base_bytes.decode("utf-8", "replace") if base_bytes else None),  # noqa: E501
            ours=None,
            theirs=redact_conflict_value(relpath, "", theirs_bytes.decode("utf-8", "replace")))]
        return FileMergeOutcome(path=relpath, content=None, conflicts=tuple(conflicts), warnings=(), used_strategy="deleted")  # noqa: E501
    if theirs_bytes is None and ours_bytes is not None and (base_bytes is None or ours_bytes != base_bytes):  # noqa: E501
        conflicts = [MergeConflictItem(path=relpath, key_path="", reason="delete-modify-conflict",
            base=redact_conflict_value(relpath, "", base_bytes.decode("utf-8", "replace") if base_bytes else None),  # noqa: E501
            ours=redact_conflict_value(relpath, "", ours_bytes.decode("utf-8", "replace")),
            theirs=None)]
        return FileMergeOutcome(path=relpath, content=None, conflicts=tuple(conflicts), warnings=(), used_strategy="deleted")  # noqa: E501

    if ours_bytes == theirs_bytes:
        return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=(), used_strategy="fast-forward")  # noqa: E501
    if base_bytes is not None and ours_bytes == base_bytes:
        return FileMergeOutcome(path=relpath, content=theirs_bytes, conflicts=(), warnings=(), used_strategy="fast-forward")  # noqa: E501
    if base_bytes is not None and theirs_bytes == base_bytes:
        return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=(), used_strategy="fast-forward")  # noqa: E501

    lowered = relpath.lower()
    if relpath == "onx-jars.lock.json":
        return merge_lockfile_bytes(relpath, base_bytes, ours_bytes, theirs_bytes)

    if lowered == "server-icon.png":
        conflicts = [MergeConflictItem(path=relpath, key_path="", reason="binary-conflict",
            base=f"<binary:{len(base_bytes) if base_bytes else 0} bytes>",
            ours=f"<binary:{len(ours_bytes)} bytes>",
            theirs=f"<binary:{len(theirs_bytes)} bytes>")]
        return FileMergeOutcome(path=relpath, content=None, conflicts=tuple(conflicts), warnings=(), used_strategy="ours-fallback")  # noqa: E501

    ext = "." + lowered.rsplit(".", 1)[-1] if "." in lowered else ""
    if ext in STRUCTURED_EXTENSIONS and ext in (".yml", ".yaml"):
        # multi-doc handling
        def _docs(b):
            if b is None:
                return None
            try:
                return [d if d is not None else {} for d in yaml.safe_load_all(b.decode("utf-8"))]
            except (yaml.YAMLError, UnicodeDecodeError):
                return None
        base_docs = _docs(base_bytes)
        ours_docs = _docs(ours_bytes)
        theirs_docs = _docs(theirs_bytes)
        if ours_docs is None or theirs_docs is None or (base_bytes is not None and base_docs is None):  # noqa: E501
            warnings = [f"'{relpath}': structured parse failed during merge; kept target ('ours') bytes untouched"]  # noqa: E501
            return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=tuple(warnings), used_strategy="ours-fallback")  # noqa: E501
        if len(ours_docs) > 1 or len(theirs_docs) > 1 or (base_docs is not None and len(base_docs) > 1):  # noqa: E501
            if base_docs is None:
                if len(ours_docs) != len(theirs_docs):
                    warnings = [f"'{relpath}': structured parse failed during merge; kept target ('ours') bytes untouched"]  # noqa: E501
                    return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=tuple(warnings), used_strategy="ours-fallback")  # noqa: E501
                base_docs = [{} for _ in ours_docs]
            if not (len(base_docs) == len(ours_docs) == len(theirs_docs)):
                # count mismatch
                warnings = [f"'{relpath}': structured parse failed during merge; kept target ('ours') bytes untouched"]  # noqa: E501
                return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=tuple(warnings), used_strategy="ours-fallback")  # noqa: E501
            merged_docs = []
            all_conflicts = []
            for bd, od, td in zip(base_docs, ours_docs, theirs_docs):  # noqa: B905
                c = []
                ma = _merge_ast_value(relpath, "", bd, od, td, c, set_mergeable_array_keys=set_mergeable_array_keys)  # noqa: E501
                if c:
                    all_conflicts.extend(c)
                    break
                merged_docs.append(ma)
            if all_conflicts:
                return FileMergeOutcome(path=relpath, content=None, conflicts=tuple(all_conflicts), warnings=(), used_strategy="ast-canonical")  # noqa: E501
            # diff3-first per doc: try whole diff3
            if base_bytes is not None:
                diff3_outcome = merge_text_diff3(relpath, base_bytes, ours_bytes, theirs_bytes)
            else:
                diff3_outcome = None
            if diff3_outcome is not None and not diff3_outcome.conflicts:
                try:
                    parsed_docs = [d if d is not None else {} for d in yaml.safe_load_all(diff3_outcome.content.decode("utf-8"))]  # noqa: E501
                except yaml.YAMLError:
                    parsed_docs = None
                if parsed_docs is not None and len(parsed_docs) == len(merged_docs) and all(_canonical_ast_equal(parsed_docs[i], merged_docs[i]) for i in range(len(merged_docs))):  # noqa: E501,F821
                    return FileMergeOutcome(path=relpath, content=diff3_outcome.content, conflicts=(), warnings=(), used_strategy="diff3-preserved")  # noqa: E501
            # canonical
            out = "\n---\n".join(yaml.safe_dump(d, sort_keys=False, allow_unicode=True).rstrip("\n") for d in merged_docs) + "\n"  # noqa: E501
            # if single doc originally? keep
            warning = f"'{relpath}': textual diff3 could not preserve formatting cleanly; fell back to canonical yaml rewrite (comments may have been stripped)"  # noqa: E501
            # only warn if diff3 failed; if diff3 had conflicts, warn
            if diff3_outcome is not None and diff3_outcome.conflicts:
                return FileMergeOutcome(path=relpath, content=out.encode("utf-8"), conflicts=(), warnings=(warning,), used_strategy="ast-canonical")  # noqa: E501
            # if ast mismatch only
            return FileMergeOutcome(path=relpath, content=out.encode("utf-8"), conflicts=(), warnings=(warning,), used_strategy="ast-canonical")  # noqa: E501
        # single doc: fall through to normal structured handling
    if ext in STRUCTURED_EXTENSIONS:
        base_p = _parse_structured(relpath, base_bytes) if base_bytes is not None else None
        ours_p = _parse_structured(relpath, ours_bytes)
        theirs_p = _parse_structured(relpath, theirs_bytes)
        if base_bytes is None:
            if ours_p is not None and theirs_p is not None:
                if isinstance(ours_p[0], list) and isinstance(theirs_p[0], list):
                    base_ast = []
                else:
                    base_ast = {}
            else:
                warnings = [f"'{relpath}': structured parse failed during merge; kept target ('ours') bytes untouched"]  # noqa: E501
                return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=tuple(warnings), used_strategy="ours-fallback")  # noqa: E501
        else:
            if base_p is None or ours_p is None or theirs_p is None:
                warnings = [f"'{relpath}': structured parse failed during merge; kept target ('ours') bytes untouched"]  # noqa: E501
                return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=tuple(warnings), used_strategy="ours-fallback")  # noqa: E501
            base_ast = base_p[0]
        ours_ast = ours_p[0]
        theirs_ast = theirs_p[0]
        fmt = ours_p[1]

        if ext in (".yml", ".yaml", ".toml") and base_bytes is not None and ours_bytes != base_bytes and theirs_bytes != base_bytes and ours_bytes != theirs_bytes:  # noqa: E501
            conflicts = []
            merged_ast = _merge_ast_value(relpath, "", base_ast, ours_ast, theirs_ast, conflicts, set_mergeable_array_keys=set_mergeable_array_keys)  # noqa: E501
            if conflicts:
                return FileMergeOutcome(path=relpath, content=None, conflicts=tuple(conflicts), warnings=(), used_strategy="ast-canonical")  # noqa: E501
            if base_bytes is not None:
                diff3_outcome = merge_text_diff3(relpath, base_bytes, ours_bytes, theirs_bytes)
            else:
                diff3_outcome = None
            if diff3_outcome is not None and not diff3_outcome.conflicts:
                parsed = _parse_structured(relpath, diff3_outcome.content)
                if parsed is not None and _ast_equal(parsed[0], merged_ast):
                    return FileMergeOutcome(path=relpath, content=diff3_outcome.content, conflicts=(), warnings=(), used_strategy="diff3-preserved")  # noqa: E501
            if fmt == "yaml":
                content = yaml.safe_dump(merged_ast, sort_keys=False, allow_unicode=True).encode("utf-8")  # noqa: E501
            else:
                content = tomli_w.dumps(merged_ast).encode("utf-8")
            fmt_name = "yaml" if fmt == "yaml" else "toml"
            warning = f"'{relpath}': textual diff3 could not preserve formatting cleanly; fell back to canonical {fmt_name} rewrite (comments may have been stripped)"  # noqa: E501
            return FileMergeOutcome(path=relpath, content=content, conflicts=(), warnings=(warning,), used_strategy="ast-canonical")  # noqa: E501

        conflicts = []
        merged_ast = _merge_ast_value(relpath, "", base_ast if base_bytes is not None else ({} if base_bytes is None else base_ast), ours_ast, theirs_ast, conflicts, set_mergeable_array_keys=set_mergeable_array_keys)  # noqa: E501
        if conflicts:
            return FileMergeOutcome(path=relpath, content=None, conflicts=tuple(conflicts), warnings=(), used_strategy="ast-canonical")  # noqa: E501
        content = _dump_structured(fmt, merged_ast)
        return FileMergeOutcome(path=relpath, content=content, conflicts=(), warnings=(), used_strategy="ast-canonical")  # noqa: E501

    if ext in TEXT_DIFF3_EXTENSIONS:
        return merge_text_diff3(relpath, base_bytes, ours_bytes, theirs_bytes)

    warnings = [f"'{relpath}': unknown format; kept target ('ours') bytes untouched"]
    return FileMergeOutcome(path=relpath, content=ours_bytes, conflicts=(), warnings=tuple(warnings), used_strategy="ours-fallback")  # noqa: E501


__all__ = [
    "FileMergeOutcome",
    "MergeConflictItem",
    "SET_MERGEABLE_ARRAY_KEYS",
    "STRUCTURED_EXTENSIONS",
    "TEXT_DIFF3_EXTENSIONS",
    "merge_class_b_file",
    "merge_lockfile_bytes",
    "merge_structured_config",
    "merge_text_diff3",
]
