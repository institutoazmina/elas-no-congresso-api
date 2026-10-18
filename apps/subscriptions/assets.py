"""Public, cacheable assets embedded in subscription emails."""

from pathlib import Path

from django.http import FileResponse, Http404, HttpRequest
from django.views.decorators.http import require_GET

EMAIL_ASSETS_DIR = Path(__file__).resolve().parent / "emails" / "assets"
EMAIL_ASSETS = {
    filename: EMAIL_ASSETS_DIR / filename for filename in ("daily-header.png", "header.png")
}


@require_GET
def email_asset(request: HttpRequest, name: str) -> FileResponse:
    """Serve an email header from a stable URL email clients can access."""
    # Look up a server-built path so the request value never reaches the filesystem.
    asset_path = EMAIL_ASSETS.get(name)
    if asset_path is None or not asset_path.is_file():
        raise Http404("Asset não encontrado.")

    response = FileResponse(asset_path.open("rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
