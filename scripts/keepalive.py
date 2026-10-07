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

Playwright is deliberately not in requirements.txt. It is a CI-only dependency and
the deployed app must not carry it.
"""

import os
import sys

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
EXPECTED_TITLE = "AI Agent Incident Register"
EXPECTED_BODY = "Rows that feed the numbers"

PAGE_TIMEOUT_MS = 60_000
WAKE_TIMEOUT_MS = 180_000


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

        # If the app is asleep, wake it. The button may take a moment to appear,
        # so this looks rather than assumes.
        woke = False
        for text in WAKE_BUTTON_TEXTS:
            button = page.get_by_text(text, exact=False)
            try:
                if button.count() > 0 and button.first.is_visible():
                    print(f"app was asleep. clicking '{text}'")
                    button.first.click()
                    woke = True
                    break
            except Exception:  # noqa: BLE001
                continue

        if woke:
            print("waiting for the app to come back up")
            try:
                page.wait_for_selector(
                    f"text={EXPECTED_BODY}", timeout=WAKE_TIMEOUT_MS
                )
            except Exception as error:  # noqa: BLE001
                print(f"FAIL app did not come back up in time: {error}", file=sys.stderr)
                browser.close()
                return 1
        else:
            try:
                page.wait_for_selector(f"text={EXPECTED_BODY}", timeout=PAGE_TIMEOUT_MS)
            except Exception as error:  # noqa: BLE001
                print(f"FAIL app was awake but did not render: {error}", file=sys.stderr)
                browser.close()
                return 1

        title = page.title()
        body = page.inner_text("body")
        browser.close()

    problems = []
    if EXPECTED_TITLE not in title:
        problems.append(f"title was '{title}', expected it to contain '{EXPECTED_TITLE}'")
    if EXPECTED_BODY not in body:
        problems.append(f"page did not contain '{EXPECTED_BODY}'")

    if problems:
        for line in problems:
            print(f"FAIL {line}", file=sys.stderr)
        return 1

    state = "woken" if woke else "already awake"
    print(f"OK app is up and rendering, {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
