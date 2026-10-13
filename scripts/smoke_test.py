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

import csv
import sys
from pathlib import Path

SCREENS = ["Home", "Findings", "Build your watch list", "Method"]
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

        # Home carries the case table and one open case. Both are checked rather than
        # assumed: the table used to be a separate page, and the open case replaced an
        # accordion of twelve expanders.
        if screen == "Home":
            rendered = "\n".join(str(getattr(e, "value", "")) for e in at.markdown)
            rows = rendered.count('<details class="crow')
            print(f"          {rows} rows in the case table")
            if rows == 0:
                print("          FAIL the case table rendered no rows")
                clean = False
            # Rows expand in place, so nothing should be open until one is asked for.
            if "<details" not in rendered:
                print("          FAIL the case rows are not expandable")
                clean = False
            if 'class="crow" id="AIR-001" open' in rendered or " open>" in rendered:
                print("          FAIL a row is open on Home with none requested")
                clean = False

    # Opening a case is now a link, not a selectbox. Check that asking for one by
    # query parameter renders its record with the heading and the tabs.
    at = AppTest.from_file(str(app), default_timeout=TIMEOUT)
    at.query_params["case"] = "AIR-013"
    at.run()
    opened = "\n".join(str(getattr(e, "value", "")) for e in at.markdown)
    clean = report("Home, one case opened by link", at) and clean
    if 'id="AIR-013" open>' not in opened:
        print("  FAIL  the requested row did not open in place", file=sys.stderr)
        clean = False
    else:
        # Five tabs and five panes per row, with exactly one pane open in each. The whole
        # table is one markdown string, so these are counted across every row.
        n_rows = opened.count('<details class="crow')
        checks = {
            "tabs": (opened.count('class="tb'), n_rows * 5),
            "panes": (opened.count('class="pane'), n_rows * 5),
            "open panes": (opened.count('class="pane on"'), n_rows),
        }
        for name, (got, want) in checks.items():
            if got != want:
                print(
                    f"  FAIL  {name}: {got} across {n_rows} rows, expected {want}",
                    file=sys.stderr,
                )
                clean = False
        if all(got == want for got, want in checks.values()):
            print(f"          five tabs per row, one pane open, across {n_rows} rows")

    # The row tabs and the open and close controls are wired by one delegated listener.
    # It lived inside the home screen for a while, which left both dead on Findings with
    # the markup still rendering and nothing erroring. Every screen that draws rows has
    # to carry the listener.
    for screen_name in ("Home", "Findings"):
        at = AppTest.from_file(str(app), default_timeout=TIMEOUT)
        if screen_name != "Home":
            at.query_params["screen"] = screen_name
        at.run()
        html = "\n".join(str(getattr(e, "value", "")) for e in at.markdown)
        rows = html.count('<details class="crow')
        if rows and not html.count('class="tctl-b"'):
            print(
                f"  FAIL  {screen_name} draws {rows} rows with no open and close control",
                file=sys.stderr,
            )
            clean = False
        else:
            print(f"          {screen_name}: {rows} rows, controls present")

    # A ?case= link opens that row, and must not leave the parameter behind to pin the
    # same row open on every later screen. Findings read the parameter too, so a stale
    # one opened a case there as well.
    at = AppTest.from_file(str(app), default_timeout=TIMEOUT)
    at.query_params["case"] = "AIR-002"
    at.query_params["screen"] = "Findings"
    at.run()
    findings_html = "\n".join(str(getattr(e, "value", "")) for e in at.markdown)
    clean = report("Findings with a stale case parameter", at) and clean
    if 'id="AIR-002" open>' in findings_html:
        print(
            "  FAIL  a stale case parameter still opens a row on Findings",
            file=sys.stderr,
        )
        clean = False
    else:
        print("          a stale case parameter does not pin a row open elsewhere")

    # Each card says "N of 20" and its button has to land on exactly N rows. This was
    # wrong until 13 October 2026: the cards counted grade A and B rows while the
    # filtered table also showed grade C ones, so a card saying 17 opened a table of
    # 18. The counted-rows figure comes from the data, not from the page.
    with open(project_dir / "data" / "incidents.csv", newline="", encoding="utf-8") as fh:
        rows_data = list(csv.DictReader(fh))
    counted_rows = [r for r in rows_data if r["evidence_grade"] in ("A", "B")]
    card_tests = {
        "not-accuracy": lambda r: r["control_class"] != "Accuracy",
        "record-silent-on-stop": lambda r: r["deploy_stop_authority"] == "Not disclosed",
        "not-attacker": lambda r: r["directed_by"] != "Attacker",
    }
    for key, predicate in card_tests.items():
        want = sum(1 for r in counted_rows if predicate(r))
        at = AppTest.from_file(str(app), default_timeout=TIMEOUT)
        at.query_params["view"] = key
        at.run()
        shown = "\n".join(str(getattr(e, "value", "")) for e in at.markdown)
        got = shown.count('<details class="crow')
        clean = report(f"Home filtered by {key}", at) and clean
        if got != want:
            print(
                f"  FAIL  card {key} counts {want} but its filter shows {got} rows",
                file=sys.stderr,
            )
            clean = False
        else:
            print(f"          card {key}: {want} counted, {got} rows shown")

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

    # The watch list carried three typed counts that went stale as the register grew, and
    # the roles table described itself with one total while being computed from another.
    # Nothing on this screen should name a figure the data does not produce.
    watch_md = "\n".join(str(getattr(e, "value", "")) for e in at.markdown)
    watch_md += "\n".join(str(getattr(e, "value", "")) for e in at.caption)
    stale = [bad for bad in ("12 public cases", "out of 11", "11 cases") if bad in watch_md]
    if stale:
        print(f"  FAIL  the watch list names a stale figure: {stale}", file=sys.stderr)
        clean = False
    elif "**Start with these" not in watch_md:
        print("  FAIL  the watch list is not ordered into a head and a tail", file=sys.stderr)
        clean = False
    else:
        print("          no stale figures, and the list has a head and a tail")

    # The narrowest case: no risky authority, but a person approves. This branch was
    # unsatisfiable until 12 October 2026, because a yes on Q6 was counted as a risk
    # answer, so the message never rendered while every screen still passed. Rendering
    # is not enough on its own, so this asserts the message is actually there.
    at = AppTest.from_file(str(app), default_timeout=TIMEOUT)
    at.run()
    at.radio[0].set_value("Build your watch list").run()
    for index in range(5):
        at.radio[index].set_value("No")
    at.radio[5].set_value("Yes")
    at.run()
    boxes = " ".join(str(box.value) for box in at.success)
    narrow_ok = "cases still apply to it" in boxes
    clean = report("Build your watch list, the narrowest case", at) and clean
    if narrow_ok:
        print("          the narrowest case message rendered")
    else:
        print("  FAIL  the narrowest case message did not render", file=sys.stderr)
        clean = False

    # v1.0 reached the live site as a KeyError because st.cache_data keys on the
    # function, not on the files it opens, so a new column in the case data left the
    # key unchanged and new code ran against an old table. Nothing here would have
    # caught it: every local run starts with an empty cache. This asserts the stamp
    # the loaders are keyed on actually moves when the data moves.
    import importlib.util

    spec = importlib.util.spec_from_file_location("register_app", app)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    before = module.data_stamp(module.DATA_FILE, module.RATINGS_FILE)
    original = module.DATA_FILE.read_bytes()
    try:
        module.DATA_FILE.write_bytes(original + b"\n")
        after = module.data_stamp(module.DATA_FILE, module.RATINGS_FILE)
    finally:
        module.DATA_FILE.write_bytes(original)
    if before == after:
        print(
            "  FAIL  the cache stamp does not change when the case data changes",
            file=sys.stderr,
        )
        clean = False
    else:
        print("  ok    cache stamp moves when the case data moves")

    print("\nAll screens rendered." if clean else "\nAt least one screen raised.", file=sys.stderr if not clean else sys.stdout)
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
