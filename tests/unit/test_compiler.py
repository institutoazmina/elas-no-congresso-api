
from apps.subscriptions.compiler import (
    _leaf_to_tsquery,
    _make_token,
    _remove_accents,
    _sanitize_token,
    ast_to_tsquery,
)


class TestSanitizeToken:
    def test_basic(self):
        assert _sanitize_token("hello") == "hello"

    def test_accents_removed(self):
        assert _sanitize_token("ação") == "acao"

    def test_special_chars_replaced(self):
        assert _sanitize_token("teste@123") == "teste@123"

    def test_multiple_underscores_collapsed(self):
        assert _sanitize_token("a__b") == "a_b"

    def test_strips_leading_trailing_underscores(self):
        assert _sanitize_token("_test_") == "test"

    def test_lowercase(self):
        assert _sanitize_token("HELLO") == "hello"


class TestRemoveAccents:
    def test_returns_plain(self):
        assert _remove_accents("acao") == "acao"

    def test_removes_accents(self):
        assert _remove_accents("ação") == "acao"

    def test_ntilde(self):
        assert _remove_accents("São Paulo") == "Sao Paulo"


class TestMakeToken:
    def test_simple(self):
        assert _make_token("house", "CD") == "house_cd"

    def test_with_accents(self):
        assert _make_token("state", "SP") == "state_sp"


class TestLeafToTsquery:
    def test_eq_string(self):
        tok, reval = _leaf_to_tsquery({"field": "house", "op": "eq", "value": "CD"})
        assert tok == "house_cd"
        assert reval is False

    def test_eq_numeric(self):
        tok, reval = _leaf_to_tsquery({"field": "ano", "op": "eq", "value": "2024"})
        assert "ano_eq" in tok
        assert reval is True

    def test_ne_string(self):
        tok, reval = _leaf_to_tsquery({"field": "house", "op": "ne", "value": "CD"})
        assert tok == "!house_cd"
        assert reval is True

    def test_in_list(self):
        tok, reval = _leaf_to_tsquery(
            {"field": "house", "op": "in", "value": ["CD", "SF"]}
        )
        assert "(" in tok and "|" in tok
        assert reval is False

    def test_contains(self):
        tok, reval = _leaf_to_tsquery(
            {"field": "ementa", "op": "contains", "value": "mulher"}
        )
        assert "ementa_mulher" in tok
        assert reval is False


class TestCompileAst:
    def test_empty_ast(self):
        result = ast_to_tsquery({"op": "and", "children": []})
        assert result == ("", False)

    def test_single_eq(self):
        result = ast_to_tsquery({"op": "and", "children": [
            {"field": "house", "op": "eq", "value": "CD"}
        ]})
        assert "house_cd" in result[0]

    def test_and_two(self):
        result = ast_to_tsquery({"op": "and", "children": [
            {"field": "house", "op": "eq", "value": "CD"},
            {"field": "year", "op": "eq", "value": "2024"},
        ]})
        assert "&" in result[0]

    def test_or_two(self):
        result = ast_to_tsquery({"op": "or", "children": [
            {"field": "house", "op": "eq", "value": "CD"},
            {"field": "house", "op": "eq", "value": "SF"},
        ]})
        assert result[0] == "(house_cd) | (house_sf)"

    def test_not(self):
        result = ast_to_tsquery({"op": "not", "child": {"field": "house", "op": "eq", "value": "CD"}})
        assert result[0] == "!(house_cd)"

    def test_complex(self):
        result = ast_to_tsquery({
            "op": "and",
            "children": [
                {
                    "op": "or",
                    "children": [
                        {"field": "theme", "op": "eq", "value": "mulheres"},
                        {"field": "theme", "op": "eq", "value": "genero"},
                    ]
                },
                {"field": "year", "op": "gte", "value": "2020"},
            ]
        })
        assert "theme_mulheres" in result[0] and "theme_genero" in result[0]
        assert "&" in result[0]
