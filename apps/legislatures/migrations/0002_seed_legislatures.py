"""Carrega as 57 legislaturas brasileiras (1826–2027) + 58ª a 60ª projetadas.

Fonte: Senado Federal, "Tabela de Legislaturas"
https://www25.senado.leg.br/documents/130884256/132289867/TABELA+DE+LEGISLATURAS.pdf

A numeração é a "atual" da tabela — a renumeração retroativa a partir de 1826
feita pelo Decreto Legislativo nº 79/1979, não a numeração "à época".

Os intervalos NÃO são contíguos: dissoluções da Câmara, o Governo Provisório
(1930-1933) e o Estado Novo (1937-1946) deixam lacunas em que nenhuma
legislatura estava em vigor. Uma data pode não cair em legislatura nenhuma.
"""

from django.db import migrations

# (número, início, fim)
LEGISLATURAS = [
    (1, "1826-05-06", "1829-09-03"),
    (2, "1830-05-03", "1833-10-06"),
    (3, "1834-05-03", "1837-10-15"),
    (4, "1838-05-03", "1841-11-21"),
    (5, "1843-01-01", "1844-05-24"),
    (6, "1845-01-01", "1847-09-18"),
    (7, "1848-05-03", "1849-02-19"),
    (8, "1850-01-01", "1852-09-04"),
    (9, "1853-05-03", "1856-09-20"),
    (10, "1857-05-03", "1860-09-12"),
    (11, "1861-05-03", "1863-05-12"),
    (12, "1864-01-01", "1866-09-16"),
    (13, "1867-05-22", "1868-07-18"),
    (14, "1869-05-11", "1872-05-22"),
    (15, "1872-12-12", "1875-10-10"),
    (16, "1877-02-01", "1878-04-11"),
    (17, "1878-12-15", "1881-06-30"),
    (18, "1882-01-17", "1884-09-03"),
    (19, "1885-05-20", "1885-09-26"),
    (20, "1886-05-03", "1889-06-15"),
    (21, "1890-11-15", "1891-02-24"),  # Congresso Constituinte
    (22, "1891-06-15", "1893-09-25"),
    (23, "1894-05-07", "1896-12-10"),
    (24, "1897-05-05", "1899-11-22"),
    (25, "1900-05-03", "1902-12-30"),
    (26, "1903-05-03", "1905-12-30"),
    (27, "1906-05-03", "1908-12-31"),
    (28, "1909-05-03", "1911-12-31"),
    (29, "1912-05-03", "1915-02-10"),
    (30, "1915-05-03", "1917-12-31"),
    (31, "1918-05-03", "1920-12-31"),
    (32, "1921-05-03", "1923-12-31"),
    (33, "1924-05-03", "1926-12-31"),
    (34, "1927-05-03", "1929-12-31"),
    (35, "1930-05-03", "1930-11-11"),  # dissolvida pelo Governo Provisório
    (36, "1933-11-15", "1934-07-20"),  # Assembleia Nacional Constituinte
    (37, "1934-07-21", "1937-11-10"),  # dissolvida pelo Estado Novo
    (38, "1946-09-23", "1951-01-30"),  # Assembleia Constituinte de 1946
    (39, "1951-03-15", "1955-01-31"),
    (40, "1955-02-07", "1959-01-31"),
    (41, "1959-03-15", "1963-01-31"),
    (42, "1963-03-15", "1967-01-22"),
    (43, "1967-03-01", "1970-11-30"),
    (44, "1971-03-31", "1974-12-05"),
    (45, "1975-03-01", "1978-12-05"),
    (46, "1979-02-01", "1983-01-31"),
    (47, "1983-02-01", "1987-01-31"),
    (48, "1987-02-01", "1991-01-31"),
    (49, "1991-02-01", "1995-01-31"),
    (50, "1995-02-01", "1999-01-31"),
    (51, "1999-02-01", "2003-01-31"),
    (52, "2003-02-01", "2007-01-31"),
    (53, "2007-02-01", "2011-01-31"),
    (54, "2011-02-01", "2015-01-31"),
    (55, "2015-02-01", "2019-01-31"),
    (56, "2019-02-01", "2023-01-31"),
    (57, "2023-02-01", "2027-01-31"),
    # Projetadas pelo art. 44 da CF/88 (4 anos, 1º de fevereiro a 31 de janeiro).
    (58, "2027-02-01", "2031-01-31"),
    (59, "2031-02-01", "2035-01-31"),
    (60, "2035-02-01", "2039-01-31"),
]


def seed(apps, schema_editor):
    model = apps.get_model("legislatures", "Legislature")
    # update_or_create porque 56 e 57 já podem existir (fixtures/seed.json, prod).
    for number, start, end in LEGISLATURAS:
        model.objects.update_or_create(
            number=number, defaults={"start_date": start, "end_date": end}
        )


def unseed(apps, schema_editor):
    model = apps.get_model("legislatures", "Legislature")
    # RESTRICT em parliamentarian_terms: só apaga as que ninguém referencia.
    model.objects.filter(
        number__in=[n for n, _, _ in LEGISLATURAS], terms__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("legislatures", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
