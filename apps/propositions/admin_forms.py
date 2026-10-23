from urllib.parse import parse_qs, urlsplit

from django import forms
from django.core.exceptions import ValidationError
from unfold.widgets import UnfoldAdminTextareaWidget


def parse_proposition_link(url):
    try:
        parsed = urlsplit(url)
        invalid_authority = parsed.username or parsed.password or parsed.port
    except ValueError as exc:
        raise ValueError("Use um link HTTPS oficial da Câmara ou do Senado.") from exc
    if parsed.scheme != "https" or invalid_authority:
        raise ValueError("Use um link HTTPS oficial da Câmara ou do Senado.")
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)
    identifier = None
    if host in {"www.camara.leg.br", "camara.leg.br"}:
        if path.lower() == "/proposicoesweb/fichadetramitacao":
            values = query.get("idProposicao", [])
            identifier = values[0] if len(values) == 1 else None
        elif path.startswith("/propostas-legislativas/"):
            identifier = path.removeprefix("/propostas-legislativas/")
        house = "camara"
    elif host in {"www25.senado.leg.br", "senado.leg.br"}:
        if path.startswith("/web/atividade/materias/-/materia/"):
            identifier = path.removeprefix("/web/atividade/materias/-/materia/")
        house = "senado"
    elif host == "legis.senado.leg.br":
        if path.startswith("/dadosabertos/materia/"):
            identifier = path.removeprefix("/dadosabertos/materia/")
        house = "senado"
    else:
        raise ValueError("Use um link HTTPS oficial da Câmara ou do Senado.")
    if (
        not identifier
        or not identifier.isascii()
        or not identifier.isdecimal()
        or len(identifier) > 19
        or not 0 < int(identifier) <= 9223372036854775807
    ):
        raise ValueError("O link precisa conter um identificador de proposição válido.")
    return house, int(identifier)


class PropositionLinksForm(forms.Form):
    links = forms.CharField(
        label="Links das proposições",
        help_text="Cole um link oficial por linha (Câmara ou Senado). Até 100 links por envio.",
        widget=UnfoldAdminTextareaWidget(
            attrs={
                "rows": 10,
                "placeholder": "https://www.camara.leg.br/...\nhttps://www25.senado.leg.br/...",
            }
        ),
    )

    def clean_links(self):
        links = [
            (number, line.strip())
            for number, line in enumerate(self.cleaned_data["links"].splitlines(), start=1)
            if line.strip()
        ]
        if len(links) > 100:
            raise ValidationError("Envie no máximo 100 links por vez.")
        parsed = []
        for number, link in links:
            try:
                parsed.append(parse_proposition_link(link))
            except ValueError as exc:
                raise ValidationError(f"Linha {number}: {exc}") from exc
        return list(dict.fromkeys(parsed))
