"""Which countries a search area covers, for the sources that only list one country's jobs.

The source catalog (collectors/catalog.py) runs a national job service only for people in that country, so it needs the
countries behind the search area: "Ohio" is the United States, "Toronto, ON" is Canada, "Germany" is all of Germany.

The location filter (textutil.LocationMatcher) is built around US places. It reads "Hamburg, DE" as Delaware and "Leeds,
England" as outside the area even for someone who searches all of the UK. Area fixes that for jobs from a service that
is known to list only one country: a job tagged with its country (RawJob.meta["country"]) is judged by the country, and
nothing changes for any other job.

Nothing here touches the network, the database or the AI."""
import re

from jobportal.core.textutil import NATIONWIDE_RE, REMOTE_RE, STATES, clean, state_of

EU = ("AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
      "PL", "PT", "RO", "SK", "SI", "ES", "SE")
EUROPE = (*EU, "IS", "LI", "NO", "CH", "GB")  # the EU and its neighbors that share its job portal or job market
# Names that cover several countries at once.
REGIONS = {"europe": EUROPE, "eu": EU, "european union": EU, "nordics": ("DK", "FI", "IS", "NO", "SE"),
           "scandinavia": ("DK", "NO", "SE"), "benelux": ("BE", "NL", "LU"), "dach": ("DE", "AT", "CH")}
# Country names people type, in English and in the country's own language. Keys are lowercase.
COUNTRY_NAMES = {
    "united states": "US", "united states of america": "US", "usa": "US", "us": "US", "u.s.": "US", "u.s.a.": "US", "america": "US",
    "canada": "CA", "united kingdom": "GB", "uk": "GB", "u.k.": "GB", "great britain": "GB", "britain": "GB",
    "ireland": "IE", "eire": "IE", "australia": "AU", "new zealand": "NZ", "aotearoa": "NZ",
    "germany": "DE", "deutschland": "DE", "france": "FR", "spain": "ES", "espana": "ES", "españa": "ES", "portugal": "PT",
    "italy": "IT", "italia": "IT", "netherlands": "NL", "the netherlands": "NL", "holland": "NL", "nederland": "NL",
    "belgium": "BE", "belgie": "BE", "belgique": "BE", "luxembourg": "LU", "austria": "AT", "osterreich": "AT", "österreich": "AT",
    "switzerland": "CH", "schweiz": "CH", "suisse": "CH", "svizzera": "CH", "sweden": "SE", "sverige": "SE",
    "norway": "NO", "norge": "NO", "denmark": "DK", "danmark": "DK", "finland": "FI", "suomi": "FI", "iceland": "IS",
    "poland": "PL", "polska": "PL", "czech republic": "CZ", "czechia": "CZ", "slovakia": "SK", "hungary": "HU", "romania": "RO",
    "bulgaria": "BG", "greece": "GR", "croatia": "HR", "slovenia": "SI", "estonia": "EE", "latvia": "LV", "lithuania": "LT",
    "malta": "MT", "cyprus": "CY", "liechtenstein": "LI", "serbia": "RS", "ukraine": "UA", "turkey": "TR", "russia": "RU",
    "singapore": "SG", "malaysia": "MY", "indonesia": "ID", "philippines": "PH", "thailand": "TH", "vietnam": "VN", "india": "IN",
    "pakistan": "PK", "bangladesh": "BD", "sri lanka": "LK", "nepal": "NP", "china": "CN", "hong kong": "HK", "taiwan": "TW",
    "japan": "JP", "south korea": "KR", "korea": "KR", "israel": "IL", "saudi arabia": "SA", "united arab emirates": "AE",
    "uae": "AE", "qatar": "QA", "kuwait": "KW", "bahrain": "BH", "oman": "OM", "jordan": "JO", "lebanon": "LB", "egypt": "EG",
    "morocco": "MA", "tunisia": "TN", "algeria": "DZ", "nigeria": "NG", "ghana": "GH", "kenya": "KE", "uganda": "UG",
    "tanzania": "TZ", "ethiopia": "ET", "rwanda": "RW", "south africa": "ZA", "mexico": "MX", "méxico": "MX", "brazil": "BR",
    "brasil": "BR", "argentina": "AR", "chile": "CL", "colombia": "CO", "peru": "PE", "ecuador": "EC", "uruguay": "UY",
    "costa rica": "CR", "panama": "PA", "dominican republic": "DO", "jamaica": "JM", "puerto rico": "PR",
}
# Each country's usual English name, by code: the first name listed for it above.
NAMES = {code: name.title() for name, code in reversed(COUNTRY_NAMES.items())}
# Parts of a country that people name instead of the country. A place here narrows the area, unlike a country name.
COUNTRY_PARTS = {
    "england": "GB", "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "ontario": "CA", "quebec": "CA", "québec": "CA", "british columbia": "CA", "alberta": "CA", "manitoba": "CA",
    "saskatchewan": "CA", "nova scotia": "CA", "new brunswick": "CA", "newfoundland": "CA", "prince edward island": "CA",
    "new south wales": "AU", "queensland": "AU", "victoria": "AU", "south australia": "AU", "western australia": "AU",
    "tasmania": "AU", "northern territory": "AU", "bavaria": "DE", "bayern": "DE", "berlin": "DE", "catalonia": "ES",
}
# Large cities people often write without a country, and the two-letter region codes that follow a town in Canada and
# Australia. The US is handled by textutil.state_of, which knows every state and many cities.
BIG_CITIES = {
    "london": "GB", "manchester": "GB", "leeds": "GB", "glasgow": "GB", "edinburgh": "GB", "cardiff": "GB",
    "belfast": "GB", "bristol": "GB", "liverpool": "GB", "sheffield": "GB", "newcastle": "GB", "nottingham": "GB",
    "dublin": "IE", "cork": "IE", "toronto": "CA", "montreal": "CA", "montréal": "CA", "vancouver": "CA", "calgary": "CA",
    "edmonton": "CA", "ottawa": "CA", "winnipeg": "CA", "halifax": "CA", "quebec city": "CA",
    "sydney": "AU", "melbourne": "AU", "brisbane": "AU", "perth": "AU", "adelaide": "AU", "canberra": "AU", "hobart": "AU",
    "auckland": "NZ", "wellington": "NZ", "christchurch": "NZ", "paris": "FR", "lyon": "FR", "marseille": "FR", "toulouse": "FR",
    "hamburg": "DE", "munich": "DE", "münchen": "DE", "frankfurt": "DE", "cologne": "DE", "köln": "DE", "stuttgart": "DE",
    "dusseldorf": "DE", "düsseldorf": "DE", "vienna": "AT", "wien": "AT", "zurich": "CH", "zürich": "CH", "geneva": "CH",
    "genève": "CH", "basel": "CH", "bern": "CH", "amsterdam": "NL", "rotterdam": "NL", "the hague": "NL", "utrecht": "NL",
    "brussels": "BE", "antwerp": "BE", "madrid": "ES", "barcelona": "ES", "valencia": "ES", "seville": "ES", "lisbon": "PT",
    "porto": "PT", "rome": "IT", "milan": "IT", "milano": "IT", "naples": "IT", "turin": "IT", "stockholm": "SE", "gothenburg": "SE",
    "malmo": "SE", "malmö": "SE", "oslo": "NO", "bergen": "NO", "copenhagen": "DK", "helsinki": "FI", "tampere": "FI",
    "warsaw": "PL", "krakow": "PL", "kraków": "PL", "wroclaw": "PL", "gdansk": "PL", "prague": "CZ", "budapest": "HU",
    "bucharest": "RO", "athens": "GR", "lagos": "NG", "abuja": "NG", "nairobi": "KE", "johannesburg": "ZA", "cape town": "ZA",
    "mumbai": "IN", "delhi": "IN", "bangalore": "IN", "bengaluru": "IN", "hyderabad": "IN", "chennai": "IN", "pune": "IN",
    "tokyo": "JP", "osaka": "JP", "seoul": "KR", "beijing": "CN", "shanghai": "CN", "shenzhen": "CN", "kuala lumpur": "MY",
    "jakarta": "ID", "manila": "PH", "bangkok": "TH", "dubai": "AE", "abu dhabi": "AE", "riyadh": "SA", "doha": "QA",
    "tel aviv": "IL", "cairo": "EG", "sao paulo": "BR", "são paulo": "BR", "rio de janeiro": "BR", "mexico city": "MX",
    "buenos aires": "AR", "bogota": "CO", "bogotá": "CO", "lima": "PE", "santiago": "CL",
}
REGION_CODES = {"ON": "CA", "QC": "CA", "BC": "CA", "AB": "CA", "MB": "CA", "SK": "CA", "NS": "CA", "NB": "CA", "NL": "CA",
                "PE": "CA", "YT": "CA", "NT": "CA", "NU": "CA", "NSW": "AU", "VIC": "AU", "QLD": "AU", "TAS": "AU", "ACT": "AU"}
# A region code at the end of a place ("Toronto, ON", "Geelong VIC 3220"). Capitals only, so "on" stays a word. Canada's codes
# that double as US states (AB is none, but NE or SC never appear here) are left to the comma form the postings use.
_REGION_CODE_RE = re.compile(r"(?:,\s*|\s)(" + "|".join(REGION_CODES) + r")(?:\s+\d{4})?\s*$")


def code_of(name: str) -> str:
    """The ISO country code for a country's name, or "" when it isn't one. Case doesn't matter."""
    return COUNTRY_NAMES.get(clean(name).lower().rstrip("."), "")


def read_place(entry: str) -> tuple[set[str], bool]:
    """(the countries a search area entry is in, whether it covers them whole).

    "Germany" gives ({"DE"}, True), "Europe" every country in it with True, "Toronto, ON" ({"CA"}, False), "Ohio" ({"US"},
    False) and "Anywhere in the US" ({"US"}, True). "Remote, Germany" names the country but not all of its jobs, so it's
    not whole. A plain "Remote", or a place nothing here recognizes, gives (set(), False)."""
    text = clean(entry)
    low = text.lower().rstrip(".")
    if not low:
        return set(), False
    if NATIONWIDE_RE.fullmatch(low):
        return {"US"}, True
    if REMOTE_RE.search(text):
        words = clean(re.sub(r"\b(?:remote|anywhere|work from home|wfh|in|from|the|within|only)\b|[-,:()]", " ", low))
        codes = set(REGIONS.get(words, ())) or ({code_of(words)} if code_of(words) else set())
        return codes, bool(codes) and "anywhere" in low
    if low in REGIONS:
        return set(REGIONS[low]), True
    if code_of(low):
        return {code_of(low)}, True
    if low in COUNTRY_PARTS:
        return {COUNTRY_PARTS[low]}, False
    # "Berlin, Germany" or "Leeds, UK": the last part names the country.
    tail = low.rsplit(",", 1)[-1].strip()
    if "," in low and code_of(tail):
        return {code_of(tail)}, False
    if "," in low and tail in COUNTRY_PARTS:
        return {COUNTRY_PARTS[tail]}, False
    region = _REGION_CODE_RE.search(text)
    if region:
        return {REGION_CODES[region.group(1)]}, False
    if state_of(text) in STATES:  # a US state or a US city in its table, read before the world's cities
        return {"US"}, False
    if low in BIG_CITIES:
        return {BIG_CITIES[low]}, False
    return set(), False


class Area:
    """The countries a search area covers: `whole` (the user named the country, or lives there and named no place) and
    `inside` (they named a part of it, such as a city or a province)."""

    def __init__(self, allowed: list[str] | None, home: str = ""):
        self.whole: set[str] = set()
        self.inside: set[str] = set()
        named_a_place = False
        for entry in allowed or []:
            codes, is_whole = read_place(entry)
            if NATIONWIDE_RE.fullmatch(clean(entry).lower()) or REMOTE_RE.search(entry):
                # The default search area (see onboarding.allowed_locations) says "Anywhere in the US" or "Remote"
                # whatever the person's country is, so it doesn't count as choosing a place.
                pass
            elif entry.strip():
                named_a_place = True
            (self.whole if is_whole else self.inside).update(codes)
        country = code_of(home)
        if country:
            (self.inside if named_a_place else self.whole).add(country)
        self.inside -= self.whole

    def countries(self) -> list[str]:
        """Every country the area touches, sorted."""
        return sorted(self.whole | self.inside)

    def judge(self, in_area: bool | None, country: str | None) -> bool | None:
        """The location filter's answer for a job from a service that only lists `country`.

        The whole country is in the area: True, whatever the town is called. A part of it is: the filter's False was only a
        guess, because it doesn't know that country's towns, so it becomes None and AI triage decides (it sees the allowed
        locations). Any other country, and every US job, keeps the filter's answer, so this widens nothing for them."""
        if in_area is True or not country or country == "US":
            return in_area
        if country in self.whole:
            return True
        if country in self.inside:
            return None
        return in_area
