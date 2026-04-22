"""
Management command: seed_dev

Loads the base fixture (seed.json) then seeds the dev database with data from:
  - parlamentares.csv  → Parliamentarian, ParliamentarianTerm
  - congresso.csv      → Proposition (Câmara), PropositionAnalysis, PropositionTheme
  - senado.csv         → Proposition (Senado), PropositionAnalysis, PropositionTheme

Faker fills in fields absent from the source data (birth_date, bio).
Safe to run multiple times (idempotent via get_or_create).
"""

import csv
import re
from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand
from faker import Faker

from apps.core.enums import Gender, House
from apps.legislatures.models import (
    InstitutionalAuthor,
    Legislature,
    Parliamentarian,
    ParliamentarianTerm,
    Party,
)
from apps.propositions.models import Proposition, PropositionAnalysis, PropositionAuthor
from apps.taxonomy.models import PropositionTheme, Theme

fake = Faker("pt_BR")

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[4] / "data"

# Parties present in CSVs but absent from seed.json
_EXTRA_PARTIES = {
    "MDB": ("Movimento Democrático Brasileiro", "Centro"),
    "PSD": ("Partido Social Democrático", "Centro"),
    "PDT": ("Partido Democrático Trabalhista", "Centro-Esquerda"),
    "NOVO": ("Partido Novo", "Direita"),
    "PODEMOS": ("Podemos", "Centro"),
    "PODE": ("Podemos", "Centro"),
    "CIDADANIA": ("Cidadania", "Centro"),
    "SOLIDARIEDADE": ("Solidariedade", "Centro"),
    "AVANTE": ("Avante", "Centro"),
    "PROS": ("Partido Republicano da Ordem Social", "Centro"),
    "PRB": ("Partido Republicano Brasileiro", "Centro-Direita"),
    "PRD": ("Partido Renovação Democrática", "Direita"),
    "PSC": ("Partido Social Cristão", "Direita"),
    "PSL": ("Partido Social Liberal", "Direita"),
    "PTB": ("Partido Trabalhista Brasileiro", "Centro"),
    "PV": ("Partido Verde", "Centro-Esquerda"),
    "PR": ("Partido da República", "Centro-Direita"),
    "REDE": ("Rede Sustentabilidade", "Centro-Esquerda"),
    "DEM": ("Democratas", "Direita"),
    "PATRIOTA": ("Patriota", "Direita"),
}

# Themes present in CSV data but absent from seed.json
_EXTRA_THEMES = [
    ("violencia-contra-a-mulher", "Violência Contra a Mulher"),
    ("lei-maria-da-penha", "Lei Maria da Penha"),
    ("feminicidio", "Feminicídio"),
    ("dignidade-sexual", "Dignidade Sexual"),
    ("direitos-sexuais-reprodutivos", "Direitos Sexuais e Reprodutivos"),
    ("direitos-sociais", "Direitos Sociais"),
    ("maternidade", "Maternidade"),
    ("politica", "Política"),
    ("raca", "Raça"),
    ("clima", "Clima"),
]

# CSV tema raw value → Theme slug in DB
_TEMA_MAP = {
    "genero": "igualdade-de-genero",
    "economia": "economia",
    "direitos sociais": "direitos-sociais",
    "maternidade": "maternidade",
    "dignidade sexual": "dignidade-sexual",
    "violencia contra a mulher": "violencia-contra-a-mulher",
    "Lei Maria da Penha": "lei-maria-da-penha",
    "feminicidio": "feminicidio",
    "raça": "raca",
    "politica": "politica",
    "direitos sexuais e reprodutivos": "direitos-sexuais-reprodutivos",
    "clima": "clima",
}

_INSTITUTIONAL_HOUSES = {
    "Câmara dos Deputados",
    "Senado Federal",
    "Congresso Nacional",
}

_ORIGINATING_HOUSE_MAP = {
    "CD": House.CAMARA,
    "SF": House.SENADO,
}


def _safe_int(val: str | None) -> int | None:
    try:
        v = (val or "").strip()
        return int(float(v)) if v else None
    except (ValueError, TypeError):
        return None


def _safe_decimal(val: str | None) -> float | None:
    try:
        v = (val or "").strip()
        f = float(v)
        return f if f else None
    except (ValueError, TypeError):
        return None


def _parse_number_label(label: str) -> tuple[str, int, int]:
    """'PL 4101/2024' → ('PL', 4101, 2024). Returns (label, 0, 0) on no match."""
    m = re.match(r"^([A-Z]+)\s+(\d+)/(\d{4})$", label.strip())
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3))
    return label.strip(), 0, 0


def _parse_leg_numbers(raw: str) -> list[int]:
    """'56.57' or '55,56,57,58' → [56, 57] etc."""
    nums = []
    for part in raw.replace(".", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nums.append(int(float(part)))
        except ValueError:
            pass
    return nums


class Command(BaseCommand):
    help = "Seed the development database from CSV source data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--data-dir",
            default=None,
            help="Directory containing the CSV files (default: sibling POC directory)",
        )
        parser.add_argument(
            "--skip-fixture",
            action="store_true",
            help="Skip loading seed.json (useful when already loaded)",
        )

    def handle(self, *args, **options):
        data_dir = Path(options["data_dir"]) if options["data_dir"] else _DEFAULT_DATA_DIR

        if not options["skip_fixture"]:
            self.stdout.write("Loading base fixture…")
            fixture_path = Path(__file__).resolve().parents[4] / "fixtures" / "seed.json"
            call_command("loaddata", str(fixture_path), verbosity=0)

        self.stdout.write("Seeding themes…")
        theme_cache = self._seed_themes()

        self.stdout.write("Seeding parties…")
        party_cache = self._seed_parties()

        self.stdout.write("Seeding parliamentarians…")
        parl_cache = self._seed_parliamentarians(data_dir / "parlamentares.csv", party_cache)

        self.stdout.write("Seeding Câmara propositions…")
        count_camara = self._seed_camara(data_dir / "congresso.csv", parl_cache, theme_cache)

        self.stdout.write("Seeding Senado propositions…")
        count_senado = self._seed_senado(data_dir / "senado.csv", parl_cache, theme_cache)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done — {len(parl_cache)} parliamentarians, "
                f"{count_camara} Câmara propositions, "
                f"{count_senado} Senado propositions."
            )
        )

    # ── themes ────────────────────────────────────────────────────────────────

    def _seed_themes(self) -> dict[str, Theme]:
        for slug, name in _EXTRA_THEMES:
            Theme.objects.get_or_create(slug=slug, defaults={"name": name})
        return {t.slug: t for t in Theme.objects.all()}

    # ── parties ───────────────────────────────────────────────────────────────

    def _seed_parties(self) -> dict[str, Party]:
        for acronym, (name, ideology) in _EXTRA_PARTIES.items():
            # PODE is an alias for PODEMOS — store under PODEMOS only
            canonical = "PODEMOS" if acronym == "PODE" else acronym
            Party.objects.get_or_create(
                acronym=canonical, defaults={"name": name, "ideology": ideology}
            )
        return {p.acronym: p for p in Party.objects.all()}

    # ── parliamentarians ──────────────────────────────────────────────────────

    def _seed_parliamentarians(
        self, csv_path: Path, party_cache: dict[str, Party]
    ) -> dict[str, Parliamentarian]:
        parl_by_name: dict[str, Parliamentarian] = {}
        legislatures = {leg.number: leg for leg in Legislature.objects.all()}
        # Case-insensitive lookup so mixed-case acronyms (PCdoB) resolve correctly
        party_cache_ci = {k.upper(): v for k, v in party_cache.items()}

        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                nome = row["nome"].strip()
                external_id = int(row["numero"])
                gender = Gender.F if row["genero"].strip() == "F" else Gender.M
                photo = row["foto"].strip() or None
                state = row["estado"].strip()
                cargo = row["cargo"].strip()

                raw_acronym = row["partido"].strip().upper()
                if raw_acronym in ("UNIAO", "UNIÃO"):
                    raw_acronym = "UNIÃO"
                elif raw_acronym == "PODE":
                    raw_acronym = "PODEMOS"
                party = party_cache_ci.get(raw_acronym)
                if party is None:
                    # Unknown party — create a minimal entry and add to caches
                    original = row["partido"].strip()
                    party, _ = Party.objects.get_or_create(
                        acronym=original, defaults={"name": original}
                    )
                    party_cache[original] = party
                    party_cache_ci[original.upper()] = party

                house = House.SENADO if "senador" in cargo.lower() else House.CAMARA

                parl, _ = Parliamentarian.objects.get_or_create(
                    full_name=nome,
                    defaults={
                        "photo_url": photo,
                        "gender": gender,
                        "birth_date": fake.date_of_birth(minimum_age=35, maximum_age=80),
                        "bio": fake.paragraph(nb_sentences=3),
                    },
                )
                parl_by_name[nome.lower()] = parl

                for leg_num in _parse_leg_numbers(row["legislatura"]):
                    leg = legislatures.get(leg_num)
                    if leg is None:
                        continue
                    ParliamentarianTerm.objects.get_or_create(
                        house=house,
                        external_id=external_id,
                        legislature_number=leg,
                        defaults={
                            "parliamentarian": parl,
                            "party": party,
                            "role": cargo,
                            "state": state,
                            "start_date": leg.start_date,
                            "end_date": leg.end_date,
                        },
                    )

        return parl_by_name

    # ── shared helpers ────────────────────────────────────────────────────────

    def _get_or_create_institutional(self, name: str) -> InstitutionalAuthor:
        kind = "casa" if name in _INSTITUTIONAL_HOUSES else "parlamentar"
        author, _ = InstitutionalAuthor.objects.get_or_create(name=name, defaults={"kind": kind})
        return author

    def _resolve_author(
        self, name: str, parl_cache: dict[str, Parliamentarian]
    ) -> tuple[Parliamentarian | None, InstitutionalAuthor | None]:
        parl = parl_cache.get(name.strip().lower())
        if parl:
            return parl, None
        return None, self._get_or_create_institutional(name.strip())

    def _attach_themes(
        self,
        proposition: Proposition,
        tema_1: str,
        tema_2: str,
        theme_cache: dict[str, Theme],
    ) -> None:
        seen: set[str] = set()
        for rank, raw in enumerate([tema_1, tema_2], start=1):
            raw = (raw or "").strip()
            if not raw:
                continue
            slug = _TEMA_MAP.get(raw)
            if not slug or slug in seen:
                continue
            theme = theme_cache.get(slug)
            if theme:
                PropositionTheme.objects.get_or_create(
                    proposition=proposition,
                    theme=theme,
                    defaults={"rank": rank},
                )
                seen.add(slug)

    def _attach_author(
        self,
        proposition: Proposition,
        parl: Parliamentarian | None,
        inst: InstitutionalAuthor | None,
    ) -> None:
        if parl is None and inst is None:
            return
        if PropositionAuthor.objects.filter(proposition=proposition).exists():
            return
        PropositionAuthor.objects.create(
            proposition=proposition,
            parliamentarian=parl,
            institutional_author=inst,
            order_index=1,
        )

    # ── Câmara ────────────────────────────────────────────────────────────────

    def _seed_camara(self, csv_path: Path, parl_cache: dict, theme_cache: dict) -> int:
        count = 0
        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                external_id = _safe_int(row.get("id"))
                if external_id is None:
                    continue

                number_label = row["nomeDoProjeto"].strip()
                type_code, number, year = _parse_number_label(number_label)

                try:
                    presented_at = date.fromisoformat(row.get("dataApresentacao", "").strip())
                except ValueError:
                    presented_at = date(year, 1, 1) if year else date.today()

                prop, created = Proposition.objects.get_or_create(
                    house=House.CAMARA,
                    external_id=external_id,
                    defaults={
                        "type_code": type_code,
                        "number_label": number_label,
                        "number": number,
                        "year": year,
                        "presented_at": presented_at,
                        "ementa": row.get("ementa", "").strip(),
                        "keywords": row.get("keywords", "").strip() or None,
                        "full_text_url": row.get("urlInteiroTeor", "").strip() or None,
                        "tramitation_url": row.get("urlTramitacao", "").strip() or None,
                        "current_status": row.get("descricaoSituacao", "").strip() or None,
                        "current_status_code": _safe_int(row.get("codSituacao")),
                        "regime": row.get("regime", "").strip() or None,
                        "scope": row.get("ambito", "").strip() or None,
                        "appreciation_mode": row.get("apreciacao", "").strip() or None,
                        "originating_house": House.CAMARA,
                    },
                )

                autor = row.get("autor", "").strip()
                if autor:
                    parl, inst = self._resolve_author(autor, parl_cache)
                    self._attach_author(prop, parl, inst)

                PropositionAnalysis.objects.get_or_create(
                    proposition=prop,
                    defaults={
                        "classification": _safe_int(row.get("classification")),
                        "classification_probability": _safe_decimal(row.get("probabilities")),
                        "llm_position": _safe_int(row.get("posicao_llm")),
                        "final_position_score": _safe_decimal(
                            row.get("classification_posicao_final")
                        ),
                    },
                )

                self._attach_themes(prop, row.get("tema_1", ""), row.get("tema_2", ""), theme_cache)

                if created:
                    count += 1

        return count

    # ── Senado ────────────────────────────────────────────────────────────────

    def _seed_senado(self, csv_path: Path, parl_cache: dict, theme_cache: dict) -> int:
        count = 0
        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                external_id = _safe_int(row.get("id"))
                if external_id is None:
                    continue

                number_label = row["NomedoProjeto"].strip()
                type_code_parsed, number_parsed, year_parsed = _parse_number_label(number_label)
                type_code = row.get("SiglaSubtipoMateria", "").strip() or type_code_parsed
                number = _safe_int(row.get("NumeroMateria")) or number_parsed
                year = _safe_int(row.get("AnoMateria")) or year_parsed

                try:
                    presented_at = date.fromisoformat(row.get("DataApresentacao", "").strip())
                except ValueError:
                    presented_at = date(year, 1, 1) if year else date.today()

                orig_raw = row.get("CasaIniciadoraNoLegislativo", "").strip()
                originating_house = _ORIGINATING_HOUSE_MAP.get(orig_raw)

                prop, created = Proposition.objects.get_or_create(
                    house=House.SENADO,
                    external_id=external_id,
                    defaults={
                        "type_code": type_code,
                        "number_label": number_label,
                        "number": number,
                        "year": year,
                        "presented_at": presented_at,
                        "ementa": row.get("Ementa", "").strip(),
                        "tramitation_url": row.get("UrlTramitacao", "").strip() or None,
                        "current_status": row.get("MovimentacaoDescricaoSituacao", "").strip()
                        or None,
                        "originating_house": originating_house,
                    },
                )

                autor_raw = row.get("Autor", "").strip()
                if autor_raw:
                    # Strip "(PARTY/STATE)" suffix and title prefix
                    autor_clean = re.sub(r"\s*\([^)]+\)\s*$", "", autor_raw)
                    autor_clean = re.sub(r"^(Senadora?|Deputad[ao])\s+", "", autor_clean).strip()
                    lookup_name = autor_clean if autor_clean else autor_raw
                    parl, inst = self._resolve_author(lookup_name, parl_cache)
                    self._attach_author(prop, parl, inst)

                PropositionAnalysis.objects.get_or_create(
                    proposition=prop,
                    defaults={
                        "classification": _safe_int(row.get("classification")),
                        "classification_probability": _safe_decimal(row.get("probabilities")),
                    },
                )

                self._attach_themes(prop, row.get("tema_1", ""), row.get("tema_2", ""), theme_cache)

                if created:
                    count += 1

        return count
