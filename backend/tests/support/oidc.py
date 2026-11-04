"""`FakeOIDC` (ТЗ Фазы 4 §8.1): the answer of Google replaced by a scripted identity."""

from __future__ import annotations

from quack.auth.google import GoogleIdentity


class FakeOIDC:
    """`GoogleOIDC` that redirects to a fake URL and maps codes to scripted identities."""

    def __init__(self) -> None:
        self.identities: dict[str, GoogleIdentity] = {}

    def script(self, code: str, *, email: str, email_verified: bool = True) -> None:
        self.identities[code] = GoogleIdentity(email=email, email_verified=email_verified)

    def authorize_url(self, *, state: str) -> str:
        return f"https://accounts.google.test/authorize?state={state}"

    async def identity(self, *, code: str) -> GoogleIdentity:
        return self.identities[code]
