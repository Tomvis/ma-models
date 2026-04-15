# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

This is the shared models library (`music_assistant_models`) for the Music Assistant ecosystem. It contains serializable dataclasses used for communication between the Music Assistant server and its clients/providers. It has no business logic — only data structures, enums, and serialization support.

## Commands

Install dependencies (required before running other commands):
```bash
pip install -e ".[test]"
```

Run tests:
```bash
pytest
# Single test file:
pytest tests/test_helpers.py
```

Lint and format:
```bash
ruff check --fix
ruff format
mypy
codespell
```

Run all pre-commit checks:
```bash
pre-commit run --all-files
```

## Architecture

**Serialization foundation:** All models use either `DataClassDictMixin` (for dict serialization) or `DataClassORJSONMixin` (for JSON via orjson) from the `mashumaro` library. These mixins are what enable the `.from_dict()` / `.to_dict()` pattern used throughout. Fields tagged with `field_options(alias=..., omit_none=True, ...)` control serialization behavior, including which fields are excluded from client-facing payloads.

**Dependency order (bottom to top):**
- `enums.py` — base layer, no internal deps
- `errors.py` — no internal deps
- `helpers.py` — depends on enums
- `media_items/` — depends on enums, helpers, errors
- `player.py`, `player_queue.py`, `queue_item.py` — depend on enums and media_items
- `background_task.py`, `config_entries.py`, `provider.py` — depend on enums
- `api.py`, `event.py` — top-level, aggregate everything

**Enum conventions:** All enums implement `_missing_()` to return an `UNKNOWN` member instead of raising on unrecognized values. This enables forward compatibility when server and client run different versions of the library.

**External IDs:** Media items carry a `external_ids: set[tuple[ExternalID, str]]` for cross-provider identity (MusicBrainz, ISRC, ACOUSTID, etc.). The `ExternalID` enum defines the ID type. Some ID types are marked `.requires_uuid_validation` and are validated as UUIDs.

**Server-side fields:** Certain fields in `player_queue.py` and elsewhere are only populated server-side and should not be serialized for clients. These use `field_options` with custom serialization hooks to control this.

## Code Style

- Line length: 100 characters
- Target: Python 3.13
- mypy is in strict mode — all functions must be fully typed
- Ruff is configured with `select = ["ALL"]` plus explicit ignores; do not add `# noqa` without checking the ignore list in `pyproject.toml` first
- Docstrings follow PEP257/Google convention
