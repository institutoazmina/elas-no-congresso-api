"""The only Substack write allowed here is creation of an unpublished draft."""

from urllib.parse import urlsplit

from django.conf import settings


class AuthenticationRequiredError(Exception):
    pass


class DraftOnlyClient:
    def __init__(self, publication_url, api=None):
        if api is not None:
            self.api = api
            return
        if not settings.SUBSTACK_COOKIES_STRING:
            raise AuthenticationRequiredError("Configure ou renove SUBSTACK_COOKIES_STRING.")
        parsed = urlsplit(publication_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.query
            or parsed.fragment
            or parsed.path.strip("/")
        ):
            raise ValueError("SUBSTACK_PUBLICATION_URL deve ser a origem HTTPS da publicação.")
        from substack import Api

        class NewsletterApi(Api):
            def get_user_publications(self):
                # Api performs profile discovery during initialization, before
                # the caller can set headers. Keep this compatibility hook local.
                self._session.headers.update(
                    {"User-Agent": "Mozilla/5.0 (compatible; ElasNoCongresso/1.0)"}
                )
                return super().get_user_publications()

        try:
            self.api = NewsletterApi(
                cookies_string=settings.SUBSTACK_COOKIES_STRING,
                publication_url=publication_url,
                timeout=30,
            )
        except Exception as exc:
            if getattr(exc, "status_code", None) in {
                401,
                403,
            } or "Requested publication is unavailable" in str(exc):
                raise AuthenticationRequiredError(
                    "Sessão inválida ou publicação indisponível."
                ) from exc
            raise
        self._restrict_requests()

    def _restrict_requests(self):
        session = self.api._session
        request = session.request
        draft_endpoint = f"{self.api.publication_url}/drafts"

        def draft_only_request(method, url, **kwargs):
            if method.upper() != "GET" and not (method.upper() == "POST" and url == draft_endpoint):
                raise ValueError("Operação Substack bloqueada pelo adaptador de rascunhos.")
            return request(method, url, **kwargs)

        session.request = draft_only_request

    def _call(self, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            if getattr(exc, "status_code", None) in {401, 403}:
                raise AuthenticationRequiredError("Renovar sessão Substack.") from exc
            raise

    def close(self):
        session = getattr(self.api, "_session", None)
        if session:
            session.close()

    def find(self, title):
        offset = 0
        matches = []
        while True:
            drafts = self._call(self.api.get_drafts, offset=offset, limit=100)
            if not isinstance(drafts, list):
                raise ValueError("Formato inesperado da lista de rascunhos.")
            matches.extend(d for d in drafts if (d.get("draft_title") or d.get("title")) == title)
            if len(drafts) < 100:
                break
            offset += 100
        if len(matches) > 1:
            raise ValueError(
                "Mais de um rascunho corresponde a esta semana; reconciliar manualmente."
            )
        return matches[0].get("id") if matches else None

    def create(self, title, markdown):
        result = self._call(
            self.api.create_draft_from_markdown,
            title=title,
            markdown=markdown,
            publish=False,
            prepublish=False,
            send=False,
            share_automatically=False,
        )
        return int(result["draft"]["id"])

    def verify(self, draft_id):
        draft = self._call(self.api.get_draft, draft_id)
        # SDK versions expose different field names; only explicit draft evidence
        # is accepted, and a scheduled release is never treated as a safe draft.
        if not isinstance(draft, dict) or int(draft.get("id", 0)) != int(draft_id):
            raise ValueError("Rascunho retornado não corresponde ao ID esperado.")
        if (
            draft.get("published")
            or draft.get("post_date")
            or draft.get("scheduled_at")
            or draft.get("draft_datetime")
            or draft.get("scheduled_release")
        ):
            raise ValueError("Publicação ou agendamento detectado; intervenção humana necessária.")
        if "draft_body" not in draft:
            raise ValueError("Não foi possível verificar o corpo do rascunho.")
        return draft
