"""The parsers behind the source catalog (catalog.py) and the company boards (ats.py). Each turns one response into plain
records, so one parser serves every site with the same format: feeds (RSS and Atom), other XML, JSON, HTML job cards,
schema.org JobPosting blocks, JSON embedded in a page, and sitemaps.

pick() then reads a record's fields from a small description of where they are:
  "title"                 a key
  "employer.name"         a path through nested objects ("items.0.title" takes the first item of a list)
  "locations[].city"      the same key from every item of a list, as a list
  ("title", "name")       a tuple: the first that has a value
  ["city", "state"]       a list: every part that has a value, joined with ", "
  "https://x.com/{id}"    text with braces: a template filled in from the record
  lambda record: ...      anything else

Nothing here touches the network, the database or the AI."""
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urljoin, urlparse

from jobportal.core.textutil import clean, html_to_text

EMPTY = (None, "", [], {}, ())


def _local(tag) -> str:
    """An XML tag's name without its namespace."""
    return str(tag).rsplit("}", 1)[-1]


def _root(body) -> ET.Element | None:
    """The root of an XML document, or None for anything that isn't valid XML."""
    try:
        return ET.fromstring(body)
    except (ET.ParseError, ValueError, TypeError):
        return None


def feed_records(body) -> list[dict]:
    """The items of an RSS feed (<item>, versions 1.0 and 2.0) or an Atom feed (<entry>), each as {tag: text} with the
    namespaces dropped. The first of a repeated tag wins, and "link" is the address whichever way the format writes it."""
    root = _root(body)
    if root is None:
        return []
    out = []
    for item in root.iter():
        if _local(item.tag) not in ("item", "entry"):
            continue
        record: dict = {}
        for child in item:
            name = _local(child.tag)
            if name == "link":  # Atom: <link rel="alternate" href="...">, RSS: <link>...</link>
                href = child.get("href")
                if not href:
                    href = (child.text or "").strip()
                elif child.get("rel", "alternate") != "alternate":
                    continue
                if href:
                    record.setdefault("link", href)
            elif name not in record:
                record[name] = "".join(child.itertext()).strip()
        if not record.get("link") and item.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"):
            record["link"] = item.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about")  # RSS 1.0
        out.append(record)
    return out


def element_record(element: ET.Element):
    """An XML element as plain data: its text when it has no children, else {tag: value} with repeated tags as a list."""
    children = list(element)
    if not children:
        return (element.text or "").strip()
    out: dict = {}
    for child in children:
        name, value = _local(child.tag), element_record(child)
        if name not in out:
            out[name] = value
        elif isinstance(out[name], list):
            out[name].append(value)
        else:
            out[name] = [out[name], value]
    return out


def xml_records(body, tag: str) -> list:
    """Every <tag> element of an XML document, as plain data (see element_record)."""
    root = _root(body)
    if root is None:
        return []
    return [element_record(e) for e in root.iter() if _local(e.tag) == tag]


def dig(value, path: str):
    """A value from nested objects and lists by a dotted path (see the module docstring), or None."""
    parts = path.split(".")
    for i, part in enumerate(parts):
        if value is None:
            return None
        if part.endswith("[]"):
            items = dig(value, part[:-2]) if part[:-2] else value
            if not isinstance(items, list):
                items = [items] if isinstance(items, dict) else []
            rest = ".".join(parts[i + 1:])
            found = [dig(item, rest) if rest else item for item in items]
            return [x for x in found if x not in EMPTY]
        if isinstance(value, list):
            value = value[int(part)] if part.isdigit() and int(part) < len(value) else None
        elif isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def pick(record, spec):
    """One field of a record, read by `spec` (see the module docstring)."""
    if spec is None:
        return None
    if callable(spec):
        try:
            return spec(record)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):  # one odd record costs only this field
            return None
    if isinstance(spec, tuple):
        return next((v for v in (pick(record, s) for s in spec) if v not in EMPTY), None)
    if isinstance(spec, list):
        return ", ".join(str(v) for v in (pick(record, s) for s in spec) if v not in EMPTY)
    if "{" in spec:
        return re.sub(r"\{([\w.\[\]-]+)\}", lambda m: str(dig(record, m.group(1)) or ""), spec)
    return dig(record, spec)


def text_of(html) -> str:
    """A piece of HTML as one clean line of text."""
    return clean(html_to_text(str(html))) if html not in EMPTY else ""


def card_records(body: str, spec: dict, base_url: str) -> list[dict]:
    """The jobs on an HTML list page, each as {"url", "title", ...}, by a description of what one job looks like:

      link      a regex: group 1 is the job's address, and group 2, when there is one, its title
      card      optional, a regex for where each job starts. Without it a job runs from its link to the next link
      title, company, location, date, description    optional regexes, each read from the job's piece of the page
                (group 1). A title is required, from `link` or from `title`
      skip      optional, a regex: a job whose address matches it is left out

    Each job appears once, however many times the page links to it. Addresses are made absolute."""
    body = " ".join(body.split())  # so a pattern needn't care how a page breaks its tags over lines
    link = re.compile(spec["link"], re.S)
    if spec.get("card"):
        chunks = re.split(spec["card"], body)[1:]
    else:
        starts = [m.start() for m in link.finditer(body)]
        chunks = [body[a:b] for a, b in zip(starts, starts[1:] + [len(body)])]
    out, seen = [], set()
    for chunk in chunks:
        found = link.search(chunk)
        if not found:
            continue
        url = urljoin(base_url, found.group(1).replace("&amp;", "&").strip())
        if url in seen or (spec.get("skip") and re.search(spec["skip"], url)):
            continue
        record = {"url": url}
        if found.re.groups >= 2:
            record["title"] = text_of(found.group(2))
        for name in ("title", "company", "location", "date", "description"):
            pattern = spec.get(name)
            if pattern and not record.get(name):
                hit = re.search(pattern, chunk, re.S)
                record[name] = text_of(next((g for g in hit.groups() if g), "")) if hit else ""
        if record.get("title"):
            seen.add(url)
            out.append(record)
    return out


def row_records(body: str, pattern: str) -> list[dict]:
    """The jobs on a page that writes each one in a single pattern: one record per match, from the pattern's named groups.
    An exact repeat of a match counts once."""
    out, seen = [], set()
    for match in re.finditer(pattern, " ".join(body.split()), re.S):
        record = match.groupdict()
        key = tuple(record.values())
        if key not in seen:
            seen.add(key)
            out.append(record)
    return out


def jsonld_postings(html: str) -> list[dict]:
    """Every schema.org JobPosting in a page's JSON-LD blocks. A block may hold one object, a list, an "@graph" list or an
    ItemList of postings."""
    out = []
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        waiting = list(data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else [])
        while waiting:
            item = waiting.pop(0)
            if not isinstance(item, dict):
                continue
            if "ItemList" in str(item.get("@type")):
                waiting += [e.get("item", e) for e in item.get("itemListElement") or [] if isinstance(e, dict)]
            elif "JobPosting" in str(item.get("@type")):  # @type can be a string or a list
                out.append(item)
    return out


def ld_location(posting: dict) -> str:
    """A JobPosting's locations as "City, ST | City, ST", plus "Remote" when it is marked as telecommuting. Sites write a
    place as a Place object with an address, or as plain text ("Remote", "Columbus, OH"), which is used as it is."""
    places = posting.get("jobLocation") or []
    places = places if isinstance(places, list) else [places]
    out = []
    for place in places:
        if isinstance(place, str):
            out.append(clean(place))
            continue
        address = (place.get("address") or {}) if isinstance(place, dict) else {}
        if isinstance(address, str):
            out.append(clean(address))
        elif isinstance(address, dict):
            out.append(", ".join(x for x in [address.get("addressLocality"), address.get("addressRegion")] if x))
    if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        out.append("Remote")
    return " | ".join(o for o in out if o)


def embedded_json(page: str, marker: str):
    """The JSON value that starts right after `marker` in a page (such as `window.pageData =`, or the __NEXT_DATA__ script
    tag), or None when there isn't a readable one."""
    at = page.find(marker)
    if at < 0:
        return None
    start = at + len(marker)
    while start < len(page) and page[start] not in "{[":
        if start > at + len(marker) + 200:  # the value should come right after the marker
            return None
        start += 1
    try:
        value, _ = json.JSONDecoder().raw_decode(page, start)
    except (json.JSONDecodeError, ValueError):
        return None
    return value


def sitemap_urls(body: str) -> list[str]:
    """Every page address in a sitemap. A plain pattern, because a sitemap can run to many megabytes."""
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)


def slug_title(url: str) -> str:
    """A readable title from the last part of an address: ".../2127857-0/business-analyst" gives "Business analyst"."""
    last = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
    words = re.sub(r"[-_+]+", " ", last).strip()
    return words[:1].upper() + words[1:]
