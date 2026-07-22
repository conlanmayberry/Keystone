from __future__ import annotations

from typing import Any

from megachud.browser.session import BrowserSession


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class FakeAccessibility:
    def __init__(self, snapshot: Any) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> Any:
        return self._snapshot


class FakePage:
    """Records what the browser tools drive it to do and returns canned
    page content — the browser analogue of tests/fixtures/fake_llm_client
    and httpx.MockTransport. No real Chromium involved."""

    def __init__(
        self,
        *,
        title: str = "Fake Title",
        url: str = "https://example.com/",
        body_text: str = "hello world",
        links: list[dict[str, str]] | None = None,
        a11y: Any = None,
        goto_status: int = 200,
    ) -> None:
        self._title = title
        self.url = url
        self._body_text = body_text
        self._links = links if links is not None else []
        self._a11y = a11y if a11y is not None else {"role": "WebArea", "name": title}
        self._goto_status = goto_status
        self.accessibility = FakeAccessibility(self._a11y)

        self.navigations: list[str] = []
        self.clicks: list[str] = []
        self.fills: list[tuple[str, str]] = []

    def set_default_navigation_timeout(self, ms: int) -> None:
        pass

    def set_default_timeout(self, ms: int) -> None:
        pass

    def goto(self, url: str) -> FakeResponse:
        self.navigations.append(url)
        self.url = url
        return FakeResponse(self._goto_status)

    def title(self) -> str:
        return self._title

    def inner_text(self, selector: str) -> str:
        return self._body_text

    def eval_on_selector_all(self, selector: str, js: str) -> list[dict[str, str]]:
        return self._links


def make_fake_factory(page: FakePage) -> tuple[Any, dict[str, int]]:
    """Returns a (page_factory, close_counter) pair. The factory always
    hands back a BrowserSession wrapping `page`; the counter's "count"
    increments each time that session is closed, so tests can assert
    cleanup happened."""
    counter = {"count": 0}

    def factory(*, headless: bool, viewport: tuple[int, int], nav_timeout_ms: int) -> BrowserSession:
        def closer() -> None:
            counter["count"] += 1

        return BrowserSession(page=page, closers=[closer])

    return factory, counter
