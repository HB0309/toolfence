"""Tests for the alternate-model profiles and configs (Phase D).

Test inventory (14 tests)
-------------------------
  test_filesystem_alt_model_profile_loads
  test_filesystem_alt_model_profile_id
  test_filesystem_alt_model_description_mentions_llama
  test_filesystem_alt_model_description_mentions_deepinfra
  test_filesystem_alt_model_nanobot_config_exists
  test_filesystem_alt_model_config_differs_only_in_expected_fields
  test_galaxium_alt_model_profile_loads
  test_galaxium_alt_model_profile_id
  test_galaxium_alt_model_description_mentions_llama
  test_galaxium_alt_model_description_mentions_deepinfra
  test_galaxium_alt_model_nanobot_config_exists
  test_galaxium_alt_model_config_differs_only_in_expected_fields
  test_filesystem_alt_model_config_model_and_provider
  test_galaxium_alt_model_config_model_and_provider
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

ALT_MODEL = "meta-llama/llama-3.3-70b-instruct"
ALT_PROVIDER_ORDER = ["DeepInfra"]

# Fields that are allowed to differ between an alt-model profile and its original.
_PROFILE_ALLOWED_DIFF_KEYS = {"profile_id", "description", "nanobot_config"}

# Config fields (nested paths) that are allowed to differ.
# - model: different model name
# - provider sub-dict: order/allow_fallbacks/require_parameters differ
# - reasoning: absent from alt-model configs (DeepInfra rejects it via require_parameters)
_CONFIG_ALLOWED_DIFF_PATHS = {
    ("agents", "defaults", "model"),
    ("providers", "openrouter", "extraBody", "provider"),
    ("providers", "openrouter", "extraBody", "provider", "order"),
    ("providers", "openrouter", "extraBody", "provider", "allow_fallbacks"),
    ("providers", "openrouter", "extraBody", "provider", "require_parameters"),
    ("providers", "openrouter", "extraBody", "reasoning"),
    ("providers", "openrouter", "extraBody", "reasoning", "effort"),
}


def _load_json(rel: str) -> dict:
    return json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _load_profile(rel: str):
    from toolfence.contracts.profile import TargetProfile
    return TargetProfile.model_validate(_load_json(rel))


# ---------------------------------------------------------------------------
# Helpers — recursive config diff
# ---------------------------------------------------------------------------

def _diff_dicts(orig: dict, alt: dict, path: tuple = ()) -> list[tuple]:
    """Return list of (path_tuple, orig_value, alt_value) for differing leaves."""
    diffs = []
    all_keys = set(orig) | set(alt)
    for k in all_keys:
        current_path = path + (k,)
        if k not in orig:
            diffs.append((current_path, None, alt[k]))
        elif k not in alt:
            diffs.append((current_path, orig[k], None))
        elif isinstance(orig[k], dict) and isinstance(alt[k], dict):
            diffs.extend(_diff_dicts(orig[k], alt[k], current_path))
        elif orig[k] != alt[k]:
            diffs.append((current_path, orig[k], alt[k]))
    return diffs


# ---------------------------------------------------------------------------
# profiles/filesystem-alt-model.json
# ---------------------------------------------------------------------------

def test_filesystem_alt_model_profile_loads():
    """profiles/filesystem-alt-model.json parses as a TargetProfile without error."""
    profile = _load_profile("profiles/filesystem-alt-model.json")
    assert profile is not None


def test_filesystem_alt_model_profile_id():
    """profile_id must be 'filesystem-alt-model'."""
    profile = _load_profile("profiles/filesystem-alt-model.json")
    assert profile.profile_id == "filesystem-alt-model"


def test_filesystem_alt_model_description_mentions_llama():
    """description must mention the Llama model."""
    profile = _load_profile("profiles/filesystem-alt-model.json")
    assert "llama" in profile.description.lower(), (
        f"description should mention 'llama', got: {profile.description!r}"
    )


def test_filesystem_alt_model_description_mentions_deepinfra():
    """description must mention DeepInfra (the active provider)."""
    profile = _load_profile("profiles/filesystem-alt-model.json")
    assert "deepinfra" in profile.description.lower(), (
        f"description should mention 'DeepInfra', got: {profile.description!r}"
    )


def test_filesystem_alt_model_nanobot_config_exists():
    """nanobot_config must point to an existing file."""
    profile = _load_profile("profiles/filesystem-alt-model.json")
    config_path = REPO_ROOT / profile.nanobot_config
    assert config_path.exists(), f"nanobot_config not found: {config_path}"


def test_filesystem_alt_model_config_differs_only_in_expected_fields():
    """filesystem-alt-model profile differs from filesystem only in allowed keys."""
    orig = _load_json("profiles/filesystem.json")
    alt = _load_json("profiles/filesystem-alt-model.json")

    unexpected = {}
    for key in set(orig) | set(alt):
        if key in _PROFILE_ALLOWED_DIFF_KEYS:
            continue
        orig_val = orig.get(key)
        alt_val = alt.get(key)
        if orig_val != alt_val:
            unexpected[key] = (orig_val, alt_val)

    assert not unexpected, (
        f"filesystem-alt-model profile differs from filesystem in unexpected keys: {list(unexpected)}"
    )


# ---------------------------------------------------------------------------
# profiles/galaxium-alt-model.json
# ---------------------------------------------------------------------------

def test_galaxium_alt_model_profile_loads():
    """profiles/galaxium-alt-model.json parses as a TargetProfile without error."""
    profile = _load_profile("profiles/galaxium-alt-model.json")
    assert profile is not None


def test_galaxium_alt_model_profile_id():
    """profile_id must be 'galaxium-alt-model'."""
    profile = _load_profile("profiles/galaxium-alt-model.json")
    assert profile.profile_id == "galaxium-alt-model"


def test_galaxium_alt_model_description_mentions_llama():
    """description must mention the Llama model."""
    profile = _load_profile("profiles/galaxium-alt-model.json")
    assert "llama" in profile.description.lower(), (
        f"description should mention 'llama', got: {profile.description!r}"
    )


def test_galaxium_alt_model_description_mentions_deepinfra():
    """description must mention DeepInfra (the active provider)."""
    profile = _load_profile("profiles/galaxium-alt-model.json")
    assert "deepinfra" in profile.description.lower(), (
        f"description should mention 'DeepInfra', got: {profile.description!r}"
    )


def test_galaxium_alt_model_nanobot_config_exists():
    """nanobot_config must point to an existing file."""
    profile = _load_profile("profiles/galaxium-alt-model.json")
    config_path = REPO_ROOT / profile.nanobot_config
    assert config_path.exists(), f"nanobot_config not found: {config_path}"


def test_galaxium_alt_model_config_differs_only_in_expected_fields():
    """galaxium-alt-model profile differs from galaxium only in allowed keys."""
    orig = _load_json("profiles/galaxium.json")
    alt = _load_json("profiles/galaxium-alt-model.json")

    unexpected = {}
    for key in set(orig) | set(alt):
        if key in _PROFILE_ALLOWED_DIFF_KEYS:
            continue
        orig_val = orig.get(key)
        alt_val = alt.get(key)
        if orig_val != alt_val:
            unexpected[key] = (orig_val, alt_val)

    assert not unexpected, (
        f"galaxium-alt-model profile differs from galaxium in unexpected keys: {list(unexpected)}"
    )


# ---------------------------------------------------------------------------
# Config files: model + provider block
# ---------------------------------------------------------------------------

def test_filesystem_alt_model_config_model_and_provider():
    """config/nanobot.filesystem.alt-model.json uses the correct model and provider block."""
    cfg = _load_json("config/nanobot.filesystem.alt-model.json")
    assert cfg["agents"]["defaults"]["model"] == ALT_MODEL, (
        f"Expected model {ALT_MODEL!r}, got {cfg['agents']['defaults']['model']!r}"
    )
    provider_block = cfg["providers"]["openrouter"]["extraBody"]["provider"]
    assert provider_block["order"] == ALT_PROVIDER_ORDER, (
        f"Expected order {ALT_PROVIDER_ORDER}, got {provider_block['order']}"
    )
    assert provider_block["allow_fallbacks"] is False
    assert provider_block["require_parameters"] is True

    # The only differences from nanobot.filesystem.json must be in the allowed paths.
    orig = _load_json("config/nanobot.filesystem.json")
    alt = _load_json("config/nanobot.filesystem.alt-model.json")
    diffs = _diff_dicts(orig, alt)
    unexpected = [
        d for d in diffs
        if d[0] not in _CONFIG_ALLOWED_DIFF_PATHS
    ]
    assert not unexpected, (
        f"nanobot.filesystem.alt-model.json differs from nanobot.filesystem.json "
        f"in unexpected paths: {[d[0] for d in unexpected]}"
    )


def test_galaxium_alt_model_config_model_and_provider():
    """config/nanobot.eval.alt-model.json uses the correct model and provider block."""
    cfg = _load_json("config/nanobot.eval.alt-model.json")
    assert cfg["agents"]["defaults"]["model"] == ALT_MODEL, (
        f"Expected model {ALT_MODEL!r}, got {cfg['agents']['defaults']['model']!r}"
    )
    provider_block = cfg["providers"]["openrouter"]["extraBody"]["provider"]
    assert provider_block["order"] == ALT_PROVIDER_ORDER, (
        f"Expected order {ALT_PROVIDER_ORDER}, got {provider_block['order']}"
    )
    assert provider_block["allow_fallbacks"] is False
    assert provider_block["require_parameters"] is True

    # The only differences from nanobot.eval.json must be in the allowed paths.
    orig = _load_json("config/nanobot.eval.json")
    alt = _load_json("config/nanobot.eval.alt-model.json")
    diffs = _diff_dicts(orig, alt)
    unexpected = [
        d for d in diffs
        if d[0] not in _CONFIG_ALLOWED_DIFF_PATHS
    ]
    assert not unexpected, (
        f"nanobot.eval.alt-model.json differs from nanobot.eval.json "
        f"in unexpected paths: {[d[0] for d in unexpected]}"
    )
