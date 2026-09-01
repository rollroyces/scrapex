# Contributing to scrapex

Thanks for your interest! scrapex is intentionally small — please open an
issue before sending a large PR so we can discuss the approach.

## Setup

```bash
git clone https://github.com/rollroyces/scrapex
cd scrapex
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Tests

```bash
pytest -v                     # all tests
pytest --cov=scrapex          # with coverage
ruff check scrapex tests      # lint
mypy scrapex                  # type-check
```

## Design rules

1. **Public API is in `scrapex/__init__.py`.** Don't add new top-level imports.
2. **Pydantic models are the contract.** All I/O goes through them.
3. **Extractors are registered, not hard-coded.** New strategy? Add a module
   under `scrapex/extractors/` that calls `register()` on import.
4. **Errors are typed.** Use the exception classes in `scrapex/errors.py`,
   don't `raise Exception(...)`.
5. **Optional dependencies stay optional.** `litellm`, `playwright`, and
   `cloudscraper` must be guarded with try/except.

## License

By contributing, you agree your contributions are licensed under
AGPL-3.0-or-later. Commercial relicensing is at the maintainer's discretion.