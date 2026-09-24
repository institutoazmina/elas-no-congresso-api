"""Inferência local e reproduzível da QuitérIA 2.0.

O formato de entrada e a ordem dos rótulos vêm do repositório de treinamento
``ia-feminista-elas-no-congresso``. Os artefatos publicados no Hub preservam
apenas ``LABEL_n``, por isso esta tradução é parte explícita do contrato.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from .models import Proposition

THEME_INDEX_TO_CATEGORY = {
    0: "direitos_sexuais_reprodutivos",
    1: "educacao_cultura",
    2: "familia_parentalidade",
    3: "igualdade_antidiscriminacao",
    4: "infancia_adolescencia",
    5: "lgbtqiapn",
    6: "participacao_politica",
    7: "saude",
    8: "trabalho_economia_cuidado",
    9: "violencias_de_genero",
}
FAVORABILITY_UNFAVORABLE_INDEX = 1
MAX_LENGTH = 512


@dataclass(frozen=True)
class QuiteriaPrediction:
    input_text: str
    theme_category: str
    theme_confidence: float
    theme_scores: dict[str, float]
    favorability_probability: float
    favorability_scores: dict[str, float]
    favorability_label: int

    @property
    def input_hash(self) -> str:
        return hashlib.sha256(self.input_text.encode()).hexdigest()


def format_markdown(text: str | None) -> str:
    """Limpeza usada no pré-processamento que treinou a QuitérIA."""
    if not text:
        return ""

    lines: list[str] = []
    for line in text.split("\n"):
        if "<!--" in line:
            continue
        line = (
            line.replace("  ", " ")
            .replace("\t", " ")
            .replace("..", "")
            .replace("\\_", "")
            .replace("##", "")
            .strip(" ")
        )
        if line and line not in lines:
            lines.append(line)
    return " ".join(lines)


def build_input(proposition: Proposition) -> str:
    """Monta ``textFormat`` exatamente como no conjunto de treinamento."""
    author = (
        proposition.authors.select_related("party", "parliamentarian")
        .order_by("order_index", "pk")
        .first()
    )
    party = author.party.acronym if author and author.party else ""
    gender = author.parliamentarian.gender if author and author.parliamentarian else ""
    state = author.state_at_authorship if author and author.state_at_authorship else ""
    content = format_markdown(proposition.full_text) or proposition.ementa
    return f"Partido: {party}; Genero: {gender}; UF: {state}; Conteúdo: {content}"


class QuiteriaClassifier:
    """Mantém os dois BERTs carregados no processo exclusivo da fila ML."""

    def __init__(self, model_dir: str):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        root = Path(model_dir)
        if not root.is_dir():
            raise FileNotFoundError(
                f"Artefatos da QuitérIA não encontrados em {root}. "
                "A imagem precisa ser reconstruída com os pesos do modelo."
            )

        self._torch = torch
        self._theme_tokenizer = AutoTokenizer.from_pretrained(
            root, subfolder="tema", local_files_only=True
        )
        self._theme_model = AutoModelForSequenceClassification.from_pretrained(
            root, subfolder="tema", local_files_only=True
        ).eval()
        self._favorability_tokenizer = AutoTokenizer.from_pretrained(
            root, subfolder="favorabilidade", local_files_only=True
        )
        self._favorability_model = AutoModelForSequenceClassification.from_pretrained(
            root, subfolder="favorabilidade", local_files_only=True
        ).eval()

    def _scores(self, tokenizer, model, text: str) -> list[float]:
        inputs = tokenizer(text, truncation=True, max_length=MAX_LENGTH, return_tensors="pt")
        with self._torch.inference_mode():
            logits = model(**inputs).logits[0]
            return self._torch.softmax(logits, dim=-1).tolist()

    def classify(self, input_text: str) -> QuiteriaPrediction:
        theme_probabilities = self._scores(self._theme_tokenizer, self._theme_model, input_text)
        theme_index = max(range(len(theme_probabilities)), key=theme_probabilities.__getitem__)
        try:
            theme_category = THEME_INDEX_TO_CATEGORY[theme_index]
        except KeyError as error:  # protege contra publicação incompatível no Hub
            raise ValueError(f"Índice de tema QuitérIA desconhecido: {theme_index}") from error

        favorability_probabilities = self._scores(
            self._favorability_tokenizer, self._favorability_model, input_text
        )
        if len(favorability_probabilities) != 2:
            raise ValueError("O submodelo de favorabilidade precisa retornar duas classes")
        unfavorable_probability = favorability_probabilities[FAVORABILITY_UNFAVORABLE_INDEX]

        return QuiteriaPrediction(
            input_text=input_text,
            theme_category=theme_category,
            theme_confidence=theme_probabilities[theme_index],
            theme_scores={
                f"LABEL_{index}": score for index, score in enumerate(theme_probabilities)
            },
            favorability_probability=unfavorable_probability,
            favorability_scores={
                f"LABEL_{index}": score for index, score in enumerate(favorability_probabilities)
            },
            favorability_label=int(
                unfavorable_probability >= settings.QUITERIA_FAVORABILITY_THRESHOLD
            ),
        )


@lru_cache(maxsize=1)
def get_classifier() -> QuiteriaClassifier:
    return QuiteriaClassifier(settings.QUITERIA_MODEL_DIR)


def classify_proposition(proposition: Proposition) -> QuiteriaPrediction:
    return get_classifier().classify(build_input(proposition))
