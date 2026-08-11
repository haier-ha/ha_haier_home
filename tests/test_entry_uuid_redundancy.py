"""Regression tests for _async_create_entry: verify no-redundant-write issues.

Uses AST inspection on the production source so we can assert structural
properties of the ``entry.data`` dict without needing a full HomeAssistant
runtime. This keeps the test free of any conftest.py mocks.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "haier_home"
_CONFIG_FLOW = _SRC_ROOT / "config_flow.py"


def _collect_dict_literal_keys_in_create_entry_data() -> set[str]:
    """Return all literal string keys used in the ``data={...}`` dict literal
    of the ``self.async_create_entry(...)`` call inside
    ``HaierHomeConfigFlow._async_create_entry``.
    """
    tree = ast.parse(_CONFIG_FLOW.read_text(encoding="utf-8"))
    # Walk to the target class
    target_cls = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "HaierHomeConfigFlow":
            target_cls = node
            break
    assert target_cls is not None, "Could not find HaierHomeConfigFlow class"

    # Walk to the target method (async def → AsyncFunctionDef, not FunctionDef)
    target_method = None
    for item in target_cls.body:
        if (
            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == "_async_create_entry"
        ):
            target_method = item
            break
    assert target_method is not None, "Could not find _async_create_entry method"

    # Inside the method, find the ``self.async_create_entry(data=DictLiteral, ...)`` call
    for node in ast.walk(target_method):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr == "async_create_entry"
        ):
            for kw in node.keywords:
                if kw.arg == "data" and isinstance(kw.value, ast.Dict):
                    keys: set[str] = set()
                    for k in kw.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            keys.add(k.value)
                    return keys
    pytest.fail(
        "Could not locate self.async_create_entry(data={...}, ...) call "
        "inside HaierHomeConfigFlow._async_create_entry – did the method "
        "signature change?"
    )
    # pragma: no cover - unreachable after pytest.fail
    return set()


def _find_reads_of_entry_uuid_key() -> list[str]:
    """Return list of files (relative to project root) that read
    ``entry.data["entry_uuid"]`` or similar. If nobody reads it, the write
    is definitely redundant.
    """
    hits: list[str] = []
    project_root = _SRC_ROOT.parent.parent
    pattern_variants = (
        'data.get("entry_uuid"',
        "data.get('entry_uuid'",
        '["entry_uuid"]',
        "['entry_uuid']",
        '"entry_uuid" in',
        "'entry_uuid' in",
    )
    for py_file in project_root.rglob("*.py"):
        # Exclude test files from "no reader" check – tests shouldn't need to
        # read production-only data keys to justify their existence.
        if py_file.is_dir():
            continue
        text = py_file.read_text(encoding="utf-8", errors="replace")
        for variant in pattern_variants:
            if variant in text:
                rel = py_file.relative_to(project_root).as_posix()
                # A hit inside the test file itself doesn't count as a consumer.
                if "test_entry_uuid" in rel:
                    continue
                hits.append(f"{rel}: {variant}")
                break
    return hits


class TestEntryUuidRedundancy:
    """The ``_async_create_entry`` helper writes ``config_entry.unique_id``
    via the official ``async_set_unique_id(...)`` API, which is the
    authoritative source for config entry identity in Home Assistant.

    Writing *the same* value a second time into ``entry.data["entry_uuid"]``
    is redundant: HA's database already stores ``unique_id`` on the entry,
    and no code path currently reads the cached copy. The duplicated value
    creates drift risk: if the unique_id scheme is ever changed later,
    whoever edits ``async_set_unique_id`` will almost certainly forget to
    also update the ``entry.data`` snapshot, leading to inconsistent state
    that is hard to debug.
    """

    EXPECTED_KEYS: frozenset[str] = frozenset(
        {
            "region",
            "token",
            "homes",
            "uid",
            "ag_client_id",  # needed by HaierHttpClient/WS after restart
            "language",
            "room_sync_mode",
            "scene_sync",
            "scenes",
            "family_names",
            "auth_implementation",  # OAuth2 auth implementation reference
        }
    )

    def test_entry_data_does_not_contain_entry_uuid_key(self) -> None:
        """``entry.data`` dict literal must not contain ``"entry_uuid"``.

        We compare against the allowed set of keys, which are all consumed
        elsewhere (see project_memory rules for ag_client_id usage in
        coordinator, WS client, and HTTP client).
        """
        keys = _collect_dict_literal_keys_in_create_entry_data()
        assert "entry_uuid" not in keys, (
            "entry.data contains redundant key 'entry_uuid'; the same value "
            "is already the authoritative config_entry.unique_id set via "
            "async_set_unique_id(). Duplicating it creates drift risk when "
            "the unique_id scheme is later adjusted."
        )

    def test_entry_data_keys_match_expected_set(self) -> None:
        """Defensive structural check – every key written to entry.data
        should be known; unexpected extras are flagged for review."""
        keys = _collect_dict_literal_keys_in_create_entry_data()
        unexpected = keys - self.EXPECTED_KEYS
        assert not unexpected, (
            f"entry.data dict in _async_create_entry carries unexpected keys: "
            f"{sorted(unexpected)}. If these are intentional, document their "
            "purpose and extend EXPECTED_KEYS in this test."
        )

    def test_no_production_code_reads_entry_uuid_from_entry_data(self) -> None:
        """If nothing reads ``entry.data["entry_uuid"]``, the write is
        provably dead code and should be removed.

        Note: a missing hit here is what makes entry_uuid provably dead; a
        non-empty hit list means the key actually has a consumer and the
        redundancy concern should be re-evaluated (in which case the test
        intentionally fails so the reviewer must re-assess).
        """
        consumers = _find_reads_of_entry_uuid_key()
        # Filter out the writing site itself (_async_create_entry in config_flow.py)
        # – the writing location contains the string literal but isn't a read.
        write_sites = [
            c for c in consumers if c.startswith("custom_components/haier_home/config_flow.py")
        ]
        real_consumers = [c for c in consumers if c not in write_sites]
        assert not real_consumers, (
            "Found code that reads entry.data['entry_uuid'] – if this is "
            "intentional then the redundancy claim is invalid and this test "
            "must be updated. Consumers:\n  - " + "\n  - ".join(real_consumers)
        )
        # The current codebase has zero consumers → the write is dead code.
