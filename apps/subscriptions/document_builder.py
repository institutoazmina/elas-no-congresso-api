"""Build flat document from Django ORM for tsquery matching (adapted from POC4)."""

from __future__ import annotations

import re
from typing import Any

from django.db import connection


def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"[\s]+", "-", s)
    return s


def build_document(proposition_id: int) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": proposition_id,
        # Mesmo valor de `id`, mas com nome de campo: é assim que o modal pede
        # para acompanhar uma proposição específica.
        "proposicao": proposition_id,
        "tipo": None,
        "casa": None,
        "situacao": None,
        "ano": None,
        "partido": [],
        "autor": [],
        "genero": [],
        "raca": [],
        "religiao": [],
        "estado": [],
        "relator": [],
        "tema": [],
        # "Categorias 2026": a taxonomia editorial fechada das anotações. É o
        # que o modal oferece — `tema` guarda as palavras-chave do raspador.
        "categoria": [],
        "comissao": [],
        "frente": [],
        "bancada": [],
        "norma": [],
        "quiteriometro": 0,
        "celeridade": None,
    }

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT p.type_code, p.house, p.current_status, p.year
            FROM propositions p WHERE p.id = %s
            """,
            [proposition_id],
        )
        row = cur.fetchone()
        if not row:
            return {}
        doc["tipo"] = row[0]
        doc["casa"] = row[1]
        doc["situacao"] = _slugify(row[2] or "")
        doc["ano"] = row[3]

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT pa.parliamentarian_id, pt.party_id, par.gender, par.race, par.religion, pt.state
            FROM proposition_authors pa
            JOIN parliamentarians par ON par.id = pa.parliamentarian_id
            JOIN parliamentarian_terms pt ON pt.parliamentarian_id = par.id AND pt.end_date IS NULL
            WHERE pa.proposition_id = %s
            ORDER BY pa.order_index
            """,
            [proposition_id],
        )
        for row in cur.fetchall():
            parl_id, party_id, gender, race, religion, state = row
            if parl_id:
                doc["autor"].append(parl_id)
            if party_id:
                with connection.cursor() as cur2:
                    cur2.execute("SELECT acronym FROM parties WHERE id = %s", [party_id])
                    party_row = cur2.fetchone()
                    if party_row:
                        doc["partido"].append(party_row[0])
            if gender:
                doc["genero"].append(gender.lower())
            if race:
                doc["raca"].append(_slugify(race))
            if religion:
                doc["religiao"].append(_slugify(religion))
            if state:
                doc["estado"].append(state.lower())

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT t.slug
            FROM proposition_themes pt
            JOIN themes t ON t.id = pt.theme_id
            WHERE pt.proposition_id = %s
            ORDER BY pt.rank
            """,
            [proposition_id],
        )
        for row in cur.fetchall():
            doc["tema"].append(row[0])

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT category
            FROM proposition_annotations
            WHERE proposition_id = %s AND category IS NOT NULL
            """,
            [proposition_id],
        )
        for row in cur.fetchall():
            doc["categoria"].append(row[0])

    # A avaliação humana é a fonte editorial autoritativa. Enquanto ela ainda
    # não chegou, a categoria prevista pela QuitérIA permite alertas imediatos.
    if not doc["categoria"]:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT theme_category
                FROM proposition_analysis
                WHERE proposition_id = %s
                  AND analysis_status = 'succeeded'
                  AND theme_category IS NOT NULL
                """,
                [proposition_id],
            )
            analysis_category = cur.fetchone()
            if analysis_category:
                doc["categoria"].append(analysis_category[0])

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT c.acronym
            FROM proposition_committees pc
            JOIN committees c ON c.id = pc.committee_id
            WHERE pc.proposition_id = %s
            """,
            [proposition_id],
        )
        for row in cur.fetchall():
            doc["comissao"].append(row[0])

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT parliamentarian_id
            FROM proposition_rapporteurs
            WHERE proposition_id = %s AND ended_at IS NULL
            """,
            [proposition_id],
        )
        for row in cur.fetchall():
            if row[0]:
                doc["relator"].append(row[0])

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT pan.quiterometer_score
            FROM proposition_analysis pan
            WHERE pan.proposition_id = %s
            """,
            [proposition_id],
        )
        analysis_row = cur.fetchone()
        if analysis_row and analysis_row[0] is not None:
            doc["quiteriometro"] = int(round(float(analysis_row[0]) * 10))

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT c.name
            FROM proposition_authors pa
            JOIN caucus_memberships cm ON cm.parliamentarian_id = pa.parliamentarian_id
                AND cm.end_date IS NULL
                AND cm.is_observed_current IS TRUE
            JOIN caucuses c ON c.id = cm.caucus_id
            WHERE pa.proposition_id = %s AND c.kind = 'frente'
            """,
            [proposition_id],
        )
        for row in cur.fetchall():
            doc["frente"].append(_slugify(row[0]))

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT c.name
            FROM proposition_authors pa
            JOIN caucus_memberships cm ON cm.parliamentarian_id = pa.parliamentarian_id
                AND cm.end_date IS NULL
                AND cm.is_observed_current IS TRUE
            JOIN caucuses c ON c.id = cm.caucus_id
            WHERE pa.proposition_id = %s AND c.kind = 'bancada'
            """,
            [proposition_id],
        )
        for row in cur.fetchall():
            doc["bancada"].append(_slugify(row[0]))

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT ln.type, ln.number, ln.year
            FROM proposition_amends pa2
            JOIN legal_norms ln ON ln.id = pa2.norm_id
            WHERE pa2.proposition_id = %s
            """,
            [proposition_id],
        )
        for row in cur.fetchall():
            norm_type, norm_number, norm_year = row
            if norm_number and norm_year:
                doc["norma"].append(f"lei_{norm_number}_{norm_year}")
            elif norm_type:
                doc["norma"].append(_slugify(norm_type))

    return doc
