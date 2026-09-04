"""Tests for scrapex.contrib.captcha — the human-in-the-loop helper.

We use a fake Page object (not a real browser) to keep tests fast
and deterministic. The contract under test is: screenshot is taken,
selector is polled, returns True when the challenge disappears.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from scrapex.contrib.captcha import solve_captcha_human_in_loop

# --- Fakes -----------------------------------------------------------------


class FakeLocator:
    """Stand-in for a Playwright Locator."""

    def __init__(self, count: int):
        self._count = count
        self.calls = 0

    async def count(self) -> int:
        self.calls += 1
        return self._count


class FakePage:
    """Stand-in for a Playwright Page.

    ``challenge_count`` is the count() value the locator will return.
    Decrement on each poll to simulate "challenge disappeared".
    """

    def __init__(self, challenge_count: int = 0):
        self._challenge_count = challenge_count
        self.screenshot_calls: list[str] = []
        self.locator_calls: list[str] = []

    async def screenshot(self, path: str) -> None:
        self.screenshot_calls.append(path)
        # Write a tiny file so the assertion "screenshot was saved" is real
        Path(path).write_bytes(b"FAKE-PNG")

    def locator(self, selector: str) -> FakeLocator:
        self.locator_calls.append(selector)
        return FakeLocator(self._challenge_count)


# --- Tests -----------------------------------------------------------------


async def test_captcha_returns_true_when_challenge_already_gone(tmp_path):
    """If the page has no challenge element, return True immediately."""
    page = FakePage(challenge_count=0)
    ok = await solve_captcha_human_in_loop(
        page,
        screenshot_path=str(tmp_path / "shot.png"),
        timeout_s=5.0,
        poll_interval_s=0.1,
    )
    assert ok is True
    assert page.screenshot_calls == [str(tmp_path / "shot.png")]


async def test_captcha_returns_true_after_challenge_disappears(tmp_path):
    """Challenge visible at first, then count drops to 0 → True."""
    call_count = [0]

    class DecreasingLocator:
        async def count(self):
            call_count[0] += 1
            return 0 if call_count[0] >= 2 else 1

    class DecreasingPage:
        def __init__(self):
            self.screenshot_calls: list[str] = []
            self.locator_calls: list[str] = []

        async def screenshot(self, path: str) -> None:
            self.screenshot_calls.append(path)
            Path(path).write_bytes(b"FAKE-PNG")

        def locator(self, selector: str) -> DecreasingLocator:
            self.locator_calls.append(selector)
            return DecreasingLocator()

    page = DecreasingPage()
    ok = await solve_captcha_human_in_loop(
        page,
        screenshot_path=str(tmp_path / "shot.png"),
        timeout_s=5.0,
        poll_interval_s=0.1,
    )
    assert ok is True
    assert call_count[0] >= 2  # at least one "still there" poll + one "gone" poll


async def test_captcha_returns_false_on_timeout(tmp_path):
    """If the challenge never disappears, return False after timeout."""
    page = FakePage(challenge_count=1)  # always 1, never disappears
    ok = await solve_captcha_human_in_loop(
        page,
        screenshot_path=str(tmp_path / "shot.png"),
        timeout_s=0.5,  # short
        poll_interval_s=0.1,
    )
    assert ok is False


async def test_captcha_creates_screenshot_dir_if_missing(tmp_path):
    """If the parent dir doesn't exist, it gets created."""
    deep = tmp_path / "deep" / "nested" / "dir"
    assert not deep.exists()
    page = FakePage(challenge_count=0)
    await solve_captcha_human_in_loop(
        page,
        screenshot_path=str(deep / "shot.png"),
        timeout_s=2.0,
    )
    assert deep.exists()
    assert (deep / "shot.png").exists()


async def test_captcha_tolerates_screenshot_failure(tmp_path):
    """If screenshot fails (e.g. browser closed), the helper still polls."""
    page = MagicMock()

    async def failing_screenshot(path):
        raise RuntimeError("browser closed")

    page.screenshot = failing_screenshot

    counter = [0]

    def fake_locator(selector):
        class L:
            async def count(inner_self):
                counter[0] += 1
                return 0 if counter[0] >= 1 else 1

        return L()

    page.locator = fake_locator
    ok = await solve_captcha_human_in_loop(
        page,
        screenshot_path=str(tmp_path / "shot.png"),
        timeout_s=2.0,
        poll_interval_s=0.1,
    )
    assert ok is True  # it still proceeded past the screenshot failure


async def test_captcha_polls_with_configured_interval():
    """Verify the poll interval is respected (within reason)."""
    page = FakePage(challenge_count=5)  # never disappears
    import time
    t0 = time.monotonic()
    ok = await solve_captcha_human_in_loop(
        page, screenshot_path="/tmp/nope.png", timeout_s=0.5, poll_interval_s=0.1
    )
    elapsed = time.monotonic() - t0
    assert ok is False
    # Should have polled at least a few times; 0.5s / 0.1s = ~5 polls
    assert elapsed >= 0.4, f"polling returned too fast: {elapsed:.2f}s"


async def test_captcha_uses_default_selectors():
    """The poll should target known CAPTCHA family selectors."""
    page = FakePage(challenge_count=0)
    await solve_captcha_human_in_loop(page, screenshot_path="/tmp/nope.png", timeout_s=1.0)
    assert page.locator_calls, "locator() was never called"
    selector = page.locator_calls[0]
    # Should match the family of CAPTCHAs we know about
    for token in ("turnstile", "recaptcha", "hcaptcha"):
        assert token in selector, f"selector {selector!r} missing token {token!r}"
