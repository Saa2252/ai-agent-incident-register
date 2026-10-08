#!/usr/bin/env python3
"""Render every screen headlessly and fail on any Streamlit exception.

Usage:
    python3 scripts/smoke_test.py [project_dir]

Why this exists
---------------
For six commits the register screen raised on every card open, because a block inside
the incident card used an expander and the card is itself rendered inside one. Streamlit
forbids nesting them. CI was green throughout, because CI parsed app.py and never ran
it, and the validator checks the data rather than the page.

That is the same failure the register documents in other people's systems: a control
that is implemented, passing, and not watching the thing that broke. So the check now
runs the app.

Uses streamlit.testing.v1.AppTest, which is part of Streamlit, so there is no new
dependency to pin. It needs the app's own requirements installed, which is why it lives
here rather than in tests/, where everything is standard library on purpose.
"""

import sys
from pathlib import Path

SCREENS = ["Home", "The register", "Build your watch list", "Method"]
TIMEOUT = 120


def report(label, at):
    """Print any exception the run produced. Returns True when the screen is clean."""
    problems = list(at.exception)
    if not problems:
        print(f"  ok    {label}")
        return True
    print(f"  FAIL  {label}")
    for problem in problems:
        message = (problem.value or "").strip().splitlines()
        print(f"          {message[0] if message else problem}")
    return False


def main(argv):
    project_dir = Path(argv[1] if len(argv) > 1 else ".").resolve()
    app = project_dir / "app.py"
    if not app.exists():
        print(f"ERROR: {app} not found", file=sys.stderr)
        return 1

    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        print("streamlit is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return 1

    clean = True

    for screen in SCREENS:
        at = AppTest.from_file(str(app), default_timeout=TIMEOUT)
        at.run()
        if at.exception:
            clean = report(f"{screen} (initial load)", at) and clean
            continue
        # The sidebar radio chooses the screen.
        at.radio[0].set_value(screen).run()
        clean = report(screen, at) and clean

        # Opening an incident card is the path that was broken, so it is exercised
        # rather than assumed. Expanders render their contents on the same run.
        if screen == "The register":
            count = len(at.expander) if hasattr(at, "expander") else 0
            print(f"          {count} expandable records rendered")
            if count == 0:
                print("          FAIL no incident cards rendered at all")
                clean = False

    # The watch list only produces rules once questions are answered, so answer them.
    at = AppTest.from_file(str(app), default_timeout=TIMEOUT)
    at.run()
    at.radio[0].set_value("Build your watch list").run()
    answered = 0
    for widget in at.radio:
        if widget.label and widget.label.startswith("**Q"):
            widget.set_value("Yes")
            answered += 1
    at.run()
    clean = report(f"Build your watch list, {answered} questions answered as yes", at) and clean

    print("\nAll screens rendered." if clean else "\nAt least one screen raised.", file=sys.stderr if not clean else sys.stdout)
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
