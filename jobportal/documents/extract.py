"""Reading imported resumes: turns a PDF, Word, OpenDocument, RTF, Markdown or plain-text file into plain text.

Who calls it: candidate/onboarding.py (the resume imported during setup) and candidate/library.py (files added to the resume
collection) call extract_text(). render.py borrows pdf_page_count() to count the pages of a printed resume.

Everything except old word processor files is read in pure Python (pypdf, python-docx and the standard library), so it
works the same on Windows, macOS and Linux with nothing else installed. Old Word (.doc), Apple Pages (.pages) and Microsoft
Works (.wps) files go through LibreOffice when it is installed. pypdf and python-docx load on first use, which keeps the
app's startup quick.

Each reader below explains its format's quirks. Errors reach the user, so every failure becomes an ExtractError with a
message written for them."""
import html
import io
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from jobportal.core import osutil
from jobportal.core.config import CACHE

SUPPORTED = (".pdf", ".docx", ".odt", ".rtf", ".md", ".markdown", ".txt", ".doc", ".pages", ".wps")
ACCEPT = ",".join(SUPPORTED)  # for the file picker's accept attribute (sent to the dashboard by onboarding.state)
MIN_CHARS = 80  # less text than this can't be a resume: usually a scanned PDF, which holds only pictures of text


class ExtractError(ValueError):
    """A file that can't be read. The message is shown to the user as is."""


def _decode(data: bytes) -> str:
    """Bytes of a text file as a string. A byte order mark means UTF-16 (or UTF-8, whose mark is dropped). Anything that
    isn't valid UTF-8 is read as Windows-1252, the usual encoding of older Windows text files."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "ignore")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", "ignore")


def _tidy(text: str) -> str:
    """Normalize line endings and whitespace. Long runs of spaces (how PDF layout text marks columns) shrink to three
    spaces, which still shows the column break, and runs of blank lines shrink to one."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")  # \x0c is a page break
    text = re.sub(r"[ \t\xa0]{4,}", "   ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------- PDF

def pdf_text(data: bytes) -> str:
    """Text of every page. A PDF has no lines or paragraphs, only pieces of text placed at positions on the page. pypdf's
    layout mode rebuilds lines from those positions and keeps the columns of a two-column resume apart; the plain mode is
    the fallback for files the stricter layout mode can't handle. A scanned PDF holds only images and yields no text."""
    from pypdf import PdfReader
    pages = []
    for page in PdfReader(io.BytesIO(data)).pages:
        try:
            text = page.extract_text(extraction_mode="layout")
        except Exception:  # noqa: BLE001 (layout mode is stricter; plain mode reads anything)
            text = page.extract_text()
        pages.append(text or "")
    return "\n\n".join(pages)


def pdf_page_count(path: Path) -> int:
    """How many pages the PDF at path has, or 0 when it can't be read."""
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------- DOCX
#
# A .docx file is a zip of XML files. word/document.xml holds the body: paragraphs (w:p) and tables (w:tbl) in reading order.
# Headers and footers live in their own parts. A paragraph's text sits in runs (w:r), each a stretch of text with one format.
# python-docx's Paragraph.text only reads runs that sit directly in the paragraph (or in a link), and its document walk only
# sees paragraphs and tables directly in the body. Word's resume templates wrap content in content controls (w:sdt), so this
# reader walks the XML itself to keep that text.

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"  # Word's XML namespace, the way lxml writes tag names
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_WRAPPERS = {_W + "sdt", _W + "sdtContent", _W + "customXml"}  # elements that only wrap ordinary content
# Run children that carry text, and what each one reads as (None means the element's own text).
_RUN_TEXT = {_W + "t": None, _W + "tab": "\t", _W + "ptab": "\t", _W + "br": "\n", _W + "cr": "\n", _W + "noBreakHyphen": "-"}
# Text inside these is skipped. A text box (w:txbxContent) holds paragraphs of its own that would run into the line that
# anchors it, and Word stores each one twice: a modern copy and a fallback copy (mc:Fallback) for older readers. With track
# changes on, w:del holds deleted text and w:moveFrom the old position of moved text.
_SKIPPED = {_W + "txbxContent", _W + "del", _W + "moveFrom", _MC + "Fallback"}


def _blocks(element, tags: set[str]):
    """The children of element with one of these tags, in order, looking through content controls and other wrappers."""
    for child in element:
        if child.tag in tags:
            yield child
        elif child.tag in _WRAPPERS:
            yield from _blocks(child, tags)


def _paragraph_text(paragraph) -> str:
    """Text of one w:p element: every run inside it, including runs in content controls, links, fields and tracked
    insertions."""
    pieces = []
    for element in paragraph.iter(*_RUN_TEXT):
        # w:tab also defines tab stops in the paragraph's properties; only the ones inside a run are text.
        if element.getparent().tag != _W + "r" or any(a.tag in _SKIPPED for a in element.iterancestors()):
            continue
        meaning = _RUN_TEXT[element.tag]
        pieces.append((element.text or "") if meaning is None else meaning)
    return "".join(pieces)


def _block_lines(container) -> list[str]:
    """Lines of text from a body, header, footer or table cell, in reading order. A paragraph is one line. A table row is
    one line with its cells separated by three spaces (a cell can hold whole paragraphs, or another table)."""
    lines = []
    for block in _blocks(container, {_W + "p", _W + "tbl"}):
        if block.tag == _W + "p":
            lines.append(_paragraph_text(block))
            continue
        for row in _blocks(block, {_W + "tr"}):
            cells = ["\n".join(_block_lines(cell)).strip() for cell in _blocks(row, {_W + "tc"})]
            lines.append("   ".join(cell for cell in cells if cell))
    return lines


def _header_footer_lines(doc, kinds: tuple[str, ...]) -> list[str]:
    """Non-blank lines of each section's headers or footers (kinds are python-docx section attributes such as "header").
    A header "linked to previous" shows the previous section's, or doesn't exist, so it is skipped and never read twice."""
    lines = []
    for section in doc.sections:
        for kind in kinds:
            part = getattr(section, kind)
            try:
                if not part.is_linked_to_previous:
                    lines += [line for line in _block_lines(part.part.element) if line.strip()]
            except Exception:  # noqa: BLE001 (a broken header must not stop the resume text from loading)
                continue
    return lines


def docx_text(data: bytes) -> str:
    """Headers, then the body (paragraphs and tables in reading order), then footers. Contact details often sit in the
    header, sometimes in a table there."""
    from docx import Document
    doc = Document(io.BytesIO(data))
    lines = _header_footer_lines(doc, ("header", "first_page_header"))
    lines += _block_lines(doc.element.body)
    lines += _header_footer_lines(doc, ("footer", "first_page_footer"))
    return "\n".join(lines)


# ---------------------------------------------------------------- ODT

def odt_text(data: bytes) -> str:
    """An OpenDocument text file (LibreOffice's own format) is a zip whose content.xml holds the text. Its markup is simple
    enough to flatten with regular expressions. Tabs and line breaks are elements, a paragraph or heading ends with
    </text:p> or </text:h>, and runs of spaces are stored as <text:s text:c="N"/>."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("content.xml").decode("utf-8", "ignore")
    xml = re.sub(r"<text:tab/>", "\t", xml)
    xml = re.sub(r"<text:line-break/>", "\n", xml)
    xml = re.sub(r"</text:(p|h)>", "\n", xml)
    xml = re.sub(r"<text:s(?: text:c=\"(\d+)\")?/>", lambda m: " " * int(m.group(1) or 1), xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))  # drop the remaining tags, then turn &amp; and friends back into text


# ---------------------------------------------------------------- RTF
#
# RTF is plain text with markup. { and } open and close groups. A backslash starts a control: a word with an optional
# number (\b bold, \fs22 font size, \par paragraph end), a hex byte (\'e9 is é in the Windows-1252 code page), or an escaped
# symbol (\{ \} \\). \uN is a Unicode character. Fallback characters for readers without Unicode follow it (how many is set
# by \ucN, 1 by default), and those must be dropped. Some groups (font tables, pictures and so on) aren't document text.

# Groups whose text is never part of the document: font and color tables, style sheets, document info, pictures, headers
# and footers, list definitions, revision tables, embedded objects and field instructions (a link's address, for example).
_RTF_SKIPPED_GROUPS = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer", "headerl", "headerr", "footerl",
                       "footerr", "listtable", "listoverridetable", "rsidtbl", "generator", "xmlnstbl", "themedata",
                       "colorschememapping", "latentstyles", "datastore", "object", "fldinst"}
# Control words that stand for text.
_RTF_SYMBOLS = {"par": "\n", "line": "\n", "sect": "\n", "page": "\n", "row": "\n", "tab": "\t", "cell": "\t",
                "emdash": "\u2014", "endash": "\u2013", "bullet": "\u2022", "lquote": "\u2018", "rquote": "\u2019",
                "ldblquote": "\u201c", "rdblquote": "\u201d", "emspace": " ", "enspace": " ", "qmspace": " "}
_RTF_CONTROL = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\([\s\S])")  # word + number, hex byte, or symbol


def rtf_text(data: bytes) -> str:
    """A small RTF reader. Keeps the text, paragraph breaks and tabs; drops formatting, pictures and other hidden groups."""
    s = data.decode("latin-1")  # RTF itself is ASCII; latin-1 maps every byte to one character, so nothing is lost
    out: list[str] = []
    stack: list[tuple[bool, int]] = []  # the (skip, uc) state of each enclosing group, restored when the group closes
    skip = False  # inside a group whose text isn't document text
    uc = 1  # how many fallback characters follow each \uN
    pending = 0  # fallback characters still to drop after the last \uN
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "{":
            stack.append((skip, uc))
            i += 1
            continue
        if ch == "}":
            skip, uc = stack.pop() if stack else (False, 1)
            i += 1
            continue
        if ch != "\\":
            if ch not in "\r\n":  # line breaks in the file itself mean nothing; \par marks paragraphs
                if pending:
                    pending -= 1
                elif not skip:
                    out.append(ch)
            i += 1
            continue
        m = _RTF_CONTROL.match(s, i)  # match at i without copying the rest of the file
        if not m:  # a lone backslash at the very end
            break
        i = m.end()
        word, arg, hex_byte, symbol = m.groups()
        if hex_byte:
            if pending:
                pending -= 1
            elif not skip:
                out.append(bytes([int(hex_byte, 16)]).decode("cp1252", "ignore"))
        elif symbol:
            if symbol == "*":  # "\*" marks a group that readers which don't know it must skip
                skip = True
            elif skip:
                continue
            elif symbol in "\\{}":
                out.append(symbol)
            elif symbol in "\r\n":  # a backslash before a line break is a paragraph break (TextEdit on macOS writes these)
                out.append("\n")
            elif symbol == "~":  # non-breaking space
                out.append(" ")
            elif symbol == "_":  # non-breaking hyphen
                out.append("-")
        elif word in _RTF_SKIPPED_GROUPS:
            skip = True
        elif skip:
            continue
        elif word == "uc":
            uc = int(arg or 1)
        elif word == "u":
            code = int(arg or 0)
            out.append(chr(code + 65536 if code < 0 else code))  # RTF numbers are signed 16-bit, so big ones come out negative
            pending = uc
        elif word in _RTF_SYMBOLS:
            out.append(_RTF_SYMBOLS[word])
    # Characters beyond the 16-bit range (emoji) arrive as two \u halves (a surrogate pair). Joining them as UTF-16 makes
    # one character; a stray half becomes the replacement character instead of breaking later code.
    return "".join(out).encode("utf-16", "surrogatepass").decode("utf-16", "replace")


# ---------------------------------------------------------------- old formats through LibreOffice

def _soffice_text(name: str, data: bytes) -> str:
    """Convert an old Word, Pages or Works file to text by running LibreOffice headless (a subprocess, up to 3 minutes).
    Works in a temporary folder inside the cache, which is removed afterwards."""
    soffice = osutil.find_soffice()
    if not soffice:
        raise ExtractError(f"{Path(name).suffix} files need LibreOffice to read. Save the resume as PDF or DOCX and import that instead.")
    CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=CACHE, ignore_cleanup_errors=True) as tmp:
        src = Path(tmp) / f"resume{Path(name).suffix.lower()}"
        src.write_bytes(data)
        # A throwaway LibreOffice profile. With the user's own, a LibreOffice window that is already open would take the job
        # and this call would return before the text file exists.
        profile = (Path(tmp) / "lo-profile").as_uri()
        subprocess.run([soffice, "--headless", f"-env:UserInstallation={profile}", "--convert-to", "txt:Text", "--outdir", tmp, str(src)],
                       capture_output=True, timeout=180, **osutil.popen_flags())
        out = Path(tmp) / "resume.txt"
        # LibreOffice writes UTF-8 starting with a byte order mark; _decode drops the mark and copes with other encodings.
        return _decode(out.read_bytes()) if out.exists() else ""


def extract_text(name: str, data: bytes) -> str:
    """Plain text of one resume file, picked by its extension (a file without one is read as text). Raises ExtractError
    with a message meant for the user when the file can't be read or holds too little text."""
    suffix = Path(name or "").suffix.lower()
    try:
        if suffix in (".md", ".markdown", ".txt", ""):
            text = _decode(data)
        elif suffix == ".pdf":
            text = pdf_text(data)
        elif suffix == ".docx":
            text = docx_text(data)
        elif suffix == ".odt":
            text = odt_text(data)
        elif suffix == ".rtf":
            text = rtf_text(data)
        elif suffix in (".doc", ".pages", ".wps"):
            text = _soffice_text(name, data)
        else:
            raise ExtractError(f"{suffix} files aren't supported. Use PDF, DOCX, ODT, RTF, Markdown or plain text.")
    except ExtractError:
        raise
    except (zipfile.BadZipFile, KeyError, ValueError, OSError, subprocess.SubprocessError) as e:
        raise ExtractError(f"couldn't read {name}: {e}") from e
    except Exception as e:  # noqa: BLE001 (third-party parsers raise their own error types)
        raise ExtractError(f"couldn't read {name}: {type(e).__name__}: {e}") from e
    text = _tidy(text)
    if len(text) < MIN_CHARS:
        raise ExtractError("couldn't find any text in that file. A scanned (image) PDF can't be read; export a text PDF or DOCX instead.")
    return text
