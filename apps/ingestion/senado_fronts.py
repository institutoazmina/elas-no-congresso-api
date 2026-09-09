"""Safe parsing and fetching of Senado parliamentary-front pages."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

SENADO_WEB_HOST = "www25.senado.leg.br"
SENADO_LEGIS_HOST = "legis.senado.leg.br"
CAMARA_PROFILE_HOST = "www.camara.leg.br"
SENADO_FRONT_HOSTS = frozenset({SENADO_WEB_HOST, SENADO_LEGIS_HOST})
SENADO_FRONT_CATALOG_URL = (
    "https://www25.senado.leg.br/web/atividade/conselhos/-/conselho/frentes-parlamentares"
)
SENADO_FRONT_MAX_BYTES = 2 * 1024 * 1024
SENADO_FRONT_MAX_PAGES = 200
SENADO_FRONT_MAX_FRONTS = 100
SENADO_FRONT_MAX_REDIRECTS = 3

_COUNCIL_PATH_PREFIX = "/web/atividade/conselhos/-/conselho/"
_LEGACY_COMPOSITION_PATH = re.compile(r"^/comissoes/composicao_comissao/?$")
_MODERN_COMPOSITION_PATH = re.compile(
    r"^/atividade/comissoes/comissao/(\d+)/composicao/lista-de-membros/?$"
)
_SENATOR_PROFILE_PATH = re.compile(r"^/web/senadores/senador/-/perfil/(\d+)/?$")
_DEPUTY_PROFILE_PATH = re.compile(r"^/deputados/(\d+)/?$")
_ACRONYM = re.compile(r"^[A-Z0-9][A-Z0-9./_-]{1,15}$")
_STATUS = re.compile(
    r"\b(?:ativa|inativa|encerrada|extinta|vigente|suspensa|em atividade)\b",
    re.IGNORECASE,
)
_ROLE = re.compile(
    r"\b(?:vice[- ]?presidente|presidente|coordenador(?:a)?|relator(?:a)?|membro)\b",
    re.IGNORECASE,
)


class UnsafeSenadoFrontUrlError(ValueError):
    """A front URL is not HTTPS and/or is outside the official allowlist."""


UnsafeSenadoFrontUrl = UnsafeSenadoFrontUrlError


class SenadoFrontPageLimitError(ValueError):
    """A front scrape exceeded its page, front, or response-size bound."""


@dataclass(frozen=True)
class SenadoFrontCatalogEntry:
    name: str
    acronym: str | None
    status: str | None
    council_url: str
    source_url: str


@dataclass(frozen=True)
class SenateFrontMember:
    house: str
    external_id: int
    profile_url: str
    role: str | None = None


@dataclass(frozen=True)
class SenadoFrontSnapshot:
    name: str
    acronym: str | None
    status: str | None
    council_url: str
    composition_url: str
    codcol: str
    members: tuple[SenateFrontMember, ...] = ()


@dataclass(frozen=True)
class SenadoFrontScrapeResult:
    fronts: tuple[SenadoFrontSnapshot, ...]
    failed_fronts: int = 0
    pages_fetched: int = 0


@dataclass
class _HtmlRow:
    cells: list[str]
    links: list[tuple[str, str]]


class _HtmlStructureParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[_HtmlRow] = []
        self.links: list[tuple[str, str]] = []
        self._row: _HtmlRow | None = None
        self._cell_parts: list[str] | None = None
        self._cell_links: list[tuple[str, str]] = []
        self._link_href: str | None = None
        self._link_parts: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        attributes = dict(attrs)
        if tag == "tr":
            if self._row is not None:
                self._finish_row()
            self._row = _HtmlRow([], [])
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
            self._cell_links = []
        elif tag == "a":
            self._link_href = attributes.get("href")
            self._link_parts = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.casefold()
        if tag == "a" and self._link_parts is not None:
            href = self._link_href or ""
            text = _clean_text(self._link_parts)
            link = (href, text)
            self.links.append(link)
            if self._row is not None:
                self._row.links.append(link)
            if self._cell_parts is not None:
                self._cell_links.append(link)
            self._link_href = None
            self._link_parts = None
        elif tag in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            self._row.cells.append(_clean_text(self._cell_parts))
            self._cell_parts = None
            self._cell_links = []
        elif tag == "tr" and self._row is not None:
            self._finish_row()

    def handle_data(self, data):
        if self._cell_parts is not None:
            self._cell_parts.append(data)
        if self._link_parts is not None:
            self._link_parts.append(data)

    def close(self):
        super().close()
        if self._row is not None:
            self._finish_row()

    def _finish_row(self):
        if self._row is not None:
            self.rows.append(self._row)
        self._row = None
        self._cell_parts = None
        self._cell_links = []


def _clean_text(parts: Iterable[str]) -> str:
    return " ".join("".join(parts).split())


def validate_senado_front_url(url: str, *, allow_camara_profile: bool = False) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    allowed_hosts = SENADO_FRONT_HOSTS | ({CAMARA_PROFILE_HOST} if allow_camara_profile else set())
    if (
        parsed.scheme.casefold() != "https"
        or host not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        raise UnsafeSenadoFrontUrl(f"untrusted Senado front URL: {url!r}")
    return urlunparse(("https", host, parsed.path, parsed.params, parsed.query, ""))


def _absolute_url(href: str, base_url: str) -> str:
    if not href:
        raise UnsafeSenadoFrontUrl("empty Senado front URL")
    return validate_senado_front_url(urljoin(base_url, href))


def _is_council_path(path: str) -> bool:
    normalized = path.rstrip("/")
    return (
        normalized.startswith(_COUNCIL_PATH_PREFIX)
        and normalized != _COUNCIL_PATH_PREFIX.rstrip("/")
        and normalized.rsplit("/", 1)[-1] != "frentes-parlamentares"
    )


def _catalog_entry(row: _HtmlRow, catalog_url: str) -> SenadoFrontCatalogEntry | None:
    council_url = None
    link_text = None
    for href, text in row.links:
        absolute = urljoin(catalog_url, href)
        parsed = urlparse(absolute)
        if "conselho" not in parsed.path.casefold():
            continue
        if not _is_council_path(parsed.path):
            continue
        council_url = _absolute_url(href, catalog_url)
        link_text = text or None
        break
    if council_url is None:
        return None

    cells = [cell for cell in row.cells if cell]
    name = link_text or (cells[0] if cells else None)
    if not name:
        return None
    acronym = next((cell for cell in cells if _ACRONYM.fullmatch(cell)), None)
    if acronym is None:
        match = re.search(r"\(([A-Z0-9]{2,15})\)", name)
        acronym = match.group(1) if match else None
    status = next((cell for cell in cells if _STATUS.search(cell)), None)
    return SenadoFrontCatalogEntry(
        name=name,
        acronym=acronym,
        status=status,
        council_url=council_url,
        source_url=catalog_url,
    )


def parse_senado_front_catalog(
    html: str,
    *,
    catalog_url: str = SENADO_FRONT_CATALOG_URL,
    max_fronts: int = SENADO_FRONT_MAX_FRONTS,
) -> list[SenadoFrontCatalogEntry]:
    catalog_url = validate_senado_front_url(catalog_url)
    parser = _HtmlStructureParser()
    parser.feed(html)
    parser.close()
    entries: list[SenadoFrontCatalogEntry] = []
    seen = set()
    for row in parser.rows:
        entry = _catalog_entry(row, catalog_url)
        if entry is None or entry.council_url in seen:
            continue
        if len(entries) >= max_fronts:
            raise SenadoFrontPageLimitError("Senado front count limit exceeded")
        entries.append(entry)
        seen.add(entry.council_url)
    return entries


def _composition_link(href: str, council_url: str) -> tuple[str, str] | None:
    absolute = urljoin(council_url, href)
    parsed = urlparse(absolute)
    path = parsed.path
    modern = _MODERN_COMPOSITION_PATH.fullmatch(path)
    legacy = _LEGACY_COMPOSITION_PATH.fullmatch(path)
    if not modern and not legacy:
        return None
    composition_url = _absolute_url(href, council_url)
    parsed = urlparse(composition_url)
    codcol = modern.group(1) if modern else parse_qs(parsed.query).get("codcol", [None])[0]
    if not codcol or not codcol.isdigit():
        raise ValueError("Senado composition URL has no numeric codcol")
    return composition_url, codcol


def parse_senado_front_council(
    entry: SenadoFrontCatalogEntry,
    html: str,
) -> SenadoFrontSnapshot:
    council_url = validate_senado_front_url(entry.council_url)
    parser = _HtmlStructureParser()
    parser.feed(html)
    parser.close()
    for href, _text in parser.links:
        result = _composition_link(href, council_url)
        if result is not None:
            composition_url, codcol = result
            return SenadoFrontSnapshot(
                name=entry.name,
                acronym=entry.acronym,
                status=entry.status,
                council_url=council_url,
                composition_url=composition_url,
                codcol=codcol,
            )
    raise ValueError(f"no Senado composition URL found for {council_url}")


def _profile_member(href: str, composition_url: str) -> tuple[str, int, str] | None:
    absolute = urljoin(composition_url, href)
    parsed = urlparse(absolute)
    senator = _SENATOR_PROFILE_PATH.fullmatch(parsed.path)
    if senator:
        profile_url = validate_senado_front_url(absolute)
        return "senado", int(senator.group(1)), profile_url
    deputy = _DEPUTY_PROFILE_PATH.fullmatch(parsed.path)
    if deputy:
        profile_url = validate_senado_front_url(absolute, allow_camara_profile=True)
        return "camara", int(deputy.group(1)), profile_url
    lowered_path = parsed.path.casefold()
    if "senador" in lowered_path or "deputado" in lowered_path:
        raise UnsafeSenadoFrontUrl(f"untrusted profile URL: {absolute!r}")
    return None


def _row_role(row: _HtmlRow) -> str | None:
    link_texts = {text.casefold() for _href, text in row.links}
    for cell in row.cells:
        if cell.casefold() in link_texts:
            continue
        match = _ROLE.search(cell)
        if match:
            return match.group(0)
    return None


def parse_senado_front_composition(
    html: str,
    composition_url: str,
) -> tuple[SenateFrontMember, ...]:
    composition_url = validate_senado_front_url(composition_url)
    parser = _HtmlStructureParser()
    parser.feed(html)
    parser.close()
    members: list[SenateFrontMember] = []
    seen = set()
    for row in parser.rows:
        role = _row_role(row)
        for href, _text in row.links:
            member = _profile_member(href, composition_url)
            if member is None:
                continue
            house, external_id, profile_url = member
            identity = (house, external_id)
            if identity in seen:
                continue
            members.append(
                SenateFrontMember(
                    house=house,
                    external_id=external_id,
                    profile_url=profile_url,
                    role=role,
                )
            )
            seen.add(identity)
    for href, _text in parser.links:
        member = _profile_member(href, composition_url)
        if member is None:
            continue
        house, external_id, profile_url = member
        identity = (house, external_id)
        if identity not in seen:
            members.append(SenateFrontMember(house, external_id, profile_url))
            seen.add(identity)
    return tuple(members)


def scrape_senado_fronts(
    client,
    *,
    catalog_url: str = SENADO_FRONT_CATALOG_URL,
    max_bytes: int = SENADO_FRONT_MAX_BYTES,
    max_pages: int = SENADO_FRONT_MAX_PAGES,
    max_fronts: int = SENADO_FRONT_MAX_FRONTS,
    max_redirects: int = SENADO_FRONT_MAX_REDIRECTS,
    catalog_html: str | None = None,
) -> SenadoFrontScrapeResult:
    pages_fetched = 0
    catalog_url = validate_senado_front_url(catalog_url)
    if catalog_html is None:
        catalog_html = client.fetch_front_html(
            catalog_url,
            max_bytes=max_bytes,
            max_redirects=max_redirects,
        )
        pages_fetched += 1
    if not isinstance(catalog_html, str):
        raise TypeError("Senado front catalog response must be text")
    entries = parse_senado_front_catalog(
        catalog_html,
        catalog_url=catalog_url,
        max_fronts=max_fronts,
    )
    fronts: list[SenadoFrontSnapshot] = []
    failed_fronts = 0
    for entry in entries:
        try:
            if pages_fetched + 2 > max_pages:
                raise SenadoFrontPageLimitError("Senado front page limit exceeded")
            council_html = client.fetch_front_html(
                entry.council_url,
                max_bytes=max_bytes,
                max_redirects=max_redirects,
            )
            pages_fetched += 1
            front = parse_senado_front_council(entry, council_html)
            composition_html = client.fetch_front_html(
                front.composition_url,
                max_bytes=max_bytes,
                max_redirects=max_redirects,
            )
            pages_fetched += 1
            fronts.append(
                replace(
                    front,
                    members=parse_senado_front_composition(
                        composition_html,
                        front.composition_url,
                    ),
                )
            )
        except Exception:
            failed_fronts += 1
    return SenadoFrontScrapeResult(tuple(fronts), failed_fronts, pages_fetched)
