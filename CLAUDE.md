# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Versioning — always use the bump script

The plugin version is duplicated in three files that must never drift:
`pyproject.toml`, `plugin.py` (`self.version`), and `rest_server.py` (FastAPI `version=`).

**Never edit these version strings by hand.** When asked to change the version, run the
script from the repo root (Windows / PowerShell):

```powershell
pwsh ./version_up.ps1 1.2.3      # set an explicit version
pwsh ./version_up.ps1 patch      # or auto-bump from the current version: major | minor | patch
```

The script reads the current version from `pyproject.toml`, rewrites all three files,
and is byte-faithful (only the version line changes, line endings preserved). It refuses
invalid input and is a no-op if the version is unchanged. After running it, review
`git diff` and commit as `chore: bump version to X.Y.Z`.

Do **not** bump the version unprompted — the user decides when.

## Tests & lint

- `python -m pytest tests/` runs standalone — no host-package stub or `PYTHONPATH` needed.
- `ruff check .` must be clean before committing (`make check` = lint + typecheck + test).

## Notes

- `shared` is the Wan2GP host package, present only when the plugin is deployed inside
  Wan2GP. `plugin.py` imports it; the package `__init__` imports `RestApiPlugin` lazily
  (via `__getattr__`/`__dir__`) so importing the package for tests does not pull it in.
- The server bind host is configurable in `cleanup_config.json` (`host`: `127.0.0.1`
  localhost-only by default, or `0.0.0.0` for LAN — the API is unauthenticated).
- `wan2gp_root` (the dir containing `wgp.py`, e.g. `…\wan.git\app`) is detected by walking
  up from the plugin via `cleanup.find_wan2gp_root` — drive/depth independent, not hardcoded.
  `pinokio_wan2gp_root` is its parent (`…\wan.git`). Both are stored on the plugin instance
  and logged at startup. Output cleanup targets `wan2gp_root/outputs`.
