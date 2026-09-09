"""Pure normalization of official Câmara and Senado parliamentarian profiles."""

from collections.abc import Mapping


def _as_mapping(value: object) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _integer(value: object) -> int | None:
    value = _text(value)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _gender(value: object) -> str | None:
    value = _text(value)
    if value is None:
        return None
    normalized = value.casefold()
    if normalized in {"f", "feminino"}:
        return "F"
    if normalized in {"m", "masculino"}:
        return "M"
    return None


def _birthplace(city: object, state: object) -> str | None:
    city = _text(city)
    state = _text(state)
    if city and state:
        return f"{city}, {state}"
    return city or state


def normalize_camara_profile(profile: Mapping) -> dict[str, object]:
    """Map the Câmara ``/deputados/{id}`` payload to stable profile fields."""
    profile = _as_mapping(profile)
    profile = _as_mapping(profile.get("dados", profile))
    status = _as_mapping(profile.get("ultimoStatus"))
    return {
        "external_id": _integer(profile.get("id") or status.get("id")),
        "full_name": _text(profile.get("nomeCivil")),
        "social_name": _text(status.get("nome") or status.get("nomeEleitoral")),
        "gender": _gender(profile.get("sexo")),
        "photo_url": _text(status.get("urlFoto")),
        "birthplace": _birthplace(profile.get("municipioNascimento"), profile.get("ufNascimento")),
    }


def normalize_senado_profile(profile: Mapping) -> dict[str, object]:
    """Map the Senado ``/senador/{id}`` payload to stable profile fields."""
    profile = _as_mapping(profile)
    detail = _as_mapping(profile.get("DetalheParlamentar", profile))
    profile = _as_mapping(detail.get("Parlamentar", detail))
    identification = _as_mapping(profile.get("IdentificacaoParlamentar"))
    basics = _as_mapping(profile.get("DadosBasicosParlamentar"))
    return {
        "external_id": _integer(identification.get("CodigoParlamentar")),
        "full_name": _text(identification.get("NomeCompletoParlamentar")),
        "social_name": _text(identification.get("NomeParlamentar")),
        "gender": _gender(identification.get("SexoParlamentar")),
        "photo_url": _text(identification.get("UrlFotoParlamentar")),
        "birthplace": _birthplace(basics.get("Naturalidade"), basics.get("UfNaturalidade")),
    }
