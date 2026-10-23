"""Tests for the plugin.json boundary model shared by the version sync and the release gate."""

from __future__ import annotations

import json

import pytest

from bmk.adapters.stagerunner.helpers._plugin_manifest import PluginManifest, PluginManifestError

# A manifest whose keys are NOT in the model's declaration order ("version" after
# "name" and a nested table), with non-ASCII text and numbers that must round-trip.
_REALISTIC = (
    '{"name": "thing", "description": "caf' + chr(0xE9) + '", "author": {"name": "bitranox", "email": "a@b"}, '
    '"keywords": ["a", "b"], "version": "1.0.0", "size": 1.0, "big": 10000000000000000000000, "flag": null}'
)


@pytest.mark.os_agnostic
def test_a_rewrite_changes_the_version_and_nothing_else() -> None:
    # The reference is what the sync wrote before this model existed: json.loads, assign
    # the key, json.dumps(indent=2) plus a newline. A manifest rewrite that differed in
    # key order or escaping would churn every repo's plugin.json on each sync.
    reference = json.loads(_REALISTIC)
    reference["version"] = "3.0.0"

    rewritten = PluginManifest.from_json(_REALISTIC).with_version("3.0.0").to_json()

    assert rewritten == json.dumps(reference, indent=2) + "\n"


@pytest.mark.os_agnostic
def test_a_version_the_manifest_lacked_is_appended_last() -> None:
    assert PluginManifest.from_json('{"name": "x", "z": 1}').with_version("2.0.0").to_json() == (
        '{\n  "name": "x",\n  "z": 1,\n  "version": "2.0.0"\n}\n'
    )


@pytest.mark.os_agnostic
def test_an_absent_version_reads_empty_and_is_not_written_back() -> None:
    manifest = PluginManifest.from_json('{"name": "x"}')

    assert (manifest.version, manifest.to_json()) == ("", '{\n  "name": "x"\n}\n')


@pytest.mark.os_agnostic
@pytest.mark.parametrize(("raw", "expected"), [("1.5", "1.5"), ("1", "1"), ("null", "None"), ("true", "True")])
def test_a_non_string_version_is_read_as_its_text(raw: str, expected: str) -> None:
    # str() of the JSON value, as the sync always read it: a number still orders as a
    # version, and null/true become text the version check then refuses.
    assert PluginManifest.from_json(f'{{"version": {raw}}}').version == expected


@pytest.mark.os_agnostic
@pytest.mark.parametrize("text", ["[1, 2]", '"hello"', "3"])
def test_json_that_is_not_an_object_is_refused(text: str) -> None:
    with pytest.raises(PluginManifestError, match="not a JSON object"):
        PluginManifest.from_json(text)


@pytest.mark.os_agnostic
def test_text_that_is_not_json_raises_the_decoder_error() -> None:
    with pytest.raises(json.JSONDecodeError):
        PluginManifest.from_json('{"name": ')
