# Tests

This project separates fast unit tests from slower integration tests.

- `tests/unit/`: fast tests (imports, pure logic)
- `tests/integration/`: filesystem / external tool checks

Run:
- `pytest`
- `pytest -m "not integration"`
- `pytest -m integration`
