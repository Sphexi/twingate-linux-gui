# Contributing

## Development Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/benyanke/twingate-linux-gui.git
   cd twingate-linux-gui
   ```

2. Create a virtual environment using Python 3.12:

   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the package and all development dependencies:

   ```bash
   pip install -r requirements-dev.txt
   pip install -e .
   ```

4. Verify the setup:

   ```bash
   pytest                  # all tests must pass
   ruff check .            # no lint errors
   mypy src/               # no type errors
   ```

   For headless environments (CI, servers without a display):

   ```bash
   QT_QPA_PLATFORM=offscreen pytest
   ```

## Code Style

**Language version:** Python 3.12+. Use modern type hints (`str | None`, not `Optional[str]`),
`match` statements where appropriate, and other 3.12+ features freely.

**Linting and formatting:** `ruff` handles both. Configuration lives in `pyproject.toml`
(`target-version = "py312"`, line length 100). Run before every commit:

```bash
ruff check .        # lint
ruff format .       # format
```

**Type checking:** `mypy` runs in strict mode. Every function signature must have complete
type annotations. Run:

```bash
mypy src/
```

**Docstrings:** Every public class and method requires a docstring. Use Google style:

```python
def connect(self, timeout: int = 30) -> bool:
    """Initiate a Twingate connection via the CLI.

    Args:
        timeout: Maximum seconds to wait for the command to complete.

    Returns:
        True if the connection was established, False otherwise.

    Raises:
        subprocess.TimeoutExpired: If the CLI does not respond within timeout.
    """
```

Private methods (`_name`) need at minimum a one-line docstring if the logic is not
immediately obvious from the code.

## Testing

Run the full test suite:

```bash
pytest
```

Run a specific test file:

```bash
pytest tests/test_client.py
```

Run with coverage:

```bash
pytest --cov=twingate_tray --cov-report=html
```

**Qt widget tests:** Use `pytest-qt` for any test that touches PyQt6 widgets. The `qtbot`
fixture handles widget lifecycle and cleanup automatically.

**Subprocess mocking:** Never call the real `twingate` binary in tests. Always mock
`subprocess.run`. The shared fixture in `tests/conftest.py` provides a pre-configured mock.
Tests that accidentally invoke the real CLI will fail in CI where the binary is not installed.

**Headless mode:** Set `QT_QPA_PLATFORM=offscreen` when running tests in environments without
a display server. This is set automatically in CI via `.github/workflows/ci.yml`.

## Pull Request Process

1. Fork the repository and create a feature branch from `main`:

   ```bash
   git checkout -b feature/my-change
   ```

2. Make your changes. Write tests for any new behavior.

3. Ensure all checks pass before opening the PR:

   ```bash
   ruff check .
   ruff format --check .
   mypy src/
   QT_QPA_PLATFORM=offscreen pytest
   ```

4. Update `CHANGELOG.md` under the `[Unreleased]` section for any user-facing change
   (new feature, bug fix, behavior change). Internal refactors do not require a changelog
   entry.

5. Keep PRs focused. One feature or fix per PR. If you find unrelated issues while working,
   open a separate PR or issue for them.

6. Describe what the PR does and why in the PR description. Link any related issues.

## Architecture Notes

The full architecture is documented in `CLAUDE.md` at the project root. Key rules that affect
all contributions:

- **All Twingate interaction is via subprocess.** The CLI has no API or D-Bus interface.
  Every operation is `subprocess.run(["twingate", ...])` with stdout/stderr parsing. Do not
  introduce HTTP clients or any other out-of-process communication mechanism.

- **Pass `-d` to every CLI command.** This disables ANSI color codes in output, making stdout
  parsing reliable. Any new CLI invocation that omits `-d` will produce unparseable output in
  production.

- **Commands that modify state go through `pkexec`.** Read-only commands (`status`,
  `resources`, `exit-node list`, `account list`) run directly. Everything else requires root
  and must be invoked via `pkexec`. See `CLAUDE.md` for the full command classification.

- **Never crash on parse failures.** If CLI output is unexpected, log a warning and degrade
  gracefully. The tray application must remain running and responsive at all times.

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE).
