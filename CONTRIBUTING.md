# Contributing to JobPortal

Thanks for helping. This page covers getting set up, running the tests, and the rules that keep JobPortal working on
Windows, macOS and Linux.

## Set up

1. Install Python 3.11 or newer. For PDF export you need Chrome, Edge or Chromium. AI features need a ChatGPT Go, Plus or Pro
   plan; sign in from inside the app.
2. Clone the repository and install it in editable mode with the development tools:

   ```bash
   python -m venv .venv
   .venv/bin/pip install -e ".[dev]"          # Windows: .venv\Scripts\pip install -e ".[dev]"
   ```

   (`./run.sh` or `.\run.ps1` does the same and then starts the app.)
3. Run `jobportal --doctor` to confirm everything is found.

Use a throwaway data folder while developing so you never mix test data with your own job search:

```bash
jobportal --data-dir ./dev-data --browser    # dev-data/ is ignored by git
```

The repository includes a fictional resume at `tests/fixtures/sample_resume.md` for trying the setup flow.

## Run the tests

```bash
python -m ruff check .
python -m pytest
```

Tests never call OpenAI. They use the `fake_ai` fixture in `tests/conftest.py` or the mock server in `tests/test_ai.py`.
Every test starts from an empty data folder. CI runs lint, tests, `jobportal --doctor`, a server smoke test and the start scripts on Ubuntu, macOS and Windows for
every push and pull request.

## Workflow

- Branch from `main` (for example `feature/onboarding-tooltips` or `fix/pdf-timeout`), keep pull requests focused, and fill in
  the pull request template.
- CI must pass before merging. Ask a teammate to review anything that changes prompts, the database or the setup flow.
- Describe user-facing changes in plain language in the pull request.

## Rules

**No personal data in the repository.** JobPortal starts with zero data, and the repository must never contain a real
resume, database, generated document or anyone's contact details. Tests and examples use fictional people and
`example.com` addresses. `.gitignore` blocks databases, PDFs and DOCX files, but check `git status` before you commit.

**Keep it cross-platform.**
- Anything that touches the operating system goes through `jobportal/osutil.py` (opening files and links, notifications,
  finding Chrome or LibreOffice). Don't call `xdg-open`, `open`, `start` or other system commands directly.
- Use `pathlib` for paths and pass `encoding="utf-8"` to every `read_text`, `write_text` and `open` (Windows defaults to a
  different encoding).
- No shell-specific commands in Python, and no `strftime` codes that only exist on some systems (such as `%-d`).
- Every AI request goes through `jobportal/ai.py`. ChatGPT tokens stay in `openai_auth.py` and the data folder.
- Keep `run.sh` and `run.ps1` in step with each other.

**Keep the AI truthful.** Prompts may let the model choose, reorder and rephrase, never invent. If the profile is missing
something, the answer is a question for the user (`profile.ask`), not a guess.

**Match the surrounding code.** The backend is plain FastAPI and SQLite; the dashboard is vanilla JavaScript with no build
step. Follow the existing style for naming, comments and structure. In anything user-facing, write plainly: no em dashes,
and no middle dots as separators.

## Releases

Push a version tag (for example `v0.2.0`) to `main`. The Release workflow builds the Windows, macOS and Linux apps, tests that
each one starts, and publishes them on the Releases page. Bump `__version__` in `jobportal/__init__.py` first.

To build the app for your own system:

```bash
pip install -e ".[build]"
pyinstaller --noconfirm packaging/jobportal.spec   # the app lands in dist/
```

## Where things are

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit together and where to make common changes.
