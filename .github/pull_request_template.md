## What this changes

<!-- One or two sentences, in plain language. -->

## How I tested it

- [ ] `python -m ruff check .` and `python -m pytest` pass
- [ ] Tried it in the app (which pages?)
- [ ] Works the same on Windows, macOS and Linux, or uses `core/osutil.py` for anything that differs

## Checklist

- [ ] No personal data (real resumes, databases, generated files, contact details) in the diff
- [ ] Prompts still forbid inventing experience, dates, metrics or skills
- [ ] The profile still learns only from the resume, the standard questions and questions along the way
- [ ] UI text and comments are short and plain, with no em dashes or middle dots
- [ ] If an AI assistant wrote any of this, I read the whole diff, ran the app, and it has tests

## Review checklist (for the reviewer)

Review with GitHub's "Review changes" button: approve it, or request changes with a comment on the exact lines.

- [ ] Code quality and readability: clear names, comments that explain why, no dead code, follows CONTRIBUTING.md
- [ ] Security: user input and job postings are checked or escaped, no tokens or personal data in logs, nothing reachable
  from outside this computer
- [ ] Performance: no query or network call inside a loop, nothing slow on the event loop, benchmarks still pass
- [ ] Integration: API shapes and settings keys still match what the dashboard and other packages expect
- [ ] Documentation: docstrings, CONTRIBUTING.md and the README match the change
- [ ] Tests: new behavior has a test, and CI (tests, coverage, benchmarks) is green
