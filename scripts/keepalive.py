#!/usr/bin/env python3
"""Keep the published app awake, and prove it is actually serving.

Usage:
    python3 scripts/keepalive.py [url]

The url defaults to the APP_URL environment variable, then to the published
address. Exit code 0 means the app rendered. Exit code 1 means it did not, which
is a real alert rather than a formality.

Why this needs a browser rather than a plain request
----------------------------------------------------
Streamlit Community Cloud sleeps an app after 12 hours with no traffic. Two facts
make the obvious workarounds useless:

  1. A plain HTTP request returns 200 from the static page shell without ever
     starting the Python process. Uptime monitors therefore report a sleeping app
     as healthy. The backend only starts when a browser runs the page JavaScript
     and opens a websocket to /_stcore/stream.
  2. Since April 2025 a push to the repository no longer wakes a sleeping app.
     Only a visitor does.

So this opens the page in headless Chromium, clicks the wake button if the app is
asleep, and then checks that real content rendered. That last check is the point.
A keepalive that reports success without looking at what came back is the same
mistake as a monitor that trusts a 200, and this repository has a row about
trusting a claim nobody reproduced.

Why it looks in every frame
---------------------------
Community Cloud serves a host page at the app's own address and embeds the running
app in a child frame at /~/+/. The app's text is in that frame, so the top-level
document's body is empty: inner_text("body") on it returns nothing at all, and a
text selector against the page matches nothing however long it waits.

This script looked only at the top-level document until 14 October 2026, which made
every run a false alarm regardless of what the app was doing. It now polls every
frame for either the app's content or the wake button, so it keeps working whichever
document Community Cloud decides to put them in.

Playwright is deliberately not in requirements.txt. It is a CI-only dependency and
the deployed app must not carry it.
"""

import os
import sys
import time

DEFAULT_URL = "https://ai-agent-incident-register.streamlit.app"

# Streamlit's own wording on the hibernation page. Kept as several candidates
# because the copy has changed before and a keepalive that breaks silently when a
# button is renamed is worse than none.
WAKE_BUTTON_TEXTS = [
    "Yes, get this app back up!",
    "Yes, get this app back up",
    "get this app back up",
]

# Proof the real app rendered, not the shell and not the hibernation page. The
# title alone is not enough, because the sleeping page carries it too.
#
# This was "Rows that feed the numbers" until 14 October 2026. That heading left
# Home on 9 October, when Home was cut to a landing page, and nothing connected the
# two: the keepalive waited sixty seconds for text that could no longer appear and
# failed every six hours. Five days of a workflow whose whole job is to prove the
# app rendered, reporting that it had not, with nobody reading it.
#
# It matters more than a red workflow. Community Cloud sleeps the app after twelve
# quiet hours and screenshots it once a day for the link preview, so a dead
# keepalive means the preview can be captured from the hibernation page.
#
# The line below is the hero tagline, which is the first thing Home paints and the
# thing a reader is meant to see. scripts/smoke_test.py now reads this value and
# fails if it is not on the rendered page, so the next rewrite of the hero cannot
# break the keepalive quietly.
EXPECTED_TITLE = "AI Agent Incident Register"
EXPECTED_BODY = "A public record of AI agents that caused harm"

PAGE_TIMEOUT_MS = 60_000
WAKE_TIMEOUT_MS = 180_000
POLL_MS = 1_000


def find_visible_text(page, candidates, timeout_ms):
    """Poll every frame for the first of `candidates` that is visible.

    Returns (frame, text) or (None, None). The frame list is re-read on each pass
    because the app's frame does not exist yet when the page first loads, and a
    frame that goes away mid-pass raises rather than returning False.
    """
    if isinstance(candidates, str):
        candidates = [candidates]
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        for frame in list(page.frames):
            for text in candidates:
                try:
                    found = frame.get_by_text(text, exact=False)
                    if found.count() > 0 and found.first.is_visible():
                        return frame, text
                except Exception:  # noqa: BLE001
                    continue
        if time.monotonic() >= deadline:
            return None, None
        page.wait_for_timeout(POLL_MS)


def main(argv):
    url = (argv[1] if len(argv) > 1 else os.environ.get("APP_URL") or DEFAULT_URL).rstrip("/")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed. Run:", file=sys.stderr)
        print("  pip install playwright && playwright install chromium", file=sys.stderr)
        return 1

    print(f"opening {url}")
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(PAGE_TIMEOUT_MS)

        try:
            page.goto(url, wait_until="domcontentloaded")
        except Exception as error:  # noqa: BLE001
            print(f"FAIL could not load the page: {error}", file=sys.stderr)
            browser.close()
            return 1

        # Either the app is already serving, or it is asleep and showing the wake
        # button. Both are waited for together, in every frame, because waiting for
        # one and then the other means a sleeping app spends the whole first timeout
        # waiting for content that cannot arrive until the button is clicked.
        print("waiting for the app's content or the wake button")
        frame, hit = find_visible_text(
            page, [EXPECTED_BODY] + WAKE_BUTTON_TEXTS, PAGE_TIMEOUT_MS
        )

        woke = False
        if hit in WAKE_BUTTON_TEXTS:
            print(f"app was asleep. clicking '{hit}'")
            try:
                frame.get_by_text(hit, exact=False).first.click()
            except Exception as error:  # noqa: BLE001
                print(f"FAIL could not click the wake button: {error}", file=sys.stderr)
                browser.close()
                return 1
            woke = True
            print("waiting for the app to come back up")
            frame, hit = find_visible_text(page, EXPECTED_BODY, WAKE_TIMEOUT_MS)

        title = page.title()
        body = frame.inner_text("body") if frame else ""
        where = frame.url if frame else ""
        browser.close()

    problems = []
    if EXPECTED_TITLE not in title:
        problems.append(f"title was '{title}', expected it to contain '{EXPECTED_TITLE}'")
    if EXPECTED_BODY not in body:
        problems.append(
            f"no frame rendered '{EXPECTED_BODY}'. The app is asleep, broken, or the "
            "hero has been rewritten and this script was not told"
        )

    if problems:
        for line in problems:
            print(f"FAIL {line}", file=sys.stderr)
        return 1

    state = "woken" if woke else "already awake"
    print(f"OK app is up and rendering, {state}, from {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
