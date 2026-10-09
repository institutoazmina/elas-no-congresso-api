
from ninja import ModelSchema, Schema
from pydantic import EmailStr, field_validator

from .models import Frequency, Subscription


class AlertSchema(Schema):
    """Um alerta = uma frequência + a árvore de filtros que o modal montou."""

    frequency: str
    ast: dict

    @field_validator("frequency")
    @classmethod
    def _known_frequency(cls, value: str) -> str:
        if value not in Frequency.values:
            raise ValueError(f"frequência inválida: {value!r}")
        return value

    @field_validator("ast")
    @classmethod
    def _compilable_ast(cls, value: dict) -> dict:
        """O AST vem de fora, então compila aqui: erro vira 422 em vez de 500
        estourando lá no meio do register."""
        from .compiler import ast_to_tsquery, validate_ast

        try:
            validate_ast(value)
            ast_to_tsquery(value)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ValueError(f"filtro inválido: {exc}") from exc
        return value


class SubscriptionCreateSchema(Schema):
    email: EmailStr
    accepted_terms: bool
    alerts: list[AlertSchema]

    @field_validator("alerts")
    @classmethod
    def _at_least_one(cls, value: list[AlertSchema]) -> list[AlertSchema]:
        if not value:
            raise ValueError("escolha ao menos uma frequência")
        return value

    @field_validator("accepted_terms")
    @classmethod
    def _must_accept(cls, value: bool) -> bool:
        if not value:
            raise ValueError("é preciso aceitar os termos de uso")
        return value


class SubscriptionSchema(ModelSchema):
    class Meta:
        model = Subscription
        fields = ["id", "email", "frequency", "is_active", "created_at", "confirmed_at"]
