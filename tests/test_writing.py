"""The team's writing rules, checked on every test run (so CI checks every push): no em dashes, no middle dots used as word
separators, and American spelling, in every text file the repo tracks. That covers code, comments, docs, UI text and the
diagrams in documentation/.

Code that has to match one of those characters in someone else's text (a job posting, an uploaded certificate) writes it
as an escape, like "\\u2014", which this check doesn't see. Names that come from other people's code, such as Python's
asyncio.CancelledError, are listed in THIRD_PARTY_NAMES. This file is the one place the British spellings are spelled out,
so it skips itself."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Characters the rules ban, written as escapes so this file passes its own check.
BANNED_CHARACTERS = {"—": "em dash", "·": "middle dot", " – ": "en dash used as a dash"}

# Common British spellings and their stems. Each matches at the start of a word, in any letter case. Stems are written so
# the American spelling never matches: "colour" but not "color", "analysed" but not "analyses" (the plural of analysis).
BRITISH = re.compile(r"\b(" + "|".join([
    r"colour\w*", r"behaviour\w*", r"favour\w*", r"honour\w*", r"labour\w*", r"neighbour\w*", r"flavour\w*", r"humour\w*",
    r"centre[sd]?\b", r"theatre", r"metres?\b", r"litres?\b", r"fibre", r"licence[sd]?\b", r"defence", r"offence",
    r"cancell(ed|ing)", r"travell(ed|ing|ers?)", r"labell(ed|ing)", r"modell(ed|ing)", r"levell(ed|ing)", r"signall(ed|ing)",
    r"fuell(ed|ing)", r"programmes?\b", r"catalogue", r"analogue", r"cheque", r"grey\b", r"tyres?\b", r"sceptic",
    r"judgement", r"acknowledgement", r"ageing", r"whilst", r"amongst", r"learnt", r"spelt", r"enrolment", r"fulfilment",
    r"instalment", r"skilful", r"jewellery", r"marvellous", r"artefact", r"paediatric", r"anaem", r"orthopaed", r"haem",
    r"oestr", r"manoeuvr", r"aluminium", r"enquir", r"focuss(ed|ing)", r"benefitt(ed|ing)", r"per cent",
    r"practis(e|ed|es|ing)\b",
    r"(organ|real|recogn|priorit|custom|optim|minim|maxim|normal|summar|categor|apolog|author|emphas|final|initial|serial"
    r"|sanit|standard|synchron|util|visual|personal|special|capital|character|local|stabil|token|critic|memor|modern"
    r"|harmon|mobil|familiar|jeopard)is(e|ed|es|ing|ation|ations|er)\b",
    r"(anal|catal|paral|dial)ys(e|ed|ing)\b",
]) + r")", re.IGNORECASE)

# Names from other people's code that use British spelling. They're removed from a line before it's checked.
THIRD_PARTY_NAMES = ("CancelledError",)

# Files that aren't text, by extension.
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".icns", ".woff", ".woff2", ".ttf", ".pdf", ".docx", ".zip", ".db"}


def tracked_files() -> list[Path]:
    """Every file git tracks, or, outside a git checkout, every file under the repo minus environments and caches."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return [ROOT / name for name in out.splitlines() if name]
    except (OSError, subprocess.CalledProcessError):
        skip = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist", ".pytest_cache", ".ruff_cache"}
        return [p for p in ROOT.rglob("*") if p.is_file() and not skip & set(p.relative_to(ROOT).parts)]


def problems() -> list[str]:
    """Each line that breaks a rule, as "path:line: what: the line"."""
    found = []
    for path in tracked_files():
        if path.suffix.lower() in BINARY or path == Path(__file__).resolve() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue  # not a text file
        for number, line in enumerate(lines, 1):
            what = [name for char, name in BANNED_CHARACTERS.items() if char in line]
            checked = line
            for name in THIRD_PARTY_NAMES:
                checked = checked.replace(name, "")
            what += [f'British spelling "{m.group(0)}"' for m in BRITISH.finditer(checked)]
            if what:
                found.append(f"{path.relative_to(ROOT)}:{number}: {', '.join(what)}: {line.strip()[:100]}")
    return found


def test_writing_rules():
    found = problems()
    assert not found, "Writing rules (see CONTRIBUTING.md, Rules):\n" + "\n".join(found)


def test_the_check_catches_what_it_should():
    for bad in ("the colour scheme", "We analysed it", "It was cancelled", "Customise it", "the centre"):
        assert BRITISH.search(bad), bad
    for good in ("the color scheme", "two analyses", "It was canceled", "Customize it", "the center", "exercise", "parameter",
                 "characteristic", "specialist", "programmer", "advertise", "cancellation"):
        assert not BRITISH.search(good), good
