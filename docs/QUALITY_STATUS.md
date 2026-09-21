# Project Intelligence Atlassian — quality status

Last verified: 2026-09-16. This is the sole current quality and repository-hygiene
summary. `ARCHITECTURE.md` remains the sole architecture source of truth.

This repository follows the suite's canonical
[exact-pin dependency policy](https://github.com/naveenrajElangovan/project-intelligence-rag/blob/main/docs/DEPENDENCY_POLICY.md).

## Verified status

- Full Python suite: 25 passed, 2 third-party deprecation warnings.
- Ruff lint: clean across `app`, `tests`, and `scripts`.
- Ruff format: clean across all 11 maintained Python files.
- Forge ESLint: 0 findings; Prettier: all files clean.
- Python deptry and Forge depcheck: 0 unexplained findings.
- Dependency integrity: `pip check` reports no broken requirements.
- Tests contain no permanent `skip`, `pytest.skip`, `unittest.skip`, or `xfail`
  markers.

## Quality enforcement

- `make check PYTHON=.venv/bin/python` is the single full quality entrypoint for
  Python and Forge JavaScript.
- Ruff, deptry, ESLint, Prettier, depcheck, and pytest run in pre-commit or the
  GitHub Actions quality workflow as appropriate.
- `pyproject.toml` is the sole Python dependency declaration. Runtime, test, and
  development versions are exact pins; the duplicate `requirements.txt` was
  removed after a five-repository reference search. The Docker image installs the
  project metadata directly.
- The Forge bridge has an npm lockfile. Its package manifest now uses exact direct
  versions, and CI installs the locked graph with `npm ci`.

## Closed audit decisions

- **Forge quality tooling — closed:** ESLint 10 and Prettier 3 are pinned in
  `forge/package.json`, locked in `forge/package-lock.json`, and enforced by npm,
  pre-commit, Make, and CI. Forge depcheck reports no unexplained dependency.
- **Python dependency duplication — closed:** `pyproject.toml` is authoritative;
  `requirements.txt` no longer exists.
- **Asyncio test environment — closed:** the documented command uses this
  repository's `.venv`, whose `test` extra installs pinned `pytest-asyncio`.
  `asyncio_default_fixture_loop_scope = "function"` makes the plugin policy
  explicit, so the former unknown-option warning cannot recur.
- **Shared dependency versions — closed:** FastAPI 0.141.1, Pydantic Settings
  2.15.0, Prometheus Client 0.26.0, and pytest 8.4.2 meet or exceed the required
  cross-repository floors. Each upgrade was followed by the full suite.

Deptry's narrow `DEP002` list is not a blanket suppression. `starlette` is pinned
because `app.main` relies on the HTTP 422 constant supplied through FastAPI and the
older allowed Starlette release failed the baseline suite; `uvicorn` is the
container's CLI entrypoint; `pytest-asyncio` supplies the configured pytest plugin;
and `deptry`, `pre-commit`, and `ruff` are command-line quality tools. Forge depcheck
ignores only `@forge/cli`, the locked deployment CLI invoked by operators rather
than imported by `forge/src/index.js`. Deptry's `DEP004=pytest` exception records
that pytest belongs in the test-only extra even though deptry scans `tests/`; it is
not a production dependency.

## Reproduction

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test,dev]'
npm ci --prefix forge
make check PYTHON=.venv/bin/python
```
