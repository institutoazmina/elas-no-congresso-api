"""Paleta do admin derivada de elas-no-congresso/src/styles/tailwind.css.

Os tons intermediários atendem aos papéis claro/escuro do Unfold. O azul de
ação permanece no peso 600; o peso 500 é claro para links no modo escuro.
"""

ADMIN_COLORS = {
    "brand": {
        "ink": "#0b0f5e",
        "accent": "#4242f6",
        "lime": "#def279",
        "navy": "#1e2546",
    },
    "primary": {
        "50": "#f3f3ff",
        "100": "#e8e8ff",
        "200": "#d1d1fd",
        "300": "#b8b8fc",
        "400": "#aaaaff",
        "500": "#a0a0fb",
        "600": "#4242f6",
        "700": "#3535c5",
        "800": "#282894",
        "900": "#0b0f5e",
        "950": "#080b40",
    },
    "base": {
        "50": "#f6f6fa",
        "100": "#ededf4",
        "200": "#dcdde7",
        "300": "#bdc0d0",
        "400": "#9ba0b9",
        "500": "#62677f",
        "600": "#50566f",
        "700": "#3d4360",
        "800": "#2d3558",
        "900": "#1e2546",
        "950": "#10162e",
    },
    "font": {
        "subtle-light": "var(--color-base-600)",
        "subtle-dark": "var(--color-base-300)",
        "default-light": "var(--color-base-700)",
        "default-dark": "var(--color-base-200)",
        "important-light": "var(--color-brand-ink)",
        "important-dark": "var(--color-base-50)",
    },
}
