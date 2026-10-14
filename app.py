"""AI Agent Incident Register.

Real AI agent failures, each traced to the safeguard that was missing, the test that
would have caught it before launch, and the signal that would have shown it after.

Three rules run through this file.

1. Every number on screen is computed from the case data. Nothing is typed into the
   page, so no count can drift away from the rows behind it.
2. Only grade A and grade B rows feed a number. Grade C rows appear in the register,
   labelled, and are excluded from every count.
3. No model runs anywhere in this app. Every figure is arithmetic over the case data.
"""

import csv
import datetime
import html
import importlib
import re
from collections import Counter
import sys
from pathlib import Path

import pandas as pd
from urllib.parse import quote_plus

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="AI Agent Incident Register",
    page_icon="🛑",
    layout="wide",
    initial_sidebar_state="auto",  # collapses itself on a phone, where an open sidebar covers the page
)

# Wide tables scroll inside their own box rather than pushing the page sideways.
#
# The register index carries ten facet columns and is rendered as Markdown rather than
# with st.table or st.dataframe. st.dataframe draws to a canvas and leaves its contents
# out of the accessibility tree entirely. st.table is a real table but does not render
# Markdown on the pinned Streamlit version, so links in cells come out as literal
# bracket syntax. Markdown gives a real table, with headers, that a screen reader can
# read and that can hold a link. The only thing it lacks is this, and this is four lines.
# Colour means severity of harm. Nothing else on the page is a data colour.
#
# A page with a colour per class, per grade and per status reads as marketing to a
# governance audience, and colour carrying three meanings carries none. Grade is
# monochrome, and every severity pill pairs its colour with a five-bar meter and the word,
# so nothing depends on colour alone. The bar chart this comment used to mention was
# removed in the layout pass of 11 October 2026.
# MIT AI Risk Initiative, AI Incident Tracker harm severity framework, CSET-based as
# modified by MIT. Captured 10 October 2026 and transcribed into
# frameworks/mit_severity_framework.csv. A case's headline level is the highest level it
# reached on any harm type.
# The words a reader sees for each control state. One map, used by the cards and by the
# Findings table, because the two described the same state differently: a card showed the
# raw value and the table said "Built but the attacker could switch it off".
MATURITY_LABEL = {
    "Absent": "Never built",
    "Designed": "On paper only",
    "Implemented": "Built but did not hold",
    "Bypassable": "Built but could be switched off",
    "Unknown": "Record does not say",
}

MATURITY_MEANING = {
    "Absent": "The control did not exist in any form.",
    "Designed": "It existed on paper, in a policy or an instruction, with nothing enforcing it.",
    "Implemented": "It was built and wired in, and it did not stop the thing it was there to stop.",
    "Bypassable": "It was built and wired in, and whatever it was there to stop could switch it off.",
    "Unknown": "The public record does not say what state it was in.",
}

DIRECTED_MEANING = {
    "Deployer": "It was doing what the people running it had configured or told it to do.",
    "Attacker": "An outside party pointed it at this, whether by stealing access, hiding "
                "instructions in content it read, or simply asking.",
    "No one": "Nobody steered it. It did this in ordinary use.",
}

MIT_LEVELS = {
    1: "Negligible", 2: "Minor", 3: "Substantial", 4: "Severe", 5: "Catastrophic",
}
MIT_SLUG = {1: "neg", 2: "min", 3: "sub", 4: "sev", 5: "cat"}
MIT_ORDER = [5, 4, 3, 2, 1]

# What each band means, so a heading is not a bare word. The MIT wording summarises the
# level's descriptors across the ten harm types rather than quoting one of them.
MIT_SEVERITY_MEANING = {
    5: "Societal or global breakdown. Nothing in this register comes near this level.",
    4: "Harm at the scale of a region or a nation, or to hundreds of thousands of people.",
    3: "Serious harm, affecting up to a million people or a critical service.",
    2: "Real harm to a bounded group, up to about a thousand people.",
    1: "Contained harm, or harm the record cannot show went further.",
}

EU_GROUP_MEANING = {
    "Meets": (
        "The published record shows harm of the kind Article 3(49) describes, such as "
        "serious harm to health, to critical infrastructure, to fundamental rights or to "
        "property."
    ),
    "Does not meet": (
        "The record is clear enough to say the harm falls outside that definition."
    ),
    "Not determinable from the record": (
        "The published account does not settle it either way. This is the honest default "
        "rather than a judgement that the case was minor, and it is where most cases sit "
        "because deployers rarely publish enough to decide it."
    ),
}

MIT_ATTRIBUTION = (
    "Framework: MIT AI Risk Initiative, AI Incident Tracker (CC BY 4.0), based on CSET's "
    "Taxonomy of AI Harm, as modified by MIT. Captured 10 October 2026. Scores are this "
    "register's, not MIT's."
)

PAGE_CSS = """
<style>
:root {
  --sev-cat:#8f1d1d; --sev-sev:#d03b3b; --sev-sub:#ec835a; --sev-min:#fab219; --sev-neg:#898781;
  --tint-cat:rgba(143,29,29,0.16); --tint-sev:rgba(208,59,59,0.14);
  --tint-sub:rgba(236,131,90,0.18); --tint-min:rgba(250,178,25,0.18);
  --tint-neg:rgba(137,135,129,0.14);
  --meter-off:#c3c2b7; --track:#e1e0d9; --grid-line:#e1e0d9; --ink-2:#52514e; --muted:#898781;
}
@media (prefers-color-scheme: dark) {
  :root {
    --sev-cat:#f08a8a;
    --tint-cat:rgba(240,138,138,0.22); --tint-sev:rgba(208,59,59,0.26);
    --tint-sub:rgba(236,131,90,0.22); --tint-min:rgba(250,178,25,0.20);
    --tint-neg:rgba(137,135,129,0.22);
    --meter-off:#66655f; --track:#2c2c2a; --grid-line:#2c2c2a; --ink-2:#c3c2b7;
  }
}

/* Wide tables scroll in their own box rather than pushing the page sideways. */
/* Tables wrap rather than scroll. min-width: max-content with nowrap cells made every
   long table as wide as its longest sentence: the change log ran 6,571px past the page
   at 1280, and a reader had to scroll sideways through a paragraph to read it. */
div[data-testid="stMarkdownContainer"] > table,
div[data-testid="stTable"] table {
  width: 100%; table-layout: auto; border-collapse: collapse;
}
div[data-testid="stMarkdownContainer"] > table th,
div[data-testid="stMarkdownContainer"] > table td,
div[data-testid="stTable"] th, div[data-testid="stTable"] td {
  /* break-word, not anywhere. "anywhere" lets the browser count a break between
     every pair of characters when it works out a column's minimum width, which
     collapsed the change log's Version and Date columns to one character a line
     once the table was made to fit. break-word still breaks a token that cannot
     fit on a line of its own, which is all a long URL needs. */
  white-space: normal; overflow-wrap: break-word; vertical-align: top;
}
div[data-testid="stMarkdownContainer"] > table th,
div[data-testid="stTable"] th { color: #52514e; }

/* The change log on a phone. Three columns of which one holds a paragraph cannot be a
   table at 375px: the two narrow columns get a line each per word. Below 640px every
   entry becomes a block, with its version and date as one caption line above the text. */
@media (max-width: 640px) {
  .st-key-changelog table, .st-key-changelog tbody, .st-key-changelog tr,
  .st-key-changelog td { display:block; width:100%; }
  .st-key-changelog thead { display:none; }
  .st-key-changelog tr {
    border:1px solid var(--grid-line); border-radius:10px;
    padding:10px 12px; margin:0 0 10px;
  }
  .st-key-changelog td { border:0 !important; padding:0 !important; }
  .st-key-changelog td:nth-child(1), .st-key-changelog td:nth-child(2) {
    display:inline; font-size:12px; font-weight:700; color:#52514e;
    text-transform:uppercase; letter-spacing:.04em;
  }
  .st-key-changelog td:nth-child(1)::after { content:" · "; font-weight:400; }
  .st-key-changelog td:nth-child(2)::after { content:""; display:block; height:6px; }
  .st-key-changelog td:nth-child(3) { font-size:14px; line-height:1.55; }
}


/* The case table. A real table with real headers, built as HTML because a severity
   meter cannot be expressed in a dataframe cell. */
.case-table-wrap { overflow-x: auto; border: 1px solid var(--grid-line); border-radius: 12px; }
table.cases { border-collapse: collapse; width: 100%; font-size: 14px; }
table.cases th, table.cases td {
  text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--grid-line);
  vertical-align: middle;
}
table.cases th {
  font-size: 12px; color: #52514e; font-weight: 600;
  text-transform: uppercase; letter-spacing: .04em; white-space: nowrap;
}
table.cases tr:last-child td { border-bottom: 0; }
table.cases td.id { white-space: nowrap; font-variant-numeric: tabular-nums; }
table.cases tr.notcounted td { color: var(--muted); }

.sev {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 3px 10px 3px 8px; border-radius: 999px; font-size: 13px; white-space: nowrap;
}
.meter { display: inline-flex; gap: 2px; align-items: flex-end; height: 12px; }
.meter i { width: 3px; border-radius: 1px; background: var(--meter-off); display: block; }
.meter i:nth-child(1){height:4px} .meter i:nth-child(2){height:6px}
.meter i:nth-child(3){height:8px} .meter i:nth-child(4){height:10px}
.meter i:nth-child(5){height:12px}
.s-neg{background:var(--tint-neg)} .s-neg .meter i.f{background:var(--sev-neg)}
.s-min{background:var(--tint-min)} .s-min .meter i.f{background:var(--sev-min)}
.s-sub{background:var(--tint-sub)} .s-sub .meter i.f{background:var(--sev-sub)}
.s-sev{background:var(--tint-sev)} .s-sev .meter i.f{background:var(--sev-sev)}
.s-cat{background:var(--tint-cat)} .s-cat .meter i.f{background:var(--sev-cat)}

.grade {
  display:inline-block; min-width:26px; text-align:center; padding:1px 7px;
  border-radius:6px; font-size:12px; font-weight:650;
}
.g-a { background: currentColor; }
.g-a span { color: Canvas; }
.g-b { border: 1.5px solid currentColor; }
.g-c { border: 1.5px dashed var(--muted); color: var(--muted); }

.hero-band {
  background:#0d2440; color:#fff; border-radius:14px; padding:44px 48px; margin:4px 0 48px;
}
@media (prefers-color-scheme: dark) { .hero-band { background:#13263d; } }
@media (max-width: 640px) { .hero-band { padding:28px 20px; } }
.hero-band h1 { font-size:40px; line-height:1.1; margin:0 0 12px; font-weight:700; color:#fff; }
.hero-band p.tagline {
  font-size:22px; line-height:1.35; margin:0 0 28px; font-weight:500; color:#fff;
  background:none;
}
.hero-band p.fact { color:#c9d8ec; margin:0 0 10px; font-size:15px; font-weight:600; }
/* Two facts and a separator between them. The dot is drawn by the stylesheet rather
   than written into the markup, so the rule below can take it away with the layout
   instead of leaving it stranded on a line of its own. */
.hero-band p.fact span + span::before { content:"·"; padding:0 16px; }
.hero-band p.def {
  color:#c9d8ec; margin:0; font-size:14px; font-weight:400; max-width:720px; line-height:1.5;
}
/* The hero fact line. One line with a middle dot down to 480px, two lines below it,
   because the dot ends up alone on a line of its own otherwise. */
@media (max-width: 480px) {
  .hero-band p.fact span { display:block; }
  .hero-band p.fact span + span::before { content:none; }
}

/* One grid rather than three Streamlit columns, so the cards are the same height and
   each button sits inside its own card at the bottom with the three lined up. */
.cards { display:grid; grid-template-columns:repeat(3, 1fr); gap:16px; margin:24px 0 8px; }
@media (max-width: 900px) { .cards { grid-template-columns:1fr; } }
.fcard {
  background:var(--surface,#fcfcfb); border:1px solid var(--ring,rgba(11,11,11,.10));
  border-radius:14px; padding:18px; display:flex; flex-direction:column; height:100%;
}
.fcard .big { font-size:38px; font-weight:700; line-height:1; margin:0 0 12px; }
.fcard .big small { font-size:16px; color:var(--muted); font-weight:500; margin-left:4px; }
.dots { display:flex; gap:5px; margin:0 0 16px; flex-wrap:wrap; }
.dots i { width:14px; height:14px; border-radius:50%; background:#d6d4cc; display:block; }
.dots i.on { background:#2a78d6; }
@media (prefers-color-scheme: dark) { .dots i { background:#3a3a37; } .dots i.on { background:#3987e5; } }
.fcard .say { font-size:16px; font-weight:600; margin:0 0 8px; line-height:1.35; }
.fcard .more { color:#52514e; font-size:14px; margin:0; line-height:1.5; }
.fcard .note { color:var(--muted); font-size:13px; margin:10px 0 0; line-height:1.45; }
.fcard .cardbtn {
  margin-top:auto; padding-top:16px; display:block; text-align:center;
}
.fcard .cardbtn a {
  display:block; padding:9px 12px; border-radius:8px; font-size:14px; font-weight:600;
  border:1px solid var(--ring,rgba(11,11,11,.18)); color:inherit; text-decoration:none;
}
.fcard .cardbtn a:hover { background:rgba(127,127,127,.12); }

/* Two framework panels side by side, stacked on a phone. The tiles are links, so a
   filtered view is shareable and clicking the live tile clears it. */
.panels { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin:8px 0 18px; }
@media (max-width: 900px) { .panels { grid-template-columns:1fr; } }
.panel {
  border:1px solid var(--grid-line); border-radius:12px; padding:16px 18px;
}
.panel h4 { margin:0 0 12px; font-size:15px; font-weight:700; }
.panel p { margin:10px 0 0; font-size:13px; color:var(--ink-2); line-height:1.5; }
.panel a { color:inherit; }
.tiles { display:flex; flex-direction:column; gap:6px; }
.tile {
  display:flex; align-items:center; justify-content:space-between; gap:12px;
  padding:7px 10px; border:1px solid var(--grid-line); border-radius:9px;
  text-decoration:none; color:inherit; font-size:14px;
}
.tile, .panel a.tile, .tile:hover, .tile:visited { text-decoration:none !important; }
.tile:hover { background:rgba(42,120,214,.07); }
.tile.on { border-color:#2a78d6; background:rgba(42,120,214,.12); font-weight:600; }
.tile .tcount { font-variant-numeric:tabular-nums; font-weight:700; }

/* The case index. One <details> per case, summary laid out as a grid that lines up
   with the header, so it reads as a table and still expands in place. */
.ctbl { border:1px solid var(--grid-line); border-radius:12px; overflow:hidden; }
/* The fixed columns used to add up to 814px with the gaps, which left "What happened"
   71px inside a tab panel and wrapped it one word to a line. The six labelled columns
   are now sized to what they actually hold, so the column carrying the sentence is the
   one that grows. */
.ctbl-head, .crow > summary {
  display:grid; grid-template-columns:76px 86px 140px minmax(0, 1fr) 104px 152px 66px;
  gap:8px; align-items:center; padding:10px 14px;
}
.crow .cdate { font-variant-numeric:tabular-nums; white-space:nowrap; }

/* The internal register view. Three public columns and nine an organisation fills from
   its own logs and tickets, drawn empty because no public source can fill them. Date,
   missing control and evidence are dropped here so the nine fit at 1280 without
   sideways scrolling, and they are all still on the card. */
/* Twelve columns do not fit the page width at a readable size, so the table scrolls
   inside its own container instead of squeezing every label to one word a line. */
.ctbl.itbl { overflow-x:auto; }
.itbl .ctbl-head, .itbl .crow > summary, .ihead-groups {
  grid-template-columns:86px 118px 150px 230px repeat(9, minmax(110px, 1fr));
  gap:8px; padding:8px 12px; width:max-content; min-width:100%;
}
.ihead-groups {
  display:grid; align-items:end; font-size:11px; font-weight:700; color:#52514e;
  text-transform:uppercase; letter-spacing:.04em; padding-bottom:4px;
}
.ihead-groups .gpub { grid-column:span 4; }
.ihead-groups .gint { border-bottom:2px dashed var(--grid-line); padding-bottom:3px; }
.itbl .ctbl-head span { font-size:11px; line-height:1.2; white-space:nowrap; }
.itbl .crow > summary > span:nth-child(n+5) { white-space:normal; }
.itbl .crow > summary { font-size:13px; }
.icell {
  display:block; text-align:center; border-radius:5px; padding:4px 2px;
  font-size:11px; line-height:1.25; overflow-wrap:break-word;
}
.icell.empty {
  border:1.5px dashed var(--grid-line); background:rgba(127,127,127,.05); color:#8b8880;
}
.icell.known { border:1.5px solid #2a78d6; background:rgba(42,120,214,.10); color:#1d5fae; }
.icell.part {
  border:1.5px solid rgba(42,120,214,.45); background:rgba(42,120,214,.05); color:#1d5fae;
}
p.ilegend { display:flex; flex-wrap:wrap; align-items:center; gap:7px; font-size:12px;
  color:#52514e; margin:6px 0 10px; }
p.ilegend .key { display:inline-block; width:22px; height:13px; border-radius:4px; }
p.ilegend .key.solid { border:1.5px solid #2a78d6; background:rgba(42,120,214,.10); }
p.ilegend .key.dotted {
  border:1.5px dashed var(--grid-line); background:rgba(127,127,127,.05); margin-left:14px;
}
.st-key-regpick { margin:2px 0 8px; }
.st-key-regpick [role="radiogroup"] { gap:22px; }
@media (max-width: 900px) {
  .itbl .ctbl-head, .ihead-groups { display:none; }
  .itbl .crow > summary { grid-template-columns:1fr; gap:4px; width:auto; }
  .icell { text-align:left; }
}
.ctbl-head {
  font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.04em;
  color:#52514e; background:rgba(127,127,127,.14);
}
.crow { border-top:1px solid var(--grid-line); }
.crow > summary { cursor:pointer; list-style:none; font-size:14px; }
.crow > summary::-webkit-details-marker { display:none; }
.crow > summary:hover { background:rgba(42,120,214,.06); }
.crow[open] > summary { background:rgba(42,120,214,.08); }
.crow.notcounted > summary { color:var(--muted); }
.crow .cid { font-weight:700; font-variant-numeric:tabular-nums; white-space:nowrap; }
.crow .caret {
  display:inline-block; width:0; height:0; margin-right:7px; vertical-align:middle;
  border-left:6px solid currentColor; border-top:4px solid transparent;
  border-bottom:4px solid transparent; transition:transform .12s;
}
.crow[open] .caret { transform:rotate(90deg); }
.casebody {
  padding:14px 18px 18px 46px; background:rgba(127,127,127,.09);
  border-top:1px solid var(--grid-line); font-size:14px; line-height:1.55;
}
/* The framework choice is the control this page turns on, so it reads as a choice
   rather than a stray pair of radio buttons. Scoped by container key, because the screen
   selector in the sidebar is the same widget and must not grow with it. */
.st-key-lenspick-bad, .st-key-lenspick-kind {
  border:1px solid var(--grid-line); border-radius:12px; padding:14px 16px; margin:4px 0 10px;
}
.st-key-lenspick-bad label p, .st-key-lenspick-kind label p {
  font-size:17px !important; font-weight:700 !important;
}
.st-key-lenspick-bad [role="radiogroup"] { gap:26px; }
/* Five options rather than two, so they wrap instead of running off the measure. */
.st-key-lenspick-kind [role="radiogroup"] { gap:18px; flex-wrap:wrap; }
.st-key-lenspick-kind [role="radiogroup"] > label { max-width:260px; }
/* Top-align, so a two-line option does not push its radio to the middle of the text. */
.st-key-lenspick-bad [role="radiogroup"] > label,
.st-key-lenspick-kind [role="radiogroup"] > label { align-items:flex-start; }
.st-key-lenspick-bad [role="radiogroup"] > label > div:first-child,
.st-key-lenspick-kind [role="radiogroup"] > label > div:first-child { margin-top:3px; }

/* The harm filter is a secondary control, so it is one tinted button rather than ten
   chips across two rows. */
.st-key-harmpick button {
  background:rgba(42,120,214,.12) !important; border:1px solid #2a78d6 !important;
  font-weight:600 !important;
}
.st-key-harmpick button:hover { background:rgba(42,120,214,.20) !important; }

/* Open and close every row. Buttons rather than links, because this changes nothing a
   reader would want to share or bookmark. */
.tctl { display:flex; gap:6px; margin:0 0 8px; }
.tctl-b {
  font:inherit; font-size:13px; font-weight:600; padding:5px 11px; cursor:pointer;
  color:var(--ink-2); background:none; border:1px solid var(--grid-line); border-radius:8px;
}
.tctl-b:hover { background:rgba(42,120,214,.10); border-color:#2a78d6; color:inherit; }

/* The MIT scale as five rows. The empty top of the scale is the finding, so the zero
   rows are drawn rather than dropped, and the bars are measured against the largest
   band so the shape reads at a glance. */
.srows { display:flex; flex-direction:column; gap:4px; margin:4px 0 10px; }
.srow {
  display:grid; grid-template-columns:190px 1fr 130px; gap:14px; align-items:center;
  padding:5px 8px; border-radius:9px; text-decoration:none !important; color:inherit;
  border:1px solid transparent;
}
.srow:hover { background:rgba(42,120,214,.07); }
.srow.on { border-color:#2a78d6; background:rgba(42,120,214,.10); }
.strack {
  display:flex; align-items:center; gap:3px; height:22px; background:#e1e0d9;
  border-radius:5px; overflow:hidden;
}
.sbar { height:100%; display:block; border-radius:0; }
.sbar.extra { background:transparent; border:2px dashed; box-sizing:border-box; }
.scount { font-weight:700; font-variant-numeric:tabular-nums; color:#52514e; }
.scount small { font-weight:600; font-size:11px; color:#52514e; }
/* No prefers-color-scheme override on these. Streamlit picks the page theme on its
   own, and when the two disagreed the track rendered dark on a light page. */
p.legend {
  display:flex; flex-direction:column; gap:2px; margin:8px 0 4px; font-size:12px;
}
p.legend span { color:#52514e; line-height:1.45; }
/* The failure-type views. Longer labels than a severity pill, one neutral bar colour,
   and no hover state, because these rows are not links. */
.srows.lens .srow { grid-template-columns:270px 1fr 108px; cursor:default; }
.srows.lens .slabel { font-size:13px; line-height:1.35; overflow-wrap:anywhere; }
.srows.lens .srow:hover { background:transparent; }
@media (max-width: 760px) {
  .srow { grid-template-columns:140px 1fr 90px; gap:8px; }
  .srows.lens .srow { grid-template-columns:132px 1fr 76px; gap:8px; }
  .srows.lens .slabel { font-size:12px; }
}

/* Group headings. A bare word was not carrying enough, so the band name is sized up and
   the count sits beside it rather than inside the same sentence. */
.ghead {
  display:flex; align-items:baseline; gap:12px; flex-wrap:wrap;
  margin:22px 0 2px; padding:0 0 6px 12px; border-bottom:2px solid var(--grid-line);
}
.ghead .gname { font-size:20px; font-weight:700; letter-spacing:-.01em; }
.ghead .gcount {
  font-size:13px; font-weight:700; color:var(--ink-2); text-transform:uppercase;
  letter-spacing:.04em;
}
.ghead .gcount small {
  font-weight:600; font-size:11px; text-transform:none; letter-spacing:0; color:#52514e;
}
p.gmean { font-size:13px; color:#52514e; margin:0 0 10px; max-width:760px; line-height:1.5; }
.crow-empty {
  padding:14px; font-size:14px; color:var(--muted); border-top:1px solid var(--grid-line);
}

.fwtable td.fwk { white-space:nowrap; font-weight:600; width:200px; }
.fwtable tr.fwrow-s td.fwk { font-weight:400; font-style:italic; color:#52514e; }
.fwtag {
  display:inline-block; margin-left:8px; padding:1px 7px; border-radius:999px;
  background:rgba(42,120,214,.12); border:1px solid #2a78d6; color:#1d5fae;
  font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.04em;
}
a.fwlink { font-weight:700; }
.fwbasis { font-size:12px; color:#52514e; margin-top:2px; }
p.subhead {
  font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.04em;
  color:#52514e; margin:14px 0 4px;
}
p.org { margin:0 0 9px; padding:8px 10px; background:rgba(127,127,127,.07);
  border-radius:7px; }
p.fwnote { font-size:12px; color:#52514e; margin:6px 0 0; line-height:1.5; }
p.aiid {
  margin:10px 0 0; padding:8px 10px; border-left:3px solid var(--grid-line);
  background:rgba(127,127,127,.05); font-size:13px;
}
p.aiid span { font-size:12px; color:#52514e; }
i.aiidmark {
  font-style:normal; font-size:11px; color:#2a78d6; margin-left:4px; cursor:help;
}

/* Tabs inside an open row. The active pane is a class rather than :checked, because
   React resets natively injected form controls and the radio trick died silently. */
.ctabs .tabrow { display:flex; flex-wrap:wrap; gap:4px; margin:0 0 12px; }
.ctabs .tb {
  padding:6px 12px; cursor:pointer; font:inherit; font-size:13px; font-weight:600;
  color:var(--ink-2); background:none; border:1px solid transparent; border-radius:8px;
}
.ctabs .tb:hover { background:rgba(42,120,214,.10); }
.ctabs .tb.on { background:rgba(42,120,214,.16); border-color:#2a78d6; color:inherit; }
.ctabs .pane { display:none; }
.ctabs .pane.on { display:block; }
.casebody p { margin:0 0 7px; }
.casebody table.mini { border-collapse:collapse; margin:8px 0; width:100%; }
.casebody table.mini td, .casebody table.mini th {
  border:1px solid var(--grid-line); padding:5px 8px; text-align:left; font-size:13px;
  vertical-align:top;
}
@media (max-width: 900px) {
  .ctbl-head { display:none; }
  .crow > summary { grid-template-columns:1fr; gap:4px; }
  .casebody { padding:12px 14px; }
}

.seg { display:flex; gap:2px; height:28px; margin:10px 0 8px; }
.seg div:first-child { border-radius:6px 0 0 6px; }
.seg div:last-child { border-radius:0 6px 6px 0; }
.seglabels { display:flex; gap:2px; font-size:13px; color:var(--ink-2); }
.seglabels b { color:var(--ink); display:block; font-size:14px; }

.thesis {
  background:var(--surface,#fcfcfb); border:1px solid var(--ring,rgba(11,11,11,.10));
  border-left:4px solid #2a78d6; border-radius:10px; padding:18px 20px;
}
.thesis .t { font-size:19px; font-weight:650; line-height:1.3; margin:0 0 8px; }
.thesis p { margin:0; color:var(--ink-2); }
</style>
"""

APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "data" / "incidents.csv"

VERSION = "1.1"
UPDATED = "14 October 2026"

# The version being written on this branch. Every change log row for unreleased work
# carries WORKING rather than a typed string, so the release is two edits here and not
# a search through the log: set VERSION to this number and IN_PROGRESS to "". The date
# comes from UPDATED, which the pre-commit hook stamps from the commit itself.
IN_PROGRESS = ""
REPO_URL = "https://github.com/Saa2252/ai-agent-incident-register"
WORKING = f"{IN_PROGRESS} in progress" if IN_PROGRESS else VERSION

# The app imports its vocabularies and its evidence rule from the validator rather than
# restating them. A value the validator would reject cannot be displayed as valid here.
sys.path.insert(0, str(APP_DIR / "scripts"))
import validate_register as rules_check  # noqa: E402

# Streamlit reloads app.py when it changes. It does not reload the modules app.py
# imports, because those live in sys.modules for the life of the process, so a change
# to the validator reaches the page only on a restart. On 14 October 2026 a server that
# had been up since the morning raised AttributeError for a name added to the validator
# that same day, while every headless check passed, because each of those starts a
# fresh process and never sees the stale copy. This is the third time this project has
# shipped a control that passed and was not watching the thing that broke.
_rules_source = Path(rules_check.__file__)
_rules_stamp = _rules_source.stat().st_mtime_ns if _rules_source.exists() else 0
if getattr(rules_check, "_loaded_at", None) != _rules_stamp:
    rules_check = importlib.reload(rules_check)
    rules_check._loaded_at = _rules_stamp

COUNTED_GRADES = rules_check.COUNTED_GRADES
CONTROL_CLASSES = rules_check.CONTROL_CLASSES
OWASP_CODES = rules_check.OWASP_CODES
OWASP_STATUS = rules_check.OWASP_STATUS
OWASP_ROWS = rules_check.OWASP_ROWS
# OWASP's own one-line characterisation of each code, read from the same page the codes
# come from. Added 14 October 2026, after six cases were coded Not applicable by
# reasoning from the code names alone and five of them turned out to be described by
# ASI09 word for word.
OWASP_DESCRIPTIONS = {
    code: row.get("description", "") for code, row in OWASP_ROWS.items()
}
NIST_RMF_ROWS = rules_check.NIST_RMF_ROWS
EU_ARTICLE_ROWS = rules_check.EU_ARTICLE_ROWS
NIST_800_4_ROWS = rules_check.NIST_800_4_ROWS

GRADE_MEANING = {
    "A": "A primary record, meaning a ruling, a regulator notice, a vendor security advisory or a threat intelligence report, plus a second source on another site that corroborates it rather than restating it.",
    "B": "Two independent reputable reports on different sites, usually including the deployer's own public statement.",
    "C": "A single source, or an account the deployer has not addressed. Shown here, counted nowhere.",
}

KIND_MEANING = {
    "Incident": "Harm occurred. This follows the OECD definition.",
    "Hazard": "A near miss. The failure was demonstrated but no harm has been established.",
}

APPROVAL_MEANING = {
    "No": "No person saw the action before it took effect.",
    "Yes": "A person approved, and the approval did not prevent the failure.",
    "Yes, bypassed": "An approval gate existed on paper and did not hold.",
    "Unknown": "The public record does not say.",
}

# Colour is a second signal here, never the only one. Every badge carries its own words.

NIST_GAP_QUOTE = (
    "NIST names an immature information sharing ecosystem and a lack of trusted "
    "guidelines for monitoring methods and tools among the field's central gaps, in "
    "[AI 800-4, Challenges to the Monitoring of Deployed AI Systems]"
    "(https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-4.pdf), published 6 March 2026. "
    "Both phrases are gap headings in sections 3.1.1 and 3.1.2."
)


# --------------------------------------------------------------------------- loading


def data_stamp(*paths):
    """A cache key that changes when the data changes.

    st.cache_data keys on the function's code and arguments, never on the files the
    function happens to open. Adding a column to incidents.csv therefore left the key
    identical, and a hot reload on the hosted app ran new code against a DataFrame
    cached before the column existed, which is how v1.0 reached the live site as a
    KeyError while every local check passed. Local runs never caught it because each
    one starts with a cold cache.

    The loaders take this as "stamp" and not as "_stamp". st.cache_data deliberately
    leaves any argument whose name starts with an underscore out of the key, so the
    first version of this fix was inert: the stamp moved, the key did not, and the
    same KeyError came back on 14 October 2026 on a dev server that had been up since
    before the framework basis columns were added. The test below it now changes the
    file and asserts the loader returns the change, rather than asserting the stamp
    moved and assuming the rest.
    """
    return tuple(
        (path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else (0, 0)
        for path in paths
    )


RATINGS_FILE = APP_DIR / "data" / "case_harm_ratings.csv"
MIT_FRAMEWORK_FILE = APP_DIR / "frameworks" / "mit_severity_framework.csv"


@st.cache_data
def load_register(stamp):
    frame = pd.read_csv(DATA_FILE, dtype=str).fillna("")
    frame["counted"] = frame["evidence_grade"].isin(COUNTED_GRADES)
    frame["year"] = frame["event_date"].str.slice(0, 4)
    ratings = pd.read_csv(RATINGS_FILE, dtype=str).fillna("")
    ratings["level"] = ratings["level"].astype(int)
    frame["mit_level"] = frame["id"].map(ratings.groupby("case_id")["level"].max())
    frame["mit_floored"] = frame["id"].map(
        ratings[ratings["at_least"] == "Yes"].groupby("case_id")["level"].max()
    ).notna() & (
        frame["id"].map(ratings[ratings["at_least"] == "Yes"].groupby("case_id")["level"].max())
        == frame["id"].map(ratings.groupby("case_id")["level"].max())
    )
    return frame


@st.cache_data
def load_harm_ratings(stamp):
    """Per-case harm ratings on MIT's framework, and the headline level per case."""
    ratings = pd.read_csv(RATINGS_FILE, dtype=str).fillna("")
    ratings["level"] = ratings["level"].astype(int)
    headline = ratings.groupby("case_id")["level"].max().to_dict()
    floored = (
        ratings[ratings["at_least"] == "Yes"].groupby("case_id")["level"].max().to_dict()
    )
    return ratings, headline, floored


@st.cache_data
def load_mit_framework(stamp):
    frame = pd.read_csv(MIT_FRAMEWORK_FILE, dtype=str)
    frame["level"] = frame["level"].astype(int)
    return frame


def esc(value) -> str:
    """Escape CSV-derived text before it reaches any raw-HTML render.

    This repo is public and meant to be forked, so CSV content is treated as untrusted
    input even though today it is hand written.
    """
    return html.escape(str(value), quote=True)


RUNNABLE_TESTS = {
    "AIR-002": ("tests/test_authority.py", "DestructiveActionsNeedAGate"),
    "AIR-004": ("tests/test_authority.py", "TheGateMustBeOperating"),
    "AIR-010": ("tests/test_injection.py", "UntrustedContentCannotAct"),
}


def tag(text):
    """A neutral outlined tag. Nothing here encodes data, so nothing here is coloured.

    Only the severity pill is coloured on a card, because severity is the only thing
    colour means on this site.
    """
    return (
        '<span style="display:inline-block;border:1px solid rgba(128,128,128,.4);'
        "border-radius:4px;padding:2px 8px;font-size:0.78rem;font-weight:600;"
        f'margin:0 6px 4px 0;white-space:nowrap">{esc(text)}</span>'
    )


def severity_pill(level, floored=False):
    """Colour, a five-bar meter and the word. Never colour alone."""
    name = MIT_LEVELS[level]
    bars = "".join(f'<i class="{"f" if i <= level else ""}"></i>' for i in range(1, 6))
    prefix = "at least " if floored else ""
    return (
        f'<span class="sev s-{MIT_SLUG[level]}">'
        f'<span class="meter" aria-hidden="true">{bars}</span>{esc(prefix + name)}</span>'
    )


def grade_badge(grade):
    """Monochrome. A filled, B outlined, C dashed and followed by the words."""
    badge = f'<span class="grade g-{grade.lower()}"><span>{esc(grade)}</span></span>'
    if grade == "C":
        badge += ' <span style="font-size:12px;color:var(--muted)">not counted</span>'
    return badge


def _home_link(chosen, show_uncounted=False):
    """A Home URL that keeps the filter the reader is already in.

    Every link on Home has to carry the current view forward, or clicking a case ID
    silently drops the filter and the table stops matching the heading above it.
    """
    parts = [f"view={key}" for key in chosen]
    if show_uncounted:
        parts.append("c=1")
    return "?" + "&".join(parts) if parts else "?"


def frameworks_html(row):
    """Where this case sits in each published framework, with the official wording.

    Every name and every clause text is read from the files in frameworks/, so a label
    on a card is the framework owner's words and not a paraphrase typed here. ISO/IEC
    42001 is deliberately absent: its numbers have never been read against the text.
    """
    def line(label, value, text, basis, primary):
        """One mapping. The first for a framework is the one every count uses."""
        body = f"<b>{esc(value)}</b>"
        if text:
            body += f" &middot; {esc(text)}"
        mark = '<span class="fwtag">counted</span>' if primary else ""
        return (
            f'<tr class="{"fwrow-p" if primary else "fwrow-s"}">'
            f'<td class="fwk">{esc(label)}</td><td>{body}{mark}'
            f'<div class="fwbasis">{esc(basis)}</div></td></tr>'
        )

    def block(name, refs, text_for, basis):
        out = []
        for i, ref in enumerate(refs):
            out.append(line(name if i == 0 else "also maps to", ref,
                            text_for(ref), basis, i == 0))
        return out

    rows = []
    rows += block(
        "NIST AI RMF 1.0",
        [r.strip() for r in row["nist_ai_rmf"].split(",") if r.strip()],
        lambda ref: NIST_RMF_ROWS.get(ref, {}).get("text", ""),
        row["nist_ai_rmf_basis"],
    )

    def eu_text(ref):
        inner = ref
        if ref.startswith("None (closest:"):
            inner = "Article " + ref.split("Article ")[1].rstrip(")")
        return EU_ARTICLE_ROWS.get(inner, {}).get("title", "")

    rows += block(
        "EU AI Act",
        [r.strip() for r in row["eu_ai_act"].split(",") if r.strip()],
        eu_text, row["eu_ai_act_basis"],
    )
    rows += block(
        "OWASP Agentic Top 10 2026", [row["owasp_code"]],
        lambda ref: " ".join(
            x for x in (OWASP_CODES.get(ref, ""), OWASP_DESCRIPTIONS.get(ref, "")) if x
        ),
        row["owasp_code_basis"],
    )
    rows += block(
        "NIST AI 800-4 monitoring", [row["nist_800_4_category"]],
        lambda ref: NIST_800_4_ROWS.get(ref, {}).get("what_it_covers", ""),
        "Register's summary, not NIST's wording",
    )
    return (
        '<table class="mini fwtable"><tbody>' + "".join(rows) + "</tbody></table>"
        "<p class=\"fwnote\">The row marked <b>counted</b> is this case's primary "
        "mapping, and the only one any figure on the Findings page uses. The rest also "
        "fit and are counted nowhere. Names and clause text come from the published "
        "lists in this repository, each with its source and the date it was read."
        '<br><a class="fwlink" target="_self" href="?screen=Method&amp;rule=mapping">'
        "How these mappings were made &rarr;</a></p>"
    )


def event_date_label(row):
    """The event date shown at the precision the record actually supports.

    Every row still carries a full date so the table can sort and the validator can
    compare. Two rows are dated less precisely than that by their own sources, and
    printing a day for them would be precision this register does not have.
    """
    precision = (row.get("event_date_precision") or "day").strip()
    if precision == "day":
        return row["event_date"]
    stamp = datetime.date.fromisoformat(row["event_date"])
    month = stamp.strftime("%b %Y")
    if precision == "month":
        return month
    anchor = re.search(
        r"(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*",
        row["source_1_label"],
    )
    if not anchor:
        return f"{month}, week not named"
    return f"{month}, week before {anchor.group(1)} {anchor.group(2)}"


def aiid_mark(row):
    """A marker in the ID cell when another index holds the same event.

    Not a link. A link inside the summary would open the row as well as the page, so
    the real link lives on the card where it does one thing.
    """
    if not row["aiid_id"]:
        return ""
    return (
        f'<i class="aiidmark" title="AI Incident Database, incident '
        f'{esc(row["aiid_id"])}">&#8599;</i>'
    )


def aiid_line(row):
    """The same event's number in the AI Incident Database, as a pointer not a source.

    The database is on the aggregator list, which means it is how cases are found and
    never what a claim rests on. It is still the first place a reader will go to check
    this register against something else, so every row says whether it is there.
    """
    if row["aiid_id"]:
        body = (
            '<a href="https://incidentdatabase.ai/cite/'
            f'{esc(row["aiid_id"])}/" target="_blank" rel="noopener">'
            f'AI Incident Database, incident {esc(row["aiid_id"])}</a>'
        )
    else:
        body = "Not in the AI Incident Database."
    return (
        f'<p class="aiid"><b>Cross-reference, not a source.</b> {body}'
        f'<br><span>{esc(row["aiid_match_basis"])} '
        f'Checked {esc(row["aiid_checked_on"])}.</span></p>'
    )


def case_sections_html(row, ratings=None):
    """One case's full record as plain HTML.

    Rendered as markup rather than Streamlit widgets so it can sit inside a <details>
    element in the table. Widgets cannot: each one is its own block outside the table,
    and opening a row would rerun the script and lose the reader's place.
    """
    def para(text):
        return f"<p>{esc(text)}</p>" if text else ""

    sources = (
        f'<p><a href="{esc(row["source_1_url"])}" target="_blank" rel="noopener">'
        f'1. {esc(row["source_1_label"])}</a></p>'
    )
    if row["source_2_url"]:
        sources += (
            f'<p><a href="{esc(row["source_2_url"])}" target="_blank" rel="noopener">'
            f'2. {esc(row["source_2_label"])}</a></p>'
        )

    deployment = "".join(
        f"<tr><td>{esc(label)}</td><td>{esc(row[field])}</td></tr>"
        for label, field in (
            ("Someone reviewed its behaviour first", "deploy_evidence_seen"),
            ("A role could halt or roll it back", "deploy_stop_authority"),
            ("A date was set to look at it again", "deploy_review_date"),
        )
    )

    harm_rows = ""
    if ratings is not None:
        mine = ratings[ratings["case_id"] == row["id"]].sort_values("level", ascending=False)
        harm_rows = "".join(
            f"<tr><td>{esc(r.harm_type)}</td>"
            f"<td>{r.level} {MIT_LEVELS[r.level]}"
            f"{' (at least)' if r.at_least == 'Yes' else ''}</td>"
            f"<td>{esc(r.basis)}</td></tr>"
            for r in mine.itertuples()
        )
        if harm_rows:
            harm_rows = (
                '<table class="mini"><thead><tr><th>Harm type</th><th>Level</th>'
                f"<th>Why</th></tr></thead><tbody>{harm_rows}</tbody></table>"
            )

    panes = [
        (
            "What happened",
            # Named here rather than worked into every title. Fourteen of the twenty one
            # titles did not carry the organisation, and rewriting them to force it in
            # would have risked the facts for the sake of a convention.
            f'<p class="org"><b>Organisation.</b> {esc(row["deployer"])}'
            f'<br><b>When.</b> {esc(event_date_label(row))}</p>'
            + para(row["what_happened"])
            + '<p class="subhead">Why it is in the register</p>'
            + para(row["why_in_register"]),
        ),
        (
            "What was missing",
            f"<p><b>{esc(row['control_class'])}.</b> "
            f"{esc(CONTROL_CLASSES[row['control_class']])}</p>"
            f"<p><b>State it was in: {esc(MATURITY_LABEL[row['control_maturity']])}.</b> "
            f"{esc(MATURITY_MEANING[row['control_maturity']])}</p>"
            f"<p><b>Who directed the agent: {esc(row['directed_by'])}.</b> "
            f"{esc(DIRECTED_MEANING[row['directed_by']])}</p>"
            + para(row["missing_control"]) + para(row["missing_control_basis"])
            + para(row["missing_control_note"]),
        ),
        (
            "Test before launch",
            para(row["test_before_launch"])
            + f"<p><b>Pass mark.</b> {esc(row['test_pass_mark'])}</p>"
            + f"<p><b>Signal after launch.</b> {esc(row['signal_after_launch'])}</p>",
        ),
        (
            "Evidence",
            f"<p><b>Grade {esc(row['evidence_grade'])}.</b> "
            f"{esc(GRADE_MEANING[row['evidence_grade']])}</p>"
            + para(row["evidence_note"])
            + sources
            + aiid_line(row)
            + f'<table class="mini"><tbody>{deployment}</tbody></table>'
            + harm_rows
            + f"<p><b>EU Article 3(49), closest limb ({esc(row['eu_closest_limb'])}).</b> "
            f"{esc(row['eu_basis'])}</p>",
        ),
        ("Aftermath", para(row["what_changed_after"])),
        ("Frameworks", frameworks_html(row)),
    ]

    # Tabs without a Streamlit widget. The first attempt used hidden radios and a CSS
    # sibling selector, which is the usual trick and does not survive here: React's event
    # system resets the state of form controls injected as raw HTML, so clicking a tab
    # left the radio unchecked and the pane never changed. Buttons plus a class, toggled
    # by one delegated listener for the whole page, sidesteps that entirely.
    buttons, bodies = [], []
    for i, (label, body) in enumerate(panes):
        on = " on" if i == 0 else ""
        buttons.append(f'<button type="button" class="tb{on}">{esc(label)}</button>')
        bodies.append(f'<div class="pane{on}">{body}</div>')
    return (
        '<div class="casebody"><div class="ctabs">'
        f'<div class="tabrow">{"".join(buttons)}</div>'
        + "".join(bodies)
        + "</div></div>"
    )



def open_case_once(valid_ids):
    """Honour a ?case= deep link once, then take it out of the URL.

    Nothing in the app sets this parameter any more: rows open with a click on the row
    itself, which never touches the address bar. It exists only so a posted link can open
    a case. Left in place it pinned that row open on every later render, on Home and on
    Findings both, because every render read it again. Stripping it with replaceState
    rather than by rewriting st.query_params avoids a rerun, so the row the reader was
    sent to stays open while the link stops following them around.
    """
    wanted = st.query_params.get("case")
    if not wanted or wanted not in set(valid_ids):
        return None
    components.html(
        "<script>"
        "const doc = window.parent.document;"
        "const scrollerOf = (el) => {"
        "  let n = el.parentElement;"
        "  while (n) {"
        "    const o = window.parent.getComputedStyle(n).overflowY;"
        "    if (/auto|scroll/.test(o) && n.scrollHeight > n.clientHeight) return n;"
        "    n = n.parentElement;"
        "  }"
        "  return doc.scrollingElement || doc.documentElement;"
        "};"
        "const go = () => {"
        f"  const el = doc.getElementById({wanted!r});"
        "  if (!el) return false;"
        "  const s = scrollerOf(el);"
        "  const base = s === (doc.scrollingElement || doc.documentElement)"
        "    ? 0 : s.getBoundingClientRect().top;"
        "  s.scrollTop += el.getBoundingClientRect().top - base - 20;"
        "  const u = new URL(window.parent.location);"
        "  u.searchParams.delete('case');"
        "  window.parent.history.replaceState({}, '', u);"
        "  return true;"
        "};"
        "let n = 0;"
        "const t = setInterval(() => { if (go() || ++n > 60) clearInterval(t); }, 150);"
        "</script>",
        height=0,
    )
    return wanted


def empty_case_table():
    """A group with no cases still gets the table, so the shape of the scale is visible.

    Dropping the empty levels would quietly flatter the data: the point of using a scale
    that reaches further than this register does is that a reader can see how far.
    """
    return '<div class="ctbl"><div class="crow-empty">No cases in this register</div></div>'


def table_controls():
    """Open and close every row at once. Client side, so it costs no rerun."""
    return (
        '<div class="tctl">'
        '<button type="button" class="tctl-b" data-all="open">Open all</button>'
        '<button type="button" class="tctl-b" data-all="close">Close all</button>'
        "</div>"
    )


def case_table(view, ratings=None, open_id=None):
    """The case index, with each row expanding in place.

    A <details> element per case rather than a <table>, because a real table cannot hold
    an expanding panel between two rows without colspan tricks that fall apart on a
    phone. The summary is a grid lined up with the header, so it still reads as a table.

    No Streamlit widget is involved, so opening a row is a browser toggle rather than a
    rerun, and the reader keeps their place, their filters and their scroll position.
    """
    head = (
        '<div class="ctbl-head"><span>ID</span><span>Date</span>'
        "<span>Organisation</span><span>What happened</span>"
        "<span>Missing control</span><span>Severity</span><span>Evidence</span></div>"
    )
    rows = []
    for _, row in view.iterrows():
        klass = " notcounted" if not row["counted"] else ""
        is_open = " open" if open_id and row["id"] == open_id else ""
        # The deployer field names the organisation and sometimes the tool maker too.
        # The column shows the organisation, and the card carries the full phrasing.
        org = row["deployer"].split(",")[0].strip()
        rows.append(
            f'<details class="crow{klass}" id="{esc(row["id"])}"{is_open}>'
            '<summary><span class="cid"><i class="caret"></i>'
            f'{esc(row["id"])}{aiid_mark(row)}</span>'
            f'<span class="cdate">{esc(event_date_label(row))}</span>'
            f'<span>{esc(org)}</span><span>{esc(row["title"])}</span>'
            f'<span>{esc(row["control_class"])}</span>'
            f'<span>{severity_pill(row["mit_level"], row["mit_floored"])}</span>'
            f'<span>{grade_badge(row["evidence_grade"])}</span></summary>'
            + case_sections_html(row, ratings)
            + "</details>"
        )
    return f'<div class="ctbl">{head}{"".join(rows)}</div>'


# The nine columns an organisation's own incident register carries and a public record
# cannot fill, in the three groups a response actually moves through.
INTERNAL_GROUPS = (
    ("Intake", ("Detected", "Reported by", "Owner")),
    ("Response", ("Root cause", "Corrective action", "Due")),
    ("Closure", ("Closed", "Approved by", "Regulator notified")),
)
INTERNAL_COLUMNS = [c for _, cols in INTERNAL_GROUPS for c in cols]

# The one column a public record sometimes fills. Everything else in the nine is filled
# from logs, tickets and the people involved, and none of that is published.
CORRECTIVE = {
    "Documented": ("On public record", "known"),
    "Partial": ("Partly on record", "part"),
    "Undocumented": ("", ""),
}


def internal_cells(row):
    """The nine internal cells for one case, as markup and as a tally.

    Nothing is invented. A cell a public record cannot fill is drawn empty and dashed,
    which is the point of the view: the gap is the finding.
    """
    html_cells, filled, partly = [], 0, 0
    for name in INTERNAL_COLUMNS:
        text, state = "", ""
        if name == "Corrective action":
            text, state = CORRECTIVE.get(row["aftermath_status"], ("", ""))
            if state == "known":
                filled += 1
            elif state == "part":
                partly += 1
        if text:
            html_cells.append(f'<span class="icell {state}">{esc(text)}</span>')
        else:
            html_cells.append('<span class="icell empty">\u2013</span>')
    return "".join(html_cells), filled, partly


def internal_summary(view):
    """The computed line under the table. Cells, not rows, because cells is the claim."""
    total = len(view) * len(INTERNAL_COLUMNS)
    filled = partly = 0
    for _, row in view.iterrows():
        _, f, p = internal_cells(row)
        filled += f
        partly += p
    return total - filled - partly, total, filled, partly


def internal_table(view, ratings=None, open_id=None):
    """The same cases with the columns an internal register adds, drawn empty.

    Missing control, severity and evidence are dropped here so the nine dotted columns
    have a readable width. They are all still on the card, which opens in this view
    exactly as it does in the other. The table scrolls sideways inside its own container
    rather than squeezing twelve columns into the page width.
    """
    groups = (
        '<div class="ihead-groups"><span class="gpub">From the public record</span>'
        + "".join(
            f'<span class="gint" style="grid-column: span 3">{esc(name)}</span>'
            for name, _ in INTERNAL_GROUPS
        )
        + "</div>"
    )
    head = (
        '<div class="ctbl-head itbl-head"><span>ID</span><span>Date</span>'
        "<span>Organisation</span><span>What happened</span>"
        + "".join(f"<span>{esc(c)}</span>" for c in INTERNAL_COLUMNS)
        + "</div>"
    )
    rows = []
    for _, row in view.iterrows():
        klass = " notcounted" if not row["counted"] else ""
        is_open = " open" if open_id and row["id"] == open_id else ""
        org = row["deployer"].split(",")[0].strip()
        cells, _, _ = internal_cells(row)
        rows.append(
            f'<details class="crow{klass}" id="{esc(row["id"])}"{is_open}>'
            '<summary><span class="cid"><i class="caret"></i>'
            f'{esc(row["id"])}{aiid_mark(row)}</span>'
            f'<span class="cdate">{esc(event_date_label(row))}</span>'
            f'<span>{esc(org)}</span><span>{esc(row["title"])}</span>'
            f"{cells}</summary>"
            + case_sections_html(row, ratings)
            + "</details>"
        )
    return f'<div class="ctbl itbl">{groups}{head}{"".join(rows)}</div>'


def describe_count(total, counted):
    """Render a composition count, saying plainly how much of it feeds a number."""
    rows = "row" if total == 1 else "rows"
    if total == counted:
        return f"{total} {rows}"
    if counted == 0:
        return f"{total} {rows}, not counted"
    return f"{total} {rows}, {counted} of them counted"


def headline(frame):
    """The opening line of the register, computed from the rows that count.

    The claim the register makes is about which control was missing, so the number
    that carries it is a count of control classes. Grade C rows are excluded.
    """
    counted = frame[frame["counted"]]
    total = len(counted)
    accuracy = int((counted["control_class"] == "Accuracy").sum())
    not_accuracy = total - accuracy
    by_class = counted["control_class"].value_counts().to_dict()
    # The rubric tests accuracy last, so a case that is both a permissions failure and
    # an accuracy failure is classed as the former. That ordering could be producing
    # the finding on its own, so the register measures the effect rather than arguing
    # about it. A row where the agent stated nothing untrue cannot become an accuracy
    # failure under any ordering, which makes it an order-independent floor.
    said_untrue = counted["said_something_untrue"] == "Yes"
    # Could the agent do more than read. This is the authority it actually held at the
    # time, which is not always the authority its owners believed it held.
    acted = counted["authority"].apply(
        lambda value: bool({"Write", "Delete", "Pay", "Promise"} & set(value.split("|")))
    )
    return {
        "total": total,
        "all_rows": len(frame),
        "accuracy": accuracy,
        "not_accuracy": not_accuracy,
        "by_class": by_class,
        "accuracy_first": int(len(counted) - said_untrue.sum()),
        "would_change_class": int(said_untrue.sum() - accuracy),
        # The IDs as well as the count. Three were typed here and the list went stale
        # the moment the register grew past twelve cases.
        "change_class_ids": sorted(
            counted[(counted["said_something_untrue"] == "Yes")
                    & (counted["control_class"] != "Accuracy")]["id"]
        ),
        "said_nothing_untrue": int((~said_untrue).sum()),
        "said_untrue": int(said_untrue.sum()),
        "aftermath_documented": int((counted["aftermath_status"] == "Documented").sum()),
        "aftermath_partial": int((counted["aftermath_status"] == "Partial").sum()),
        "aftermath_undocumented": int((counted["aftermath_status"] == "Undocumented").sum()),
        "control_absent": int((counted["control_maturity"] == "Absent").sum()),
        "basis_stated": int(counted["missing_control_basis"].str.startswith("Stated").sum()),
        "basis_entailed": int(counted["missing_control_basis"].str.startswith("Entailed").sum()),
        "basis_reading": int(counted["missing_control_basis"].str.startswith("Reading").sum()),
        "roles": (
            pd.concat([counted["control_owner_role"], counted["accountable_role"]])
            .value_counts().to_dict()
        ),
        "control_designed": int((counted["control_maturity"] == "Designed").sum()),
        "control_implemented": int((counted["control_maturity"] == "Implemented").sum()),
        "control_bypassable": int((counted["control_maturity"] == "Bypassable").sum()),
        "control_unknown": int((counted["control_maturity"] == "Unknown").sum()),
        "no_stop_authority_recorded": int((counted["deploy_stop_authority"] == "Not disclosed").sum()),
        "no_review_recorded": int((counted["deploy_review_date"] == "Not disclosed").sum()),
        "no_evidence_recorded": int((counted["deploy_evidence_seen"] == "Not disclosed").sum()),
        "bearer_no_control": int((counted["harm_bearer_had_control"] == "No").sum()),
        "no_approval": int((counted["human_approval"] != "Yes").sum()),
        "could_act": int(acted.sum()),
        "read_only": int((~acted).sum()),

        "years": f"{counted['year'].min()} to {counted['year'].max()}",
    }


# ------------------------------------------------------------------------------ home


def severity_rows(counted, uncounted, active, link_for):
    """The MIT scale as five rows, including the empty top.

    A stacked bar hid the shape that matters: the two levels this register never
    reaches. Five rows with a zero on them say it outright. Severity is this site's
    only data colour, so the bars carry it and nothing else here does.
    """
    widest = max([int((counted["mit_level"] == l).sum()) for l in MIT_ORDER] + [1])
    rows = []
    for level in MIT_ORDER:
        n = int((counted["mit_level"] == level).sum())
        extra = int((uncounted["mit_level"] == level).sum())
        on = " on" if active == MIT_LEVELS[level] else ""
        width = 100 * n / widest if widest else 0
        extra_width = 100 * extra / widest if widest else 0
        bar = (
            f'<span class="sbar" style="width:{width:.2f}%;'
            f'background:var(--sev-{MIT_SLUG[level]})"></span>'
        )
        if extra:
            bar += (
                f'<span class="sbar extra" style="width:{extra_width:.2f}%;'
                f'border-color:var(--sev-{MIT_SLUG[level]})"></span>'
            )
        rows.append(
            f'<a class="srow{on}" target="_self" href="{esc(link_for(MIT_LEVELS[level]))}">'
            f'<span class="slabel">{severity_pill(level)}</span>'
            f'<span class="strack">{bar}</span>'
            f'<span class="scount">{n}'
            + (f'<small> +{extra} not counted</small>' if extra else "")
            + "</span></a>"
        )
    return f'<div class="srows">{"".join(rows)}</div>'


def dots(filled, total):
    """A row of dots so "5 of 11" reads without arithmetic."""
    return (
        '<div class="dots" role="img" aria-label="' + f"{filled} of {total}" + '">'
        + "".join(f'<i class="{"on" if i < filled else ""}"></i>' for i in range(total))
        + "</div>"
    )


def how_to_read(text):
    """One grey line under every table, saying what it is and is not."""
    st.caption(text)


def and_join(items):
    """A, B and C. One place, so every list of IDs on the site reads the same way."""
    items = list(items)
    if not items:
        return "none"
    if len(items) == 1:
        return items[0]
    return " and ".join([", ".join(items[:-1]), items[-1]])


def count_word(n):
    """Small counts read better spelled out, and the sentence stays computed."""
    return {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}.get(n, str(n))


def own_account_rows(counted):
    """The rows whose primary record the implicated organisation published itself, and
    the subset of those with no corroboration beyond restatement.

    Read off the source label rather than listed by hand. A label reading "CNN, 12 July
    2025, reporting the company's own account" names a news outlet as the primary
    record, not the account itself, so "reporting" excludes the row: the earlier
    sentence counted AIR-016 and so said six where the claim holds for five. The subset
    is the grade B rows, because grade A already requires the second source to
    corroborate rather than restate, so a grade A row is corroborated by definition.
    Findings and the Limits bullet both call this, so the two cannot drift apart.
    """
    own = counted[
        counted["source_1_label"].str.contains("own account", case=False)
        & ~counted["source_1_label"].str.contains("reporting", case=False)
    ]
    return sorted(own["id"]), sorted(own[own["evidence_grade"] == "B"]["id"])


def tab_what_was_missing(frame):
    facts = headline(frame)
    counted = frame[frame["counted"]]

    by_class = Counter(counted["control_class"])
    attacker = int((counted["directed_by"] == "Attacker").sum())
    # The cases where the operator got in by claiming the work was authorised. Derived
    # from the rows rather than listed by hand, so a fourth case joins the sentence on its
    # own. Each of these three carries the claim in its own account or its basis, and for
    # the extortion campaign it is in the provider's full threat intelligence report.
    claim = "authorised security test|authorised penetration test|authorised security tester"
    bypass = sorted(
        counted[
            counted["what_happened"].str.contains(claim, case=False, regex=True)
            | counted["missing_control_basis"].str.contains(claim, case=False, regex=True)
        ]["id"]
    )
    uncounted = sorted(frame[~frame["counted"]]["id"])

    st.markdown(
        f"#### In {facts['not_accuracy']} of {facts['total']} cases, the missing "
        "safeguard wasn't accuracy."
    )
    st.markdown(
        "These agents did not mostly fail by getting facts wrong. They failed because "
        "they were allowed to do too much, or because they obeyed instructions they "
        "should have ignored."
    )
    st.markdown(
        f"Of the {facts['total']} cases with strong enough evidence to count, only "
        f"{by_class['Accuracy']} come down to the agent saying something untrue. In "
        f"{by_class['Authority']}, the agent had more power than its task needed: it "
        "could delete, send or change things with no check (Authority). In "
        f"{by_class['Boundary']}, it treated text it was reading, such as an email, web "
        "page or document, as an instruction to follow (Boundary). The table below "
        "defines all five types. This split depends partly on the order the types are "
        f"checked in. If accuracy is checked first, {facts['accuracy_first']} of "
        f"{facts['total']} still involve no false statement at all."
    )
    st.markdown("##### Who set the agent in motion?")
    st.markdown(
        f"In {attacker} of the {facts['total']} cases, an attacker was directing the "
        f"agent. In the other {facts['total'] - attacker}, no attacker was involved. The "
        "harm came from ordinary use, or from the agent doing what the organisation "
        "running it had set it up to do. Most failures in this register were not attacks. "
        "They came from how the agent was deployed."
    )
    words = {1: "once", 2: "twice", 3: "three times", 4: "four times", 5: "five times"}
    how_often = words.get(len(bypass), f"{len(bypass)} times")
    st.markdown(f"##### One trick worked {how_often}")
    joined = and_join(bypass)
    st.markdown(
        f"In {joined}, attackers got past the model's safeguards simply by telling it "
        "the work was authorised security testing. Nothing in the public record shows "
        "any of the providers has since changed how its models handle that claim. If "
        "your agent can take security-sensitive actions, test whether this claim gets it "
        "past your own safeguards."
    )
    st.markdown(
        f"**The five types of missing safeguard, across the {facts['total']} counted "
        "cases**"
    )
    rows = []
    for name in sorted(frame["control_class"].unique()):
        n = int((counted["control_class"] == name).sum())
        ids = ", ".join(sorted(counted[counted["control_class"] == name]["id"]))
        extra = sorted(frame[(frame["control_class"] == name) & ~frame["counted"]]["id"])
        if extra:
            ids += f" (+ {', '.join(extra)}, not counted)"
        rows.append(
            f"<tr><td>{esc(name)}</td><td>{esc(CONTROL_CLASSES[name])}</td>"
            f'<td style="text-align:right">{n}</td><td>{esc(ids)}</td></tr>'
        )
    rows.append(
        f'<tr><td><b>Total</b></td><td></td><td style="text-align:right"><b>'
        f"{facts['total']}</b></td><td></td></tr>"
    )
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr>'
        "<th>Missing control</th><th>What it means</th><th>Counted cases</th>"
        f"<th>Case IDs</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    how_to_read(
        f"One more case, {uncounted[0] if uncounted else 'none'}, is shown in the register "
        "but not counted, because it rests on a single source. Each case is given one "
        "missing safeguard, chosen by a fixed order of checks that tests accuracy last."
        if len(uncounted) == 1 else
        f"{len(uncounted)} cases are shown in the register but not counted, because they "
        "rest on a single source. Each case is given one missing safeguard, chosen by a "
        "fixed order of checks that tests accuracy last."
    )

    st.markdown("")
    st.markdown("#### What state was that control in?")
    st.markdown(
        f"**{facts['control_absent']} of {facts['total']} had no such control in any form.**"
    )
    labels = list(MATURITY_LABEL.items())
    rows = []
    for key, label in labels:
        subset = counted[counted["control_maturity"] == key]
        rows.append(
            f"<tr><td>{esc(label)}</td>"
            f'<td style="text-align:right">{len(subset)}</td>'
            f"<td>{esc(', '.join(sorted(subset['id'])))}</td></tr>"
        )
    st.markdown(f"**What state that safeguard was in, across {facts['total']} counted cases**")
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr>'
        "<th>State of the control</th><th>Cases</th><th>Case IDs</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    how_to_read(
        "A control can be designed, implemented, evidenced in an audit, and still not be "
        "stopping anything. That third row is the one worth dwelling on."
    )

    st.markdown("")
    st.markdown("#### Two counts that change where you look")
    st.markdown(
        f"In {facts['no_approval']} of {facts['total']}, the public account describes no "
        "approval step before the action took effect. That field carries no source of "
        "its own, unlike the stop-authority field, so read it as this register's reading "
        "of each account rather than a sourced absence."
    )
    st.markdown(
        f"In {facts['read_only']} of the {facts['total']}, the agent could only read. It "
        "could not delete, send, buy or change anything. That did not keep those cases "
        "out of this register. An agent that only reads can still speak, and what it says "
        "can bind the organisation running it. Check what your own agent can say, not "
        "only what it can do."
    )
    with st.expander("Why it matters"):
        st.markdown(
            "Putting accuracy last in the rubric is a choice that could manufacture the "
            "result, so the register measures the effect rather than asking to be trusted "
            f"on it. {facts['would_change_class']} rows change class when accuracy is "
            "tested first. The finding the register actually rests on is structural: in "
            "none of the counted cases was an untrue statement sufficient on its own. "
            "Harm always also required authority the agent should not have held, reach it "
            "should not have had, or a path nobody was monitoring."
        )


# ------------------------------------------------------------- framework lenses

# Severity is this site's only data colour, so the failure-type views use one neutral
# blue for every bar and print the category name beside it rather than encoding it.
LENS_BAR = "#2a78d6"

LENS_LABEL = {
    "mit": ("MIT harm severity scale", "How big was it, compared with all AI harm?"),
    "eu": ("EU AI Act serious-incident test",
           "Would it trigger mandatory reporting in the EU?"),
    "classes": ("This register's classes", "Which safeguard was missing?"),
    "owasp": ("OWASP Agentic Top 10", "Which known attack pattern?"),
    "rmf": ("NIST AI RMF", "Which governance function was missing?"),
    "articles": ("EU AI Act articles",
                 "Which provision addresses the missing safeguard?"),
    "monitoring": ("NIST AI 800-4 monitoring", "Which kind of monitoring was missing?"),
}
LENS_BAD = ["mit", "eu"]
LENS_KIND = ["classes", "owasp", "rmf", "articles", "monitoring"]
HOW_BAD_TAB = "How bad"
WHAT_KIND_TAB = "What kind of failure"
LENS_TAB = dict(
    [(s, HOW_BAD_TAB) for s in LENS_BAD] + [(s, WHAT_KIND_TAB) for s in LENS_KIND]
)


def _split(value):
    """A comma separated field as a list. Two framework fields hold several values."""
    return [v.strip() for v in str(value).split(",") if v.strip()]


def _eu_article(value):
    """The article a value points at. "None (closest: Article 15)" points at 15."""
    if value.startswith("None (closest:"):
        return "Article " + value.split("Article ")[1].rstrip(")")
    return value


def _eu_label(key):
    title = EU_ARTICLE_ROWS.get(_eu_article(key), {}).get("title", "")
    if key.startswith("None (closest:"):
        return f"No provision applies, closest is {_eu_article(key)}"
    return f"{key} {title}".strip()


FRAMEWORK_LENSES = {
    "owasp": {
        "name": "OWASP Top 10 for Agentic Applications, 2026",
        "unit": "pattern",
        "plural": "patterns",
        "multi": False,
        "show_zeros": True,
        "rows": lambda: OWASP_ROWS,
        "basis_field": "owasp_code_basis",
        "catalogue": lambda: list(OWASP_CODES),
        "values": lambda row: _split(row["owasp_code"]),
        "label": lambda key: f"{key} {OWASP_CODES.get(key, '')}".strip(),
        "meaning": lambda key: OWASP_DESCRIPTIONS.get(key, ""),
        "sentence": (
            "OWASP's list names the attack patterns that apply to an agent rather than "
            "to a chatbot. Each case is given the one code whose entry describes the "
            "mechanism of its failure, or Not applicable where no entry does. The code "
            "names are OWASP's. The one-line descriptions are this register's summary, "
            "not OWASP's wording."
        ),
    },
    "rmf": {
        "name": "NIST AI Risk Management Framework 1.0",
        "unit": "subcategory",
        "plural": "subcategories",
        "multi": True,
        "show_zeros": False,
        "rows": lambda: NIST_RMF_ROWS,
        "basis_field": "nist_ai_rmf_basis",
        "catalogue": lambda: list(NIST_RMF_ROWS),
        "values": lambda row: _split(row["nist_ai_rmf"]),
        "label": lambda key: key,
        "meaning": lambda key: NIST_RMF_ROWS.get(key, {}).get("text", ""),
        "sentence": (
            "The framework names the practices an organisation is meant to have in "
            "place. A case is listed under the subcategory whose text names the missing "
            "safeguard."
        ),
    },
    "articles": {
        "name": "Regulation (EU) 2024/1689, the EU AI Act",
        "unit": "article",
        "plural": "articles",
        "multi": True,
        "show_zeros": False,
        "rows": lambda: EU_ARTICLE_ROWS,
        "basis_field": "eu_ai_act_basis",
        "catalogue": lambda: list(EU_ARTICLE_ROWS),
        "values": lambda row: _split(row["eu_ai_act"]),
        "label": _eu_label,
        "meaning": lambda key: "",
        "sentence": (
            "These are the provisions that come closest to the missing safeguard. "
            "Whether an obligation applies depends on the role, the system and the "
            "jurisdiction, so read an article here as a starting point and not as a "
            "finding of law."
        ),
    },
    "monitoring": {
        "name": "NIST AI 800-4, Challenges to the Monitoring of Deployed AI Systems",
        "unit": "category",
        "plural": "categories",
        "multi": False,
        "show_zeros": True,
        "rows": lambda: NIST_800_4_ROWS,
        "basis_field": None,
        "catalogue": lambda: list(NIST_800_4_ROWS),
        "values": lambda row: _split(row["nist_800_4_category"]),
        "label": lambda key: key,
        "meaning": lambda key: NIST_800_4_ROWS.get(key, {}).get("what_it_covers", ""),
        "sentence": (
            "NIST groups what an organisation has to watch for once a system is live. A "
            "case is listed under the kind of monitoring whose absence the record "
            "shows. The category names are NIST's. The one-line descriptions are this "
            "register's summary, not NIST's wording."
        ),
    },
}


def group_header(name, counted, uncounted, meaning="", cls="", style=""):
    """A group label on the same basis as every heading above it.

    It used to print the number of rows in the group, which counted the single-source
    row and so disagreed with the heading and the bar directly above it. It now prints
    the counted figure and carries the not-counted row as a separate mark, in the same
    small style the bars use.
    """
    tail = f"<small> +{uncounted} not counted</small>" if uncounted else ""
    return (
        f'<div class="ghead{cls}"{style}><span class="gname">{esc(name)}</span>'
        f'<span class="gcount">{counted} {"case" if counted == 1 else "cases"}{tail}'
        "</span></div>"
        + (f'<p class="gmean">{esc(meaning)}</p>' if meaning else "")
    )


def category_rows(pairs):
    """One neutral bar per category, with the count printed and empty rows drawn.

    The same shape as the severity rows, without the colour and without the link.
    Nothing here is clickable, because nothing behind it filters, and a row that looks
    like a link and does nothing is worse than a row that looks like a row.
    """
    widest = max([n for _, n, _ in pairs] + [1])
    out = []
    for label, n, extra in pairs:
        bar = (
            f'<span class="sbar" style="width:{100 * n / widest:.2f}%;'
            f'background:{LENS_BAR}"></span>'
        )
        if extra:
            bar += (
                f'<span class="sbar extra" style="width:'
                f'{100 * extra / widest:.2f}%;border-color:{LENS_BAR}"></span>'
            )
        out.append(
            f'<div class="srow"><span class="slabel">{esc(label)}</span>'
            f'<span class="strack">{bar}</span>'
            f'<span class="scount">{n}'
            + (f"<small> +{extra} not counted</small>" if extra else "")
            + "</span></div>"
        )
    return f'<div class="srows lens">{"".join(out)}</div>'


def primary_mapping(spec, row):
    """The one provision this case is counted under, which is the first in its list.

    The order is the rule published on the Method page, and the validator rejects a
    row whose first value is not the one that rule picks, so this is reading a decision
    rather than making one.
    """
    values = spec["values"](row)
    return values[0] if values else ""


def framework_view(frame, slug):
    """One published framework applied to every case, in the same shape for all four.

    The finding as a computed heading, one sentence saying what the framework is, a
    neutral bar for every category, the cases grouped under their category, and a
    source line naming the file the labels were read from. Every label here is the
    framework owner's wording, read from frameworks/, and every count is derived.
    """
    spec = FRAMEWORK_LENSES[slug]
    ratings, _, _ = load_harm_ratings(data_stamp(RATINGS_FILE))
    counted = frame[frame["counted"]]
    uncounted = frame[~frame["counted"]]
    total = len(counted)

    # Every count here is of primary mappings, so a case appears once however many
    # provisions also fit. Before the mapping rule a case with two values was counted
    # under both and the bars added up to more cases than the register holds.
    hits = Counter(primary_mapping(spec, row) for _, row in counted.iterrows())
    extras = Counter(primary_mapping(spec, row) for _, row in uncounted.iterrows())
    hits.pop("", None)
    extras.pop("", None)

    catalogue = spec["catalogue"]()
    seen = set(hits) | set(extras)
    if spec["show_zeros"]:
        order = catalogue + sorted(k for k in seen if k not in catalogue)
    else:
        order = sorted(seen, key=lambda k: (-hits[k], k))
    if not order:
        st.info("No case in this register carries a value from this framework.")
        return

    top = order[0]
    for key in order:
        if hits[key] > hits[top]:
            top = key
    n = hits[top]

    if slug == "owasp":
        st.markdown(
            f"#### {n} of {total} cases fall under {esc(top)}: "
            f"{esc(OWASP_CODES.get(top, ''))}."
        )
        # A description of what is in this register, not a claim about agent failures
        # in general. The opening words say so, and the three codes are computed.
        three = sorted(hits, key=lambda k: (-hits[k], k))[:3]
        st.markdown(
            f"In this register, three patterns ({and_join(three)}) account for "
            f"{sum(hits[k] for k in three)} of {total}."
        )
    elif slug == "rmf":
        st.markdown(f"#### {n} of {total} cases point to {esc(top)}.")
        st.markdown(
            f"{esc(top)} reads: {esc(NIST_RMF_ROWS.get(top, {}).get('text', ''))}"
        )
    elif slug == "articles":
        st.markdown(
            f"#### {esc(_eu_article(top))} is the closest provision in {n} of {total} "
            "cases. None of these systems is confirmed high-risk."
        )
    else:
        st.markdown(f"#### {n} of {total} fall under {esc(top)} monitoring.")
    st.markdown(spec["sentence"])

    st.markdown(f"##### Where the {total} counted cases fall")
    st.markdown(
        category_rows([
            (spec["label"](key), hits[key], extras[key]) for key in order
        ]),
        unsafe_allow_html=True,
    )
    used = [k for k in order if k in catalogue and (hits[k] or extras[k])]
    if spec["show_zeros"]:
        st.caption(
            f"{len(used)} of the {len(catalogue)} {spec['plural']} in the published "
            f"list have a case here. The other "
            f"{count_word(len(catalogue) - len(used))} "
            f"{'is' if len(catalogue) - len(used) == 1 else 'are'} drawn at zero, "
            "because a category with no case is part of the shape."
        )
    else:
        st.caption(
            f"{len(used)} of the {len(catalogue)} {spec['plural']} this register "
            "tracks appear here. The published list is too long to draw in full, so "
            f"the {spec['plural']} with no case are left out rather than drawn at zero."
        )

    st.caption(
        "Each case is counted once, under its primary mapping. Other mappings that fit "
        "are on the case card and counted nowhere. "
        "[How these mappings were made](?screen=Method&rule=mapping)"
    )
    st.markdown(f"##### All {len(frame)} cases, grouped by {spec['unit']}")
    st.markdown(table_controls(), unsafe_allow_html=True)
    for key in order:
        rows = frame[frame.apply(lambda r: primary_mapping(spec, r) == key, axis=1)]
        st.markdown(
            group_header(
                spec["label"](key), hits[key], extras[key], spec["meaning"](key),
                cls=" lens",
            ),
            unsafe_allow_html=True,
        )
        if rows.empty:
            st.markdown(empty_case_table(), unsafe_allow_html=True)
            continue
        st.markdown(
            case_table(rows.sort_values("event_date", ascending=False), ratings=ratings),
            unsafe_allow_html=True,
        )

    table = spec["rows"]()
    src = (
        table.get(_eu_article(top))
        or table.get(top)
        or next(iter(table.values()), {})
    )
    basis_field = spec["basis_field"]
    if basis_field:
        stated = int((counted[basis_field] == "Stated").sum())
        basis = (
            f"All {total} mappings are this register's reading, not the framework "
            "owner's."
            if stated == 0 else
            f"{total - stated} of the {total} mappings are this register's reading. "
            f"{stated} {'is' if stated == 1 else 'are'} applied to the case by the "
            "publication itself."
        )
    else:
        basis = (
            f"All {total} mappings are this register's reading, not NIST's."
        )
    url = src.get("source_url", "")
    host = url.split("/")[2] if "//" in url else url
    # Two of the four files record an edition line that already names the framework,
    # so printing both read as a stutter. The name is added only when it is missing.
    edition = src.get("verified_against", "")
    if not edition:
        lead = spec["name"]
    elif spec["name"].split(",")[0].lower() in edition.lower():
        lead = edition
    else:
        lead = f"{spec['name']}, {edition}"
    st.caption(
        f"Source: {lead}, read from [{host}]({url}) on {src.get('retrieved', '')}. "
        f"{basis}"
    )
    how_to_read(
        "A greyed row rests on a single source, so it is shown in its group and left "
        "out of every figure, including the dashed part of a bar."
    )


def lens_picker(group, key):
    """The selector both Findings tabs carry, with the choice kept in the URL.

    Written on change rather than on every run. Both tabs render on every run, so two
    selectors writing the same parameter on every run would fight over it and the
    reader would be moved back to whichever ran last.
    """
    slugs = LENS_BAD if group == "bad" else LENS_KIND
    labels = [LENS_LABEL[s][0] for s in slugs]
    asked = st.query_params.get("lens")

    def remember():
        st.query_params["lens"] = slugs[labels.index(st.session_state[key])]

    with st.container(key=f"lenspick-{group}"):
        chosen = st.radio(
            "View the cases through",
            labels,
            captions=[LENS_LABEL[s][1] for s in slugs],
            horizontal=True,
            index=slugs.index(asked) if asked in slugs else 0,
            key=key,
            on_change=remember,
        )
    return slugs[labels.index(chosen)]


def tab_what_kind(frame):
    """What sort of failure it was, through the register's classes or four frameworks."""
    lens = lens_picker("kind", "lens_kind")
    if lens == "classes":
        tab_what_was_missing(frame)
    else:
        framework_view(frame, lens)


def tab_how_severe(frame):
    """Every case, measured against whichever of the two harm frameworks is picked."""
    ratings, _, _ = load_harm_ratings(data_stamp(RATINGS_FILE))
    definitions = load_mit_framework(data_stamp(MIT_FRAMEWORK_FILE))
    harms = list(definitions["harm_type"].drop_duplicates())

    mit = lens_picker("bad", "lens_bad") == "mit"

    # The harm filter reads the MIT ratings file, so it belongs to the MIT view alone.
    # On the EU view it filtered the cases by a dimension the EU test does not use.
    chosen_harms = []
    if mit:
        with st.container(key="harmpick"), st.popover(
            "Filter by type of harm", icon=":material/filter_list:", width="content"
        ):
            chosen_harms = st.pills(
                "Harm types", harms, selection_mode="multi", default=[],
                label_visibility="collapsed",
            )
    view = frame
    if chosen_harms:
        ids = set(ratings[ratings["harm_type"].isin(chosen_harms)]["case_id"])
        view = view[view["id"].isin(ids)]
    counted = view[view["counted"]]
    uncounted = view[~view["counted"]]
    n = len(counted)

    # The heading is the finding, so it has to be built from the data every time.
    if mit:
        middle = int((counted["mit_level"] == 3).sum())
        st.markdown(
            f"#### No case reached the top two levels of harm. {middle} reached the middle."
        )
        st.markdown(
            "On MIT's five-level scale, built to rank AI harm up to global catastrophe, "
            "the worst case here is Substantial. The lesson is in how the harm happened: "
            "the same missing safeguards could allow far larger harm in a bigger "
            "deployment."
        )
    else:
        meets = int((counted["eu_serious_incident"] == "Meets").sum())
        nd = int(
            (counted["eu_serious_incident"] == "Not determinable from the record").sum()
        )
        st.markdown(
            f"#### {meets} of {n} cases clearly meet the EU's serious-incident test. "
            f"{nd} can't be judged from the public record."
        )
        st.markdown(
            "Article 3(49) of the EU AI Act defines a serious incident. This is the "
            "register's reading of the closest part of that definition, not a legal "
            "classification. Where a published account does not settle it, the register "
            "says so rather than guessing."
        )

    active_level = st.query_params.get("level") if mit else None

    def level_link(name):
        parts = ["screen=Findings"]
        if active_level != name:
            parts.append(f"level={quote_plus(name)}")
        return "?" + "&".join(parts)

    if mit:
        st.markdown(f"##### Where the {n} cases fall on MIT's scale")
        st.markdown(
            severity_rows(counted, uncounted, active_level, level_link),
            unsafe_allow_html=True,
        )
        st.caption("Click a level to show only those cases.")
        st.markdown(
            '<p class="legend">'
            + ("".join(
                f'<span>{esc(MIT_LEVELS[l])}: {esc(MIT_SEVERITY_MEANING[l])}</span>'
                for l in MIT_ORDER
            ))
            + "</p>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Summarised from MIT's table. The full table, five levels across ten harm "
            "types with MIT's own wording, is on the Method page."
        )

    if not len(uncounted) == 0:
        ids = ", ".join(sorted(uncounted["id"]))
        st.caption(
            f"{ids} is shown but not counted: it rests on a single source."
            if len(uncounted) == 1 else
            f"{ids} are shown but not counted: they rest on a single source."
        )

    if view.empty:
        st.info("No cases affect that harm type. [Show every case](?screen=Findings)", icon="🔍")
        return

    # One level selected shows that level alone. Otherwise every case, grouped.
    if active_level:
        rows = view[view["mit_level"].map(MIT_LEVELS) == active_level]
        st.markdown(
            f"##### {len(rows)} case{'s' if len(rows) != 1 else ''} rated "
            f"{esc(active_level)}  ·  [Show every level](?screen=Findings)"
        )
        st.markdown(table_controls(), unsafe_allow_html=True)
        st.markdown(
            case_table(rows.sort_values("event_date", ascending=False), ratings=ratings),
            unsafe_allow_html=True,
        )
    else:
        label = "severity" if mit else "the EU test"
        st.markdown(f"##### All {len(view)} cases, grouped by {label}")
        st.markdown(table_controls(), unsafe_allow_html=True)
        if mit:
            groups = [
                (MIT_LEVELS[l], MIT_SEVERITY_MEANING[l],
                 view[view["mit_level"] == l], MIT_SLUG[l])
                for l in MIT_ORDER
            ]
        else:
            groups = [
                (v, EU_GROUP_MEANING[v], view[view["eu_serious_incident"] == v], None)
                for v in ("Meets", "Does not meet", "Not determinable from the record")
            ]
        for name, meaning, rows, slug in groups:
            in_group = int(rows["counted"].sum())
            out_group = len(rows) - in_group
            tint = f' style="border-left:6px solid var(--sev-{slug})"' if slug else ""
            st.markdown(
                group_header(name, in_group, out_group, meaning, style=tint),
                unsafe_allow_html=True,
            )
            if rows.empty:
                st.markdown(empty_case_table(), unsafe_allow_html=True)
                continue
            st.markdown(
                case_table(rows.sort_values("event_date", ascending=False), ratings=ratings),
                unsafe_allow_html=True,
            )

    how_to_read(
        "'At least' means the record doesn't establish the full size of the harm, so the "
        "rating is the lowest level the record supports. A greyed row rests on a single "
        "source, so it is shown here and left out of every figure."
    )


def tab_what_the_record_shows(frame):
    facts = headline(frame)

    counted = frame[frame["counted"]]
    # Derived from the source label, not listed by hand. The typed list said four and
    # named AIR-015, whose primary record is a build tool maintainer's advisory, so the
    # sentence also called Nx an AI company. The field supports a narrower and stronger
    # claim: the primary record is the implicated organisation's own account.
    own_report, uncorroborated = own_account_rows(counted)

    with_review = facts["total"] - facts["no_review_recorded"]
    review_clause = (
        "In none does it say when the agent would be reviewed."
        if with_review == 0 else
        f"In only {with_review} of {facts['total']} does it say when the agent would be "
        "reviewed."
    )
    st.markdown(
        f"#### In {facts['no_stop_authority_recorded']} of {facts['total']} cases, the "
        f"record doesn't say who could stop the agent. {review_clause}"
    )
    st.markdown(
        "Neither figure says nobody could have stopped it, and neither says nobody ever "
        "looked. They say the published account does not answer the question, and a "
        "safeguard nobody can name is one a reader cannot check. For your own agent, "
        "write down who can switch it off and the date you will next review it."
    )
    st.markdown("**How much of this register another index already holds.**")
    in_aiid = sorted(frame[frame["aiid_id"] != ""]["id"])
    not_in = sorted(frame[frame["aiid_id"] == ""]["id"])
    checked = sorted(frame["aiid_checked_on"])[-1] if len(frame) else ""
    st.markdown(
        f"{len(in_aiid)} of the {len(frame)} cases here are also in the AI Incident "
        f"Database. {len(not_in)} "
        + ("is" if len(not_in) == 1 else "are")
        + f" not, as of {checked}"
        + (f" ({and_join(not_in)})" if not_in else "")
        + ". Each match was opened and read rather than taken from a search result, and "
        "an absence is recorded as nothing found rather than as nothing there. That "
        "database is on this register's aggregator list, so it is how cases are found "
        "and never what a claim rests on."
    )
    st.markdown("**Where the newest cases came from is itself a finding.**")
    # The Limits page says three rows rest on one party's account. Read next to this
    # sentence the two numbers look like they disagree, so the subset is named here.
    if len(uncorroborated) > 1:
        subset = (
            f", of which {len(uncorroborated)} have no corroboration beyond restatement "
            "(see Limits)"
        )
    elif uncorroborated:
        subset = (
            f", of which {uncorroborated[0]} has no corroboration beyond restatement "
            "(see Limits)"
        )
    else:
        subset = ""
    st.markdown(
        f"In {len(own_report)} of the {facts['total']} counted cases the primary record "
        "is the implicated organisation's own published account of what happened. They "
        f"are {and_join(own_report)}{subset}. Several are AI companies or an AI "
        "evaluation body, which run threat intelligence teams and publish what they "
        "find. Most organisations do neither."
    )
    st.markdown(
        "So the failures that exist on paper are the ones the best instrumented "
        "organisations chose to write up. Agent failures inside ordinary companies are "
        "almost certainly more common, and none of them are here. Read every count in "
        "this register as a count of what was documented, not of what happened."
    )
    corrections = [
        ("A database and its backups were destroyed, newest copy three months old",
         "The platform published a postmortem saying the data was recovered two and a "
         "half days later"),
        ("An eating disorder helpline was shut",
         "The number was taken over by another charity and still reaches therapists"),
        ("A regulator's settlement terms, with no mention of the company's response",
         "The company denied wrongdoing"),
    ]
    st.markdown("**Three corrections an earlier version of this register needed**")
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr>'
        "<th>What an earlier version of this register said</th>"
        "<th>What the record shows</th></tr></thead><tbody>"
        + "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in corrections)
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    how_to_read(
        "Every one of those omissions made the deployer look worse than the record "
        "supports. They were this register's errors, not a source's."
    )

    st.markdown("")
    st.markdown("#### How completely is each ending known?")
    st.markdown(
        f"**{facts['aftermath_documented']} of {facts['total']} counted cases have a "
        f"fully documented ending.** {facts['aftermath_partial']} stop part way and "
        f"{facts['aftermath_undocumented']} has no recorded ending at all."
    )
    how_to_read(
        "A register built from public sources will tend to overstate harm rather than "
        "understate it, because the destruction is news and the recovery is a postmortem "
        "nobody aggregated. Each card says when its record stops early."
    )

    st.markdown("")
    st.markdown("#### What do deployment records contain?")
    st.markdown(
        f"**In {facts['no_review_recorded']} of {facts['total']}, the record does not say "
        "whether any date was set to re-examine the agent.**"
    )
    deploy = [
        ("anyone reviewed the agent's behaviour before launch", facts["no_evidence_recorded"]),
        ("any role could halt or roll back the deployment", facts["no_stop_authority_recorded"]),
        ("any date was set to re-examine it", facts["no_review_recorded"]),
    ]
    st.markdown(f"**What the record is silent about, across {facts['total']} counted cases**")
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr>'
        "<th>Does the public record say whether...</th><th>Silent</th></tr></thead><tbody>"
        + "".join(
            f'<tr><td>{esc(q)}</td><td style="text-align:right">{n} of {facts["total"]}</td></tr>'
            for q, n in deploy
        )
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    how_to_read(
        "Statements about the record, not about the deployers. This register does not "
        "claim that any organisation set no review date, only that the record does not "
        "say. Every row defaults to not disclosed, and both yes and no require a source."
    )

    st.markdown("")
    st.markdown("#### How much of this is the register's own judgement?")
    st.markdown(
        f"**{facts['basis_stated'] + facts['basis_entailed']} of {facts['total']} do not "
        "rest on this register's opinion.**"
    )
    tiers = [
        ("Stated", facts["basis_stated"], "The deployer, a regulator or a ruling said it."),
        ("Entailed", facts["basis_entailed"],
         "It follows from the record. A control added afterwards is evidence of its prior absence."),
        ("Our reading", facts["basis_reading"],
         "Neither. This is judgement, and it is labelled as such on the card."),
    ]
    st.markdown("**Where the register's own judgement enters, and where it does not**")
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr>'
        "<th>How the register knows</th><th>Cases</th><th>What it means</th>"
        "</tr></thead><tbody>"
        + "".join(
            f'<tr><td>{esc(n)}</td><td style="text-align:right">{c} of {facts["total"]}</td>'
            f"<td>{esc(d)}</td></tr>"
            for n, c, d in tiers
        )
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    how_to_read(
        "Naming the missing control is the only place this register makes a claim about a "
        "company that the company did not make about itself, so it is the only field that "
        "carries this. The test and signal columns are recommendations to the reader."
    )

    with st.expander("Why it matters"):
        st.markdown(
            "Primary records exist mainly for legal and security events: rulings, CVEs, "
            "threat intelligence reports, enforcement notices. A chatbot that quietly "
            "gave wrong answers for a year produces no document at all. A security "
            "vendor's catalogue of agent failures is mostly security failures. And "
            "searching for these cases returns a large volume of generated write-ups with "
            "nothing behind them. Every register of AI incidents, this one included, is a "
            "map of the documentation regime rather than a map of the harm."
        )


def screen_findings(frame):
    st.title("Findings")
    st.markdown(
        f"What {len(frame)} documented incidents show, measured against recognised "
        "frameworks."
    )
    severe, kind, record = st.tabs([HOW_BAD_TAB, WHAT_KIND_TAB, "Gaps in the record"])
    with severe:
        tab_how_severe(frame)
    with kind:
        tab_what_kind(frame)
    with record:
        tab_what_the_record_shows(frame)
    st.markdown("")
    st.caption(
        "Every figure on this page is calculated from the register's data, never typed "
        "in by hand."
    )


def incident_card(row):
    """One record, in four tabs.

    Eight rounds of review each added a field, and nothing was watching the total. The
    flat version carried thirty-two fields and six coloured boxes in a single scroll,
    which is unreadable however correct each line is. So the story is always visible and
    the governance detail sits behind tabs, where a reader who wants it can find it and a
    reader who does not is not made to scroll past it.

    The repeated definitions went to the Method page. They were the same words on every
    card, twelve times over.
    """
    st.markdown(
        tag(row["id"])
        + tag(row["incident_or_hazard"])
        + severity_pill(row["mit_level"], row["mit_floored"])
        + tag(f"Missing control: {row['control_class']}")
        + tag(f"Evidence grade {row['evidence_grade']}")
        + (tag("Facts disputed by the deployer") if row["disputed"] == "Yes" else "")
        + (tag("Not counted in any number") if not row["counted"] else "")
        + (tag("Included before the inclusion rule")
           if row["inclusion"] == "Included before the inclusion rule" else ""),
        unsafe_allow_html=True,
    )
    st.markdown(
        f"**{esc(row['deployer'])}** · {esc(row['sector'])} · {esc(row['agent_type'])} "
        f"· {esc(row['event_date'])}"
    )

    happened, missing, test, evidence, aftermath = st.tabs(
        ["What happened", "What was missing", "Test before launch", "Evidence", "Aftermath"]
    )

    with happened:
        st.markdown(esc(row["what_happened"]))
        st.markdown(f"**Why this is in the register.** {esc(row['why_in_register'])}")
        granted = ", ".join(part for part in row["authority"].split("|") if part)
        st.markdown(
            f"**The agent could:** {esc(granted)}.  \n"
            f"**A person approved first:** {esc(row['human_approval'])}."
        )
        st.markdown(
            f"**Harm fell on.** {esc(row['harm_borne_by'])}  \n"
            f"**Could have prevented it.** {esc(row['could_have_prevented'])}"
        )

    with aftermath:
        st.markdown(esc(row["what_changed_after"]))
        if row["aftermath_status"] != "Documented":
            st.markdown(
                f":orange[**The ending is {row['aftermath_status'].lower()}.** The public "
                "record stops before this story does. Read the harm above as what was "
                "reported, not as what finally happened.]"
            )
        if row["disputed"] == "Yes":
            st.markdown(
                ":orange[**The facts here are disputed.** The deployer's own position is "
                "in the paragraph above and in the second source.]"
            )
        if row["aftermath_source_url"]:
            st.caption(f"[The source for this]({row['aftermath_source_url']}).")

    with missing:
        directed_tier = row["directed_by_basis"].split(".")[0].strip()
        st.markdown(
            f"**Who directed the agent: {row['directed_by']}.** "
            f"{DIRECTED_MEANING[row['directed_by']]}\n\n"
            f"{esc(row['directed_by_basis'])}"
        )
        st.markdown("")
        tier = row["missing_control_basis"].split(".")[0].strip()
        st.markdown(
            f"**State it was in: {MATURITY_LABEL[row['control_maturity']]}.** "
            f"{MATURITY_MEANING[row['control_maturity']]}\n\n"
            f"**How the register knows: {tier}.** "
            f"{esc(row['missing_control_basis'].split('.', 1)[1].strip())}"
        )
        basis = row["owasp_code_basis"]
        mark = (
            ", applied to this case by OWASP's own list"
            if basis == "Stated"
            else ", this register's reading"
        )
        st.caption(
            f"Failure pattern: {esc(row['failure_pattern'])}. OWASP "
            f"{row['owasp_code']}, {OWASP_CODES[row['owasp_code']]}{mark}."
        )

    with test:
        st.markdown(
            f"**Test before launch.** {esc(row['test_before_launch'])}\n\n"
            f"**Pass mark.** {esc(row['test_pass_mark'])}\n\n"
            f"**Signal after launch.** {esc(row['signal_after_launch'])}"
        )
        st.caption(
            f"Monitoring category, NIST AI 800-4: {esc(row['nist_800_4_category'])}. "
            f"Runs the control: {esc(row['control_owner_role'])}. Answers when it fails: "
            f"{esc(row['accountable_role'])}."
        )
        if row["id"] in RUNNABLE_TESTS:
            path, cls = RUNNABLE_TESTS[row["id"]]
            st.success(
                f"**This one runs.** `{path}` · `{cls}`\n\n"
                "`python3 -m unittest discover tests`",
                icon="🧪",
            )

    with evidence:
        rows_md = []
        for label, answer_field, source_field in (
            ("Someone reviewed its behaviour first", "deploy_evidence_seen", "deploy_evidence_source"),
            ("A role could halt or roll it back", "deploy_stop_authority", "deploy_stop_authority_source"),
            ("A date was set to look at it again", "deploy_review_date", "deploy_review_date_source"),
        ):
            link = f" [source]({row[source_field]})" if row[source_field] else ""
            rows_md.append(f"| {label} | {row[answer_field]}{link} |")
        st.markdown(
            "**Does the public record say whether...**\n\n"
            "| | |\n| --- | --- |\n" + "\n".join(rows_md)
        )
        st.caption("Not disclosed means the record is silent, not that the thing was missing.")
        st.markdown(f"**Grade {row['evidence_grade']}.** {GRADE_MEANING[row['evidence_grade']]}")
        st.markdown(f"1. [{esc(row['source_1_label'])}]({row['source_1_url']})")
        if row["source_2_url"]:
            st.markdown(f"2. [{esc(row['source_2_label'])}]({row['source_2_url']})")
        archives = [a for a in row.get("archive_urls", "").split() if a]
        if archives:
            links = ", ".join(f"[{i}]({a})" for i, a in enumerate(archives, start=1))
            st.caption(
                f"Checked {row['date_checked']}. Archived copies: {links}. Some publishers "
                "block automated access, so an archived copy may be the one that opens."
            )
        else:
            st.caption(f"Checked {row['date_checked']}. No archived copy yet.")
        st.markdown(
            f"**Closest clauses.** NIST AI RMF {esc(row['nist_ai_rmf'])} · "
            f"EU AI Act {esc(row['eu_ai_act'])}"
        )
        st.caption(
            "Closest clause, not a legal classification."
        )


# Every finding is a filter, and every filter is a link that can be posted on its own.
# The predicates are the single source for the card numbers and the filtering, so a card
# saying 10 and a table showing 9 is not a state this can reach.
#
# "Record silent" is the wording throughout, never "nobody could". The field says the
# public record does not say. Turning that into a claim about the deployer is the same
# error as coding a sourceless No.
#
# There were two FINDINGS dicts here until 12 October 2026. The first carried the tile
# text from before the layout pass and was silently overwritten by this one, so editing
# it changed nothing on the page.
FINDINGS = {
    "no-false-statement": {
        "heading": "{n} cases where the agent said nothing untrue",
        "chip": "Said nothing untrue",
        "test": lambda r: r["said_something_untrue"] == "No",
    },
    "record-silent-on-stop": {
        "heading": "{n} cases where the record doesn't say who could have halted the deployment",
        "chip": "Record silent on who could stop it",
        "test": lambda r: r["deploy_stop_authority"] == "Not disclosed",
    },
    "control-never-built": {
        "heading": "{n} cases where the safeguard was never built",
        "chip": "Control never built",
        "test": lambda r: r["control_maturity"] == "Absent",
    },
    "control-did-not-hold": {
        "heading": "{n} cases where the safeguard existed and did not hold",
        "chip": "Control existed, did not hold",
        "test": lambda r: r["control_maturity"] == "Implemented",
    },
    # Added 12 October 2026 when the register reached 20 counted cases and the three
    # cards were re-picked on what the data now supports.
    "not-accuracy": {
        "heading": "{n} cases where the missing safeguard was not accuracy",
        "chip": "Missing control was not accuracy",
        "test": lambda r: r["control_class"] != "Accuracy",
    },
    "no-review-date": {
        "heading": "{n} cases with no date set to look at the agent again",
        "chip": "No date set to look again",
        "test": lambda r: r["deploy_review_date"] == "Not disclosed",
    },
    "not-attacker": {
        "heading": "{n} cases with no attacker involved",
        "chip": "Not attacker misuse",
        "test": lambda r: r["directed_by"] != "Attacker",
    },
}


def finding_counts(frame):
    """How many counted cases each finding covers. Computed, never typed."""
    counted = frame[frame["counted"]]
    return {
        key: int(counted.apply(spec["test"], axis=1).sum())
        for key, spec in FINDINGS.items()
    }


def screen_home(frame):
    """Home is the register. The case list used to be a second page showing the same
    twelve rows under a second set of headline numbers, which meant a reader met the
    findings twice before reaching a case."""
    facts = headline(frame)
    counts = finding_counts(frame)
    total = facts["total"]

    years = sorted(frame["event_date"].str.slice(0, 4))
    st.markdown(
        '<div class="hero-band">'
        "<h1>AI Agent Incident Register</h1>"
        '<p class="tagline">A public record of AI agents that caused harm, and the '
        "safeguard that was missing in each case.</p>"
        f'<p class="fact"><span>{facts["all_rows"]} documented incidents, {years[0]}'
        f'&ndash;{years[-1]}</span><span>{facts["total"]} with strong enough evidence '
        "to count</span></p>"
        '<p class="def">An AI agent here means a system that takes actions (runs code, '
        "changes data, sends, buys, posts), not one that only answers.</p></div>",
        unsafe_allow_html=True,
    )

    st.markdown("## What the cases show")
    st.markdown(
        "None of these failures was only the AI being wrong. Every one needed the agent "
        "to be allowed to act."
    )

    # Re-picked on 12 October 2026, at 20 counted cases, and rewritten on 13 October so
    # each card states the finding before the number. The whole row is one grid so the
    # three cards match in height and their buttons line up.
    by_class = Counter(frame[frame["counted"]]["control_class"])
    cards = [
        ("not-accuracy",
         "The missing safeguard wasn't about accuracy.",
         f"In {by_class['Authority']} cases the agent could do more than its task needed. "
         f"In {by_class['Boundary']} it obeyed instructions hidden in content it was "
         f"reading. Only {by_class['Accuracy']} came down to a false statement.",
         f"Even if every case with a false statement is counted as an accuracy failure, "
         f"it is still {facts['accuracy_first']} of {total}."),
        ("record-silent-on-stop",
         "The public record doesn't say who could have stopped it.",
         "That doesn't mean no one could, only that no published account names them. None "
         f"of the {total} records a date to review the agent again. Could you name both "
         "for your own agent?",
         None),
        ("not-attacker",
         "No attacker was involved.",
         "The harm came from normal use, or from the agent doing what its own organisation "
         "set it up to do. Most failures here weren't attacks. They came from how the "
         "agent was deployed.",
         None),
    ]
    blocks = []
    for key, say, more, note in cards:
        n = counts[key]
        blocks.append(
            f'<div class="fcard"><div class="big">{n}<small>of {total}</small></div>'
            f'{dots(n, total)}<p class="say">{esc(say)}</p>'
            f'<p class="more">{esc(more)}</p>'
            + (f'<p class="note">{esc(note)}</p>' if note else "")
            + f'<div class="cardbtn"><a href="?view={key}" target="_self">'
            f"Show these {n}</a></div></div>"
        )
    st.markdown(f'<div class="cards">{"".join(blocks)}</div>', unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### Filter the cases")
        classes = st.multiselect("Missing control", sorted(frame["control_class"].unique()))
        severities = st.multiselect(
            "Harm severity (MIT)",
            [MIT_LEVELS[l] for l in MIT_ORDER if l in set(frame["mit_level"])],
        )
        grades = st.multiselect("Evidence grade", sorted(frame["evidence_grade"].unique()))
        directed = st.multiselect(
            "Who directed the agent",
            [v for v in ("Deployer", "Attacker", "No one") if v in set(frame["directed_by"])],
        )
        query = st.text_input("Search", placeholder="Case, deployer, pattern")
        counted_only = st.checkbox("Counted cases only (grade A and B)", value=False)

    # The finding filters live in the URL so a filtered view stays shareable, even though
    # the chips that used to set them are gone.
    chosen = [k for k in st.query_params.get_all("view") if k in FINDINGS]

    show_uncounted = st.query_params.get("c") == "1"

    view = frame
    for key in chosen:
        view = view[view.apply(FINDINGS[key]["test"], axis=1)]
    # A card says "17 of 20", and 20 is the counted rows. Its button therefore has to
    # land on 17 rows, not on 18 with a grade C row quietly making up the difference.
    uncounted_matches = int((~view["counted"]).sum()) if chosen else 0
    if chosen and not show_uncounted:
        view = view[view["counted"]]
    if classes:
        view = view[view["control_class"].isin(classes)]
    if severities:
        view = view[view["mit_level"].map(MIT_LEVELS).isin(severities)]
    if grades:
        view = view[view["evidence_grade"].isin(grades)]
    if directed:
        view = view[view["directed_by"].isin(directed)]
    if counted_only:
        view = view[view["counted"]]
    if query:
        needle = query.lower()
        columns_to_search = [
            "id", "title", "deployer", "failure_pattern", "control_class", "directed_by",
        ]
        view = view[view[columns_to_search].apply(
            lambda r: needle in " ".join(r).lower(), axis=1
        )]
    # Newest first. A register reads as a timeline, and the most recent case is the
    # one a reader is most likely to recognise.
    view = view.sort_values("event_date", ascending=False)

    st.markdown("---")
    if chosen:
        heading = " and ".join(
            FINDINGS[k]["heading"].format(n=len(view)) for k in chosen
        )
        denominator = f"{facts['total']} counted cases"
    else:
        heading = f"All {len(view)} cases"
        denominator = f"{len(frame)} cases"
    st.markdown(f"#### {esc(heading)}")

    left, middle, right = st.columns([3, 1, 1])
    left.markdown(f"**Showing {len(view)} of {denominator}**")
    middle.link_button("Code and data on GitHub", REPO_URL, width="stretch")
    right.download_button(
        "Download the data", data=DATA_FILE.read_bytes(),
        file_name="ai_agent_incident_register.csv", mime="text/csv",
        on_click="ignore", width="stretch",
    )
    if chosen and uncounted_matches and not show_uncounted:
        plural = "case matches" if uncounted_matches == 1 else "cases match"
        st.caption(
            f"{uncounted_matches} more {plural} but "
            + ("is" if uncounted_matches == 1 else "are")
            + " grade C and not counted. ["
            + ("Show it" if uncounted_matches == 1 else "Show them")
            + f"]({_home_link(chosen, show_uncounted=True)})"
        )
    if chosen:
        st.caption(
            "Filtered by: " + ", ".join(FINDINGS[k]["chip"] for k in chosen)
            + ". [Clear](?)"
        )

    if view.empty:
        st.info("No cases match these filters. [Clear them](?) and try again.", icon="🔍")
        return


    ratings_for_cards, _, _ = load_harm_ratings(data_stamp(RATINGS_FILE))

    # 32. The same cases, with the columns an organisation's own register carries. The
    # choice is in the URL so the view can be linked to, and written on change rather
    # than on every run for the same reason the lens selectors are.
    PUBLIC = "Public register"
    INTERNAL = "As an organisation's own register"
    options = [PUBLIC, INTERNAL]
    asked = INTERNAL if st.query_params.get("register") == "internal" else PUBLIC

    def remember_register():
        if st.session_state["register_view"] == INTERNAL:
            st.query_params["register"] = "internal"
        elif "register" in st.query_params:
            del st.query_params["register"]

    # The URL is the only state this toggle has. Without this line the widget's own
    # session state outlives the parameter, so a reader who looked at the internal view
    # once kept arriving back in it. Public is what an arrival shows unless the link
    # asks for the other one.
    st.session_state["register_view"] = asked
    with st.container(key="regpick"):
        chosen_view = st.radio(
            "Show these cases as",
            options,
            horizontal=True,
            key="register_view",
            on_change=remember_register,
        )
    internal = chosen_view == INTERNAL

    if internal:
        empty, cells, filled, partly = internal_summary(view)
        st.markdown(
            f"Same {len(view)} cases, with the columns an organisation's own incident "
            "register carries. The dotted columns are filled at intake, during response "
            "and at closure, from logs, tickets and the people involved. No public "
            "source can fill them, so they are shown empty. Corrective action is the one "
            "exception: the public record sometimes carries it. "
            "[What else changes inside an organisation](?screen=Method&rule=enterprise)"
        )
        st.markdown(
            '<p class="ilegend"><span class="key solid"></span>Solid, known from the '
            'public record<span class="key dotted"></span>Dotted, only an '
            "organisation's own register can fill this</p>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Sorted by event date, newest first. IDs show the order cases were added."
        )
        st.markdown(
            table_controls()
            + internal_table(
                view, ratings=ratings_for_cards, open_id=open_case_once(view["id"])
            ),
            unsafe_allow_html=True,
        )
        st.caption(
            f"{empty} of {cells} internal-register cells are empty. The public record "
            f"fills {filled} fully and {partly} partly, all in one column."
        )
        st.caption(
            "This is the structure an internal register adds, not a claim about how any "
            "of these organisations ran their own response."
        )
    else:
        st.markdown(
            table_controls()
            + case_table(
                view, ratings=ratings_for_cards, open_id=open_case_once(view["id"])
            ),
            unsafe_allow_html=True,
        )

    st.caption(
        "Click any row to open its full record in place. Colour means one thing here: how "
        "severe the harm was, on MIT's scale. Every pill carries the word and a bar meter "
        "too. Grade A is filled, B outlined, C dashed."
    )

    st.markdown("---")
    foot = st.columns(3)
    foot[0].caption(
        f"Version {VERSION} · Last reviewed: {UPDATED} · Built by Sana Asif Ahmad"
    )
    foot[1].caption(
        "Every number is computed from data/incidents.csv and "
        "data/case_harm_ratings.csv, and uses grade A and B rows only."
    )
    foot[2].caption(
        "Not legal advice and not a compliance assessment. Use it to generate questions "
        "about your own system, not conclusions about somebody else's."
    )




def _articles_used(frame):
    """The EU articles the register actually cites, in the rule's own order.

    Typed as a list of seven until 14 October 2026, which went stale the moment the
    recode added two and is the exact failure the computed-numbers rule exists to stop.
    """
    seen = set()
    for value in frame["eu_ai_act"]:
        for ref in (v.strip() for v in str(value).split(",") if v.strip()):
            seen.add(rules_check.EU_RANK.get(ref, (9, 0)) + (ref,))
    ordered = [ref for *_, ref in sorted(seen)]
    numbers = [r.replace("Article ", "") for r in ordered]
    return "Articles " + and_join(numbers)


def _leads():
    """Leads checked and not included, and the number since reconsidered.

    Counted from the status column rather than from the row count, because a row that
    was reconsidered and admitted stays in the file with its reasoning. Dropping it
    would hide the mistake, and counting it as a rejection would misstate the total.
    """
    path = Path(__file__).parent / "data" / "leads" / "considered_not_included.csv"
    with open(path, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    reconsidered = [r for r in rows if r.get("status", "").startswith("Reconsidered")]
    return len(rows) - len(reconsidered), len(reconsidered)


def screen_method(frame):
    st.title("Method")
    st.markdown(f"Version {VERSION}, last updated {UPDATED}. Single coder.")
    st.markdown(
        "This page is the argument for trusting the register, and the fastest way through "
        "it is to start with what it cannot do. **Limits**, below, names them: the sample "
        "is biased along the same axis the headline measures, one person coded every row, "
        "and the secondary class has no rubric. The **change log** at the bottom records "
        "every correction, including the ones that went against this project. If you only "
        "read two things here, read those."
    )

    st.markdown("### What counts as a case")
    st.markdown(
        "> A case where an AI system that could act or make promises for an organisation "
        "caused harm or a near miss in real use.\n\n"
        "Three parts of that sentence do the work. **Act or make promises** keeps out "
        "systems that only produce text for a person to check. **For an organisation** "
        "keeps out individuals experimenting on their own. **In real use** keeps out "
        "laboratory demonstrations, with one exception noted below."
    )
    st.markdown(
        "The one exception is a demonstrated vulnerability in a widely deployed agent, "
        "recorded as a hazard rather than an incident. A zero-click data exfiltration path "
        "in an assistant with access to a company's mail and files is a control failure "
        "whether or not anyone is known to have used it."
    )

    st.markdown("### Two kinds of count, and which is which")
    st.markdown(
        f"**Descriptive counts** describe what is in the register and cover all "
        f"{len(frame)} rows, including the grade C one. **Analytical counts** are any "
        f"number used to support a claim, and those use only the {int(frame['counted'].sum())} "
        "grade A and grade B rows. Every table below says which it is. The validator "
        "enforces three things on this: that the function producing the headline filters "
        "to counted rows, that the two sets of figures genuinely differ so the rule is not "
        "doing nothing, and that the order-independent floor never exceeds the "
        "ordered-rubric count."
    )

    st.markdown("### Which cases get in")
    st.markdown(
        "Dated 11 October 2026 and committed before any case was added under it. A lead "
        "is included only if it passes all six tests."
    )
    tests = [
        ("1. Agent action", "An AI agent took an action, a tool call, a data change or deletion, a send, a purchase, a post, or made a commitment binding an organisation. Not output that nobody acted on. Not robotics or vehicles."),
        ("2. Harm", "Actual harm, or a near miss confirmed by the organisation."),
        ("3. Organisation", "At least one named organisation, deployer, platform or vendor, whose control failed. Personal use only is excluded."),
        ("4. Evidence", "Grade A or B: a primary record, meaning a postmortem, advisory, CVE, ruling, regulator notice or company statement, plus one independent report."),
        ("5. Traceable", "The record describes the sequence well enough to name the missing control."),
        ("6. Window", "Event and publication both between 1 January 2025 and 30 September 2026, and not already in the register."),
    ]
    st.markdown(
        '<div class="case-table-wrap"><table class="cases"><thead><tr><th>Test</th>'
        "<th>What it asks</th></tr></thead><tbody>"
        + "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in tests)
        + "</tbody></table></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "**Census, not selection.** Every lead that passes is included. The inclusion "
        "decision never looks at a case's missing-control class, its severity or whether "
        "the agent said something untrue, because those are the things the findings "
        "count. They are coded after a case is in."
    )
    pre = int((frame["inclusion"] == "Included before the inclusion rule").sum())
    st.markdown(
        f"**{pre} of the {len(frame)} cases predate this rule** and are marked *Included "
        "before the inclusion rule* on their cards. A rule written after the fact cannot "
        "be claimed to have governed the cases that came first. Every lead that was "
        "checked and not admitted is listed in data/leads/considered_not_included.csv "
        "with the test it failed, so the shape of what the evidence rule excluded can be "
        "seen rather than guessed at."
    )
    # A reconsidered lead stays in the file with its original reasoning and the
    # correction. Deleting it would hide a rejection this register got wrong.
    st.caption(
        f"{_leads()[0]} leads not included. "
        f"{_leads()[1]} "
        + ("lead" if _leads()[1] == 1 else "leads")
        + " reconsidered and included, kept in the table with the reasoning that "
        "rejected "
        + ("it" if _leads()[1] == 1 else "them")
        + " and the correction."
    )

    st.markdown("### Incident or hazard")
    for kind, meaning in KIND_MEANING.items():
        count = int((frame["incident_or_hazard"] == kind).sum())
        counted_count = int(((frame["incident_or_hazard"] == kind) & frame["counted"]).sum())
        st.markdown(f"- **{kind}** ({describe_count(count, counted_count)}). {meaning}")
    st.caption(
        "Descriptive. These follow the OECD AI Incidents and Hazards Monitor definitions."
    )

    st.markdown("### Evidence grades")
    st.markdown(
        "Only grade A and grade B rows feed a number anywhere on this site. That rule is "
        "enforced by the validator, not by me remembering it."
    )
    grade_rows = []
    for grade, meaning in GRADE_MEANING.items():
        grade_rows.append({
            "Grade": grade,
            "Rows": int((frame["evidence_grade"] == grade).sum()),
            "Counted": "Yes" if grade in COUNTED_GRADES else "No",
            "What it means": meaning,
        })
    st.markdown(
        "| Grade | Rows | Counted | What it means |\n| --- | --- | --- | --- |\n"
        + "\n".join(
            f"| {r['Grade']} | {r['Rows']} | {r['Counted']} | {r['What it means']} |"
            for r in grade_rows
        )
    )
    st.markdown(
        "A grade B row needs two reports on two different sites, and in practice usually "
        "includes the deployer's own public statement. Where the deployer confirmed the "
        "event but the harm is known only from reporting, the row stays at B rather than "
        "rising to A. The register keeps one grade C row, labelled on its card and "
        "excluded from every count, because dropping it would hide a failure pattern that "
        "no counted row shows as plainly."
    )
    st.markdown(
        "**A note on sources, which turned into a finding of its own.** Searching for these "
        "cases returns a large volume of pages that read as incident write-ups but are "
        "generated summaries of other summaries, often with invented detail and no primary "
        "record. Several candidate cases were dropped because no primary source existed "
        "behind the reporting. If you build something similar, budget most of your time "
        "for verification rather than for finding cases."
    )

    st.markdown("### The coding rubric")
    st.markdown(
        "Each row gets exactly one class for what the missing control governed. The rubric "
        "is applied in the order below, so the first match wins and a row cannot be "
        "classed twice."
    )
    rubric = [
        ("1. Vendor", "The failure arrived through a third party that held access to the organisation."),
        ("2. Boundary", "The agent acted on instructions that came from content it read rather than from its operator."),
        ("3. Authority", "The agent was able to take an action it should not have been able to take at all."),
        ("4. Oversight", "No person was positioned to catch it, stop it, or verify the claim the deployment ran on."),
        ("5. Accuracy", "What is left. The agent stated something untrue and nothing checked it against the source."),
    ]
    st.markdown(
        "| Order | Class | The test applied |\n| --- | --- | --- |\n"
        + "\n".join(
            f"| {name.split('.')[0]} | {name.split('. ')[1]} | {test} |"
            for name, test in rubric
        )
    )
    st.caption(
        "Accuracy is last on purpose. An agent that says something wrong and an agent that "
        "deletes a database both look like accuracy problems if accuracy is the first "
        "question you ask."
    )

    st.markdown(
        "Every row also carries a `secondary_class`: the reading the ordered rubric "
        "discarded. It is recorded on the card, it is never counted anywhere, and it "
        "exists because first-match-wins twice threw away a classification that had "
        "already been identified as real. AIR-009 is the clearest: a vendor compromise "
        "that nobody detected for months is an oversight failure as well as a vendor one, "
        "and Vendor simply gets tested first."
    )

    st.markdown("#### What that ordering does to the finding")
    facts = headline(frame)
    st.markdown(
        "Putting accuracy last is a choice, and a choice that could manufacture the "
        "result. If a case is both a permissions failure and an accuracy failure, this "
        "rubric classes it as the former. So the register measures the effect rather than "
        "asking to be trusted on it."
    )
    st.markdown(
        f"| Ordering | Cases classed as not accuracy |\n| --- | --- |\n"
        f"| Accuracy last, as published | {facts['not_accuracy']} of {facts['total']} |\n"
        f"| Accuracy first | {facts['accuracy_first']} of {facts['total']} |"
    )
    st.warning(
        "**These are two numbers, not three, and an earlier version of this page implied "
        "otherwise.** Under this coding, testing accuracy first classes a row as Accuracy "
        "exactly when the agent stated something untrue, so 'accuracy first' and 'the "
        "agent stated nothing untrue' are the same computation under two names. Showing "
        "both as separate rows would be showing one result twice and calling it "
        "corroboration. A reviewer caught that and it is recorded in the change log.",
        icon="⚠️",
    )
    st.markdown(
        f"**{facts['would_change_class']} rows change class** when accuracy is tested "
        f"first ({', '.join(facts['change_class_ids'])}), so the published ordering "
        "accounts for a real "
        f"part of the gap. {facts['accuracy_first']} of {facts['total']} is therefore the "
        "floor, and the home screen headline uses it rather than the larger number. Every "
        "row carries a `said_something_untrue` field recorded independently of its class. "
        "The one genuinely arguable row, AIR-012, is marked as having stated something "
        "untrue, which counts against this finding rather than for it."
    )
    st.markdown(
        "**What the ordering cannot touch.** The finding the register actually rests on is "
        "structural rather than a count. In none of the counted cases was an untrue "
        "statement sufficient on its own: harm always also required authority the agent "
        "should not have held, reach it should not have had, or a path nobody was "
        "monitoring. Rearranging the rubric changes which bucket a row sits in. It does "
        "not produce a single case where a wrong answer alone did the damage."
    )

    st.markdown("### Why these two scales")
    st.markdown(
        "Severity is reported on two recognised scales, because they answer different "
        "questions and neither answers the other's.\n\n"
        "- **How big was this, compared with all AI harm?** MIT's harm severity "
        "framework, five levels across ten harm types, built on CSET's Taxonomy of AI "
        "Harm as modified by MIT. It puts these cases on the same scale as the 1,700-odd "
        "incidents in MIT's own tracker.\n"
        "- **Would it cross the EU AI Act's serious-incident threshold?** Article 3(49). "
        "A legal reporting threshold rather than a measure of size, recorded as the "
        "closest limb and never as a legal classification."
    )
    st.markdown(
        "**The register used to carry its own four-level scale: Negligible, Moderate, "
        "Serious, Severe.** It had no external source. It was written for this register "
        "and it ranked the twelve cases it then covered against each other, which meant its "
        "middle was wherever those cases happened to sit. It has been retired rather than converted, "
        "and the old labels are gone from the site and from the data, because the word "
        "Severe does not mean on MIT's scale what it meant on that one."
    )
    st.caption(
        "NIST SP 800-61 Rev 2's impact tables were considered and not used: Rev 2 was "
        "withdrawn on 3 April 2025."
    )

    st.markdown("### Naming policy")
    st.markdown(
        "**This policy governs people who appear in the cases.** Deployers and vendors are "
        "named, because the public record names them and a register of anonymous cases "
        "cannot be checked. Individuals in the cases are not named, including the people "
        "who found these failures and the staff involved, even where reporting names them. "
        "The one exception is a named party to a published legal or regulatory decision, "
        "where the name is part of the citation.\n\n"
        "**Contributors to the register are a separate matter and are named with their "
        "consent.** A reviewer who reads this cold is doing work in their own name and "
        "should get the credit for it, which is the opposite of the situation the policy "
        "above protects against."
    )

    st.markdown("### Standards and frameworks used")
    st.markdown(
        "Each one links to the thing itself, not to a summary of it. That is the same bar "
        "the incident rows are held to.\n\n"
        "- **[NIST AI RMF 1.0](https://doi.org/10.6028/NIST.AI.100-1).** The closest "
        "subcategory per row, for the control that was missing.\n"
        "- **[NIST AI 800-4](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-4.pdf), "
        "March 2026.** A research report, not a standard. It proposes six monitoring "
        "categories and this register uses them to tag every signal: Functionality, "
        "Operational, Human factors, Security, Compliance, Large-scale impacts. Those are "
        "NIST's category names. Any one-line description of a category on this site is "
        "this register's summary, not NIST's wording.\n"
        "- **[EU AI Act, Regulation (EU) 2024/1689]"
        f"(https://eur-lex.europa.eu/eli/reg/2024/1689/oj).** {_articles_used(frame)} as "
        "closest clauses, listed in the order the mapping rule applies them. Article "
        "3(49) defines a serious incident, which is "
        "the threshold the reporting duty in Article 73 hangs on. EUR-Lex is the "
        "authoritative text. Article titles were checked against that site's reproduction "
        "because EUR-Lex does not serve automated requests.\n"
        "- **[OWASP Top 10 for Agentic Applications 2026]"
        "(https://genai.owasp.org/2025/12/09/owasp-genai-security-project-releases-top-10-"
        "risks-and-mitigations-for-agentic-ai-security/),** published 9 December 2025, for "
        "the failure pattern code. All ten codes and names were read on 10 October 2026 "
        "from [OWASP's own coded list](https://genai.owasp.org/2025/12/09/owasp-top-10-"
        "for-agentic-applications-the-benchmark-for-agent). OWASP's press release of the "
        "same day describes the same risks in looser wording and without codes, so this "
        "register follows the page that gives the codes. The allowed values live in "
        "frameworks/owasp_agentic_2026.csv with their source and retrieval date, and the "
        "validator reads that file rather than a list typed into the code. Each case also "
        "records whether its code was applied by OWASP or by this register.\n"
        "- **[Commission draft guidance and reporting template for serious AI incidents]"
        "(https://digital-strategy.ec.europa.eu/en/consultations/ai-act-commission-issues-"
        "draft-guidance-and-reporting-template-serious-ai-incidents-and-seeks).** A "
        "September 2025 draft, open for feedback until 7 November 2025. The fields on "
        "each incident card were shaped to sit close to it, so a row here can be lifted "
        "into that template rather than rewritten. No final version found as of 14 "
        "October 2026, checked at the consultation page linked above."
    )

    # 4a. The framework columns were "Our reading" on every row with no rule behind
    # them, which is the same weakness the Limits section admits about the secondary
    # class. This section states the rule, and the columns were recoded under it.
    st.markdown('<div id="mapping-rule"></div>', unsafe_allow_html=True)
    st.markdown("### How a case is mapped to a framework")
    st.markdown(
        "Each case names one provision per framework as its primary mapping, chosen by "
        "the rule below, and that is the one every count on the Findings page uses. Any "
        "other provision that also fits is kept on the case card, labelled, and counted "
        "nowhere. This is the same treatment the secondary class gets, and for the same "
        "reason: a figure built on an unruled judgement displays one person's reading as "
        "structure."
    )

    st.markdown("**EU AI Act**")
    st.markdown(
        "List every article whose text names the missing safeguard, then order them "
        "specific before general. The first in that order is the primary."
    )
    eu_order = [
        ("1", "Articles naming a specific safeguard",
         "Article 14 human oversight, Article 15 accuracy, robustness and "
         "cybersecurity, Article 9 risk management, Article 10 data and data governance"),
        ("2", "General provider and deployer duties",
         "Article 16 obligations of providers, Article 26 obligations of deployers"),
        ("3", "Transparency",
         "Article 50 transparency obligations for certain AI systems"),
        ("4", "General-purpose model duties",
         "Article 53 obligations for providers of general-purpose AI models, "
         "Article 55 where the model carries systemic risk"),
        ("5", "Post-market and incident reporting",
         "Article 72 post-market monitoring, Article 73 reporting of serious incidents"),
    ]
    st.markdown(
        "| Order | Group | Articles |\n| --- | --- | --- |\n"
        + "\n".join(f"| {n} | {group} | {arts} |" for n, group, arts in eu_order)
    )
    st.markdown(
        "Where no article names the safeguard, the value is written as `None (closest: "
        "Article N)` rather than reaching for the nearest general duty. That format "
        "exists so a reader can tell a mapping from an absence of one."
    )

    st.markdown("**NIST AI RMF 1.0**")
    st.markdown(
        "The subcategory whose text names the missing safeguard, in the function where "
        "that safeguard would have lived: GOVERN for policy, MAP for context, MEASURE "
        "for testing, MANAGE for operating controls. A subcategory that names the "
        "specific safeguard beats a generic one. MANAGE 4.1, which covers "
        "post-deployment monitoring in general, is the primary only when nothing more "
        "specific fits."
    )

    st.markdown("**OWASP Agentic Top 10**")
    st.markdown(
        "One entry per case: the one whose description names the mechanism of the "
        "failure, not the harm it produced. Where the case has no security path at all, "
        "the value is `Not applicable` rather than the closest-looking code."
    )

    st.markdown("**NIST AI 800-4**")
    st.markdown(
        "One category per case, by the same test: the category whose description names "
        "the way the failure happened."
    )

    st.markdown(
        "A mapping names the provision that describes the safeguard that was missing. It "
        "does not say the provision applied to that system, that the deployer was bound "
        "by it, or that anything was breached. Most systems here are not high-risk under "
        "the EU AI Act and several cases predate its obligations."
    )
    st.markdown("Mappings were made by one person under this rule, with no second coder.")

    # 31. The Home toggle links here. It answers the question that view raises and
    # does not answer: what an organisation's own register carries that a public one
    # cannot, and what that means for a reader who has to run one.
    st.markdown('<div id="enterprise"></div>', unsafe_allow_html=True)
    st.markdown("### What else changes inside an organisation")
    internal_cols = len(INTERNAL_COLUMNS)
    st.markdown(
        f"Home can show these cases as an organisation's own register would hold them, "
        f"with {count_word(internal_cols)} more columns across intake, response and "
        "closure. Every one of them is empty, and that is the point rather than a gap "
        "in the research: they are filled from logs, tickets, approvals and the people "
        "involved, and none of that is published. The difference between the two views "
        "is the difference between what a reader outside an organisation can ever know "
        "and what the organisation knew by the end of the week."
    )
    st.markdown(
        "**What the public record does carry.** One of those "
        f"{count_word(internal_cols)} columns, corrective action, is sometimes public, "
        "because a postmortem or a regulator's notice says what was changed. This "
        "register records how completely each ending is known, which is why that column "
        "can be filled at all."
    )
    st.markdown(
        "**What an internal register adds beyond columns.** Three things, none of which "
        "a public record can show.\n"
        "- **A named owner while it is open, not only afterwards.** This register codes "
        "a control owner and an accountable role for every case, and both are the "
        "register's reading of who would have held it, not a name from the record. "
        "Inside an organisation that is a person with a calendar.\n"
        "- **A clock.** Intake, response and closure have dates and a due date between "
        "them. A public account has a date it happened and sometimes a date it was "
        "fixed, and nothing in between.\n"
        "- **A decision about whether to tell a regulator.** The closure group carries "
        "it because it is a decision somebody makes, with a date and a name against it. "
        "Article 73 of the EU AI Act is the obligation this register points at most "
        "often, and whether it applies is a question about the system and the "
        "jurisdiction, not about the incident."
    )
    st.markdown(
        "**What this register is not.** It is not a template for running an incident "
        "process, and the empty columns are not a recommendation to adopt these nine. "
        "They are the columns these cases would need to be answerable inside the "
        "organisations they happened to, which is a different claim and a smaller one."
    )

    st.markdown("### Cross-references to the AI Incident Database")
    in_aiid = frame[frame["aiid_id"] != ""].sort_values("id")
    missing = sorted(frame[frame["aiid_id"] == ""]["id"])
    st.markdown(
        f"{len(in_aiid)} of the {len(frame)} cases here carry the same event's number "
        "in the AI Incident Database. Each was matched against the export in "
        "data/leads/, then opened and read to confirm it describes the same event. "
        "The database is on the aggregator list above, so these are pointers for a "
        "reader and never evidence for a row."
    )
    rows = "\n".join(
        f"| {r['id']} | [{r['aiid_id']}](https://incidentdatabase.ai/cite/"
        f"{r['aiid_id']}/) | {r['aiid_match_basis']} | {r['aiid_checked_on']} |"
        for _, r in in_aiid.iterrows()
    )
    st.markdown(
        "| Case | Database incident | Basis | Checked |\n| --- | --- | --- | --- |\n"
        + rows
    )
    if missing:
        st.caption(
            f"{and_join(missing)} "
            + ("has" if len(missing) == 1 else "have")
            + " no match. Searching the export and the site for the deployer, the date "
            "and the mechanism turned up nothing describing the same event."
        )

    st.markdown("### Where the cases were found")
    st.markdown(
        "Finding a case and admitting a case are different steps, and only the second one "
        "has a rule. These three were used to build the candidate list. None of them "
        "decides what goes in. The evidence rule does that, and every candidate had to "
        "survive it independently of where it came from.\n\n"
        "- **[AI Incident Database](https://incidentdatabase.ai/).** Indexed incidents with "
        "linked reports. Useful for finding, never cited as the evidence for a row, "
        "because an aggregator indexing other people's reporting is weaker than the "
        "reporting.\n"
        "- **[OECD AI Incidents and Hazards Monitor](https://oecd.ai/en/incidents-methodology).** "
        "News-derived candidates, and the incident versus hazard definitions this register "
        "uses.\n"
        "- **[Cyera, Agent-Inflicted Damage](https://www.cyera.com/research/agent-inflicted-"
        "damage-inside-the-real-world-failures-of-enterprise-ai-systems).** A vendor study "
        "of agent-caused cases, treated as a lead list only. A security vendor counting "
        "security failures has an interest in the total, which is the same structural "
        "problem this register discloses about its own sample.\n\n"
        "Field names and definitions follow the [OECD common reporting framework]"
        "(https://one.oecd.org/document/DSTI/DPC/GPAI(2024)5/FINAL/en/pdf) where they map "
        "cleanly onto the fields here."
    )

    st.markdown("### Limits")
    # E27. Fourteen long bullets asked a reader to work out what each one meant for
    # them. The table says that in the second column, which is the only column most
    # readers need.
    own_account, one_party = own_account_rows(frame[frame["counted"]])
    facts = headline(frame)
    limits = [
        ("One coder",
         "One person made every inclusion, grading and classification decision. There "
         "is no second rater and no inter-rater reliability figure, so read the coding "
         "as one defensible reading rather than as a measurement."),
        ("The secondary class has no rubric",
         "The primary class comes from an ordered, published, first-match-wins test. "
         "The secondary class, which records the reading that ordering discards, was "
         "assigned case by case with no rule behind it. It is on cards and counted "
         "nowhere, deliberately: a matrix built on it would display one person's "
         "unruled judgement as structure."),
        ("The rubric is stated, not pre-registered",
         "It was written before the rows were coded, but the rule file and the data "
         "file were first committed together, so nothing in the repository proves that "
         "order. From version 0.9 onward a rubric change lands in its own commit ahead "
         "of any recoding, which makes the claim checkable forward and not backward."),
        ("The sampling frame runs along the axis the finding measures",
         "Primary records exist for events that produce legal, security or regulatory "
         "paperwork, and those are disproportionately the authority, boundary and "
         "vendor cases. A chatbot that quietly gave wrong answers for a year generates "
         "no such document. Read the headline as a floor on the non-accuracy cases, not "
         "as a ratio between the two."),
        ("Fixing the rubric did not fix that",
         "Version 0.9 measured what the ordering was doing and rewrote the headline "
         "around the part that survives it. That closes one threat and leaves the "
         "sampling one standing, and the two are often confused. The repair was to "
         f"publish the candidates that were dropped: {_leads()[0]} leads with the test "
         f"each failed, and {count_word(_leads()[1])} since reconsidered and "
         "admitted."),
        (f"{count_word(len(one_party)).capitalize()} rows rest on one party's account",
         f"{and_join(one_party)} are graded B with a reputable outlet as the second "
         "source, and in each case that outlet reports the primary account rather than "
         "verifying it. They clear grade B and would not clear grade A. These are the "
         f"{count_word(len(one_party))} rows the Findings page points here, out of the "
         f"{count_word(len(own_account))} whose primary record the organisation "
         "published itself. Read them as the organisation's own account, carefully "
         "written and unverified."),
        ("Two cases were excluded, wrongly, and are now in",
         "AIR-023 was rejected as a single source when a reputable trade outlet had "
         "covered it seven months earlier, and that report was already in the lead "
         "export the rejection was written from. Its primary record is a first-hand "
         "postmortem naming the stale state file, the auto-approve, the row count and "
         "the recovery, and recording that the agent argued against putting both sites "
         "in one Terraform setup and was overruled, and that when the agent later "
         "proposed the destroy itself the operator did not stop it. AIR-024 was "
         "rejected as resting on a single report when three existed, one of them "
         "carrying the deployer's own on-record statement. Both were search failures "
         "rather than judgement calls, and both rows stay in the leads table with the "
         "reasoning that rejected them."),
        ("A convenience sample, not a population",
         "These are the cases with a usable public record. Agent failures handled "
         "quietly are the majority and none of them are here, which biases the counts "
         "toward the visible and the embarrassing."),
        (f"{facts['total']} is a small number",
         "A count this size illustrates a pattern rather than measuring its "
         "distribution. Treat the finding as a hypothesis worth testing against your "
         "own incidents."),
        ("Closest clause, not legal classification",
         "Every framework value is checked against the published list it comes from, "
         "and the build refuses one that is not in it. Whether a clause applies to a "
         "given deployment is a different question this register does not answer. "
         "Corrections to a clause reference are among the most useful things you can "
         "send."),
        ("Tests are not proof",
         "Every test on this site would have caught the specific failure described. "
         "Passing all of them does not make an agent safe."),
        ("Every structural correction here was prompted by a reader",
         "The checks catch regressions, not errors of judgement. The validator has "
         "never told this project that a framing was wrong, a count was misleading or "
         "a claim outran its evidence. People did, every time, and the automation is "
         "there to hold the line afterwards rather than to find it."),
    ]
    st.markdown(
        "| Limit | What it means for the reader |\n| --- | --- |\n"
        + "\n".join(f"| **{name}** | {meaning} |" for name, meaning in limits)
    )

    st.markdown('<div id="own-failures"></div>', unsafe_allow_html=True)
    st.markdown("### Four failures inside this project")
    st.markdown(
        "The register codes other people's agents as having controls that were "
        "implemented and did not hold. The same label is the honest one for these."
    )
    st.markdown(
        "- **A maintenance script reverted edits while every check passed.** The "
        "repository has a validator, a test suite and a green build. While all three "
        "were passing, a maintenance script was writing back a stale copy of the data "
        "file and silently reverting edits made while it ran. One published commit "
        "carried a reverted account of AIR-001, with a fact in the deployer's favour "
        "missing from it, and the build was green throughout. The checks validate the "
        "file's contents and not whether those contents are the ones somebody meant to "
        "write. An audit of every commit that touched the data has bounded the damage "
        "to that one row, two fields and one commit.\n"
        "- **A crash on the register screen survived six green builds.** The build "
        "parsed the app and never rendered it, so a nesting error that raised on every "
        "card open was invisible to it. The build now renders every screen.\n"
        "- **The fix for that crash's successor never worked at all.** Version 1.0 "
        "reached the live site as a crash when a new column met a cached table. The "
        "repair was a stamp passed to every loader so the cache would notice. "
        "Streamlit's data cache leaves out any argument whose name begins with an "
        "underscore, and the stamp was named that way, so the key never changed. The "
        "check written to catch it asserted that the stamp moved, which was never the "
        "question. The same crash reappeared on 14 October 2026 on a local development "
        "server that had been running since before a schema change, which is how it was "
        "found, and the live site was not affected on that occasion because a "
        "deployment there restarts the process. The check now changes the data file and "
        "asserts the loader returns the change.\n"
        "- **The app read a stale copy of its own rulebook.** The app takes its "
        "vocabularies from the validator, so that a value the validator would reject "
        "cannot appear on a page as valid. Streamlit reloads the app file when it "
        "changes and leaves the modules it imports in memory for the life of the "
        "process. A server running since earlier that day raised an error on this page "
        "for a name added to the validator that morning, and every headless check "
        "passed throughout, because each starts a fresh process and cannot see a stale "
        "one. The app now reloads the validator when its file has changed."
    )
    st.caption(
        "All four are the same shape: a control that existed, passed, and was not "
        "watching the thing that broke."
    )

    st.markdown("### Dates that matter")
    st.markdown(
        "The Digital Omnibus on AI is [Regulation (EU) 2026/1744]"
        "(https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32026R1744) of 8 July "
        "2026, published in the Official Journal on 24 July 2026 and in force from the "
        "third day after that. It moved some AI Act deadlines and left others alone, and "
        "the difference matters for how you read the clause column.\n\n"
        "| Obligation | Applies from | Where this came from |\n| --- | --- | --- |\n"
        "| Article 50 transparency | 2 August 2026, already in force | **Derived.** Article 113 sets a general application date of 2 August 2026 and does not list Chapter IV among its exceptions. Read from a consolidated rendering, not the Official Journal page itself. |\n"
        "| Article 50(2) machine-readable marking, for systems placed on the market before 2 August 2026 | 2 December 2026 | **Derived** from the four month transitional period in Regulation (EU) 2026/1744, whose recital text was read on EUR-Lex. The regulation gives the period, not the date. |\n"
        "| High-risk, standalone Annex III systems | 2 December 2027 | **Official Journal text** on EUR-Lex |\n"
        "| High-risk, AI embedded in Annex I regulated products | 2 August 2028 | **Official Journal text** on EUR-Lex |\n"
    )
    st.markdown(
        "**Two of these four are derived rather than quoted, and that distinction matters "
        "more here than anywhere else on this page.** These are the claims a lawyer in the "
        "audience knows better than I do, and an earlier version of this page took them "
        "from legal commentary without saying so. The regulation number, its entry into "
        "force and the two high-risk dates were since read on EUR-Lex. The Article 50 "
        "dates were not quoted from an article that states them, they were worked out from "
        "Article 113's structure and from a transitional period given in months. That "
        "reasoning is shown so you can check it rather than trust it, and a correction "
        "here is the most useful one you could send."
    )
    st.markdown(
        "The practical point for this register is that the chatbot cases are not waiting on "
        "a future deadline. Article 50 has applied since August 2026, so a deployer whose "
        "customer-facing agent misstates its own policy today is already inside a live "
        "transparency regime, not a forthcoming one."
    )

    st.markdown("### Corrections")
    st.markdown(
        "Corrections are recorded in the change log below with the date and what changed. "
        "A register nobody corrects is a blog post, so the log is kept whether or not "
        "anyone is asked to read it."
    )

    st.markdown("### Change log")
    # Wrapped so the stacking rule below 640px can be scoped to this table. Every other
    # table on the page is two or three short columns and reads fine as a table.
    with st.container(key="changelog"):
        st.markdown(
            "| Version | Date | What changed |\n| --- | --- | --- |\n"
        f"| {WORKING} | 2026-10-14 | **The OWASP entries were read in full, and four "
        "more mappings changed.** The codes had first been read by name, then by the "
        "launch post's recap sentences, which describe 2025 incidents rather than "
        "defining the entries. Reading the published document changed four rows. ASI09 "
        "requires a confident answer to persuade a person into an action, and in three "
        "of the five cases it had been given to, the record has no person who acted: "
        "those read Not applicable. The document also lists the poisoned build tool "
        "package under its supply chain entry, which moves that row and makes the "
        "mapping the framework owner's rather than this register's. Three mappings are "
        "now the framework owner's own. The one-line descriptions on the cards and the "
        "lens are this register's summary of each entry, labelled as such. |\n"
        f"| {WORKING} | 2026-10-14 | Counterfactual wording is out of the two monitoring "
        "and governance lenses. A case is listed under the kind of monitoring whose "
        "absence the record shows, and under the subcategory whose text names the "
        "missing safeguard, rather than under what would have caught it. Nothing in the "
        "data changed and the counts are the same. The claim was the difference between "
        "what the record shows and what a different setup might have done, and only one "
        "of those is in evidence. |\n"
        f"| {WORKING} | 2026-10-14 | Rows now carry how precisely their own source dates "
        "the event. Two are dated to a month and to a week rather than to a day, and "
        "they display that way instead of showing a precision this register does not "
        "have. The cross-reference line for those rows compares with the database at the "
        "precision they actually hold. |\n"
        f"| {WORKING} | 2026-10-14 | **AIR-024 added, and a second rejection "
        "corrected.** A lead was rejected on 12 October on the reasoning that it rested "
        "on a single report with nothing corroborating it. Three reports existed, and "
        "one of them carried an on-record statement from a named spokesperson at the "
        "organisation involved. Re-screened on all six tests and admitted. Posting "
        "without approval counts as an action under the first test, on the same reading "
        "that admits AIR-016, and the organisation's own position is that the agent only "
        "answered a question, which is recorded on the row and is why it is marked "
        "disputed. Both rejections this register has had to reverse were search "
        "failures, not rules that were too strict. The figures moved again: 22 "
        "documented to 23, 21 counted to 22, not accuracy 18 of 21 to 19 of 22, the "
        "record silent on who could stop the agent 19 of 21 to 20 of 22, no review date "
        "21 of 21 to 22 of 22, control never built 10 to 11, no attacker 13 of 21 to 14 "
        "of 22, Authority 8 to 9, the MIT Negligible band 7 to 8, and the rows with a "
        "disputed account one to two. |\n"
        f"| {WORKING} | 2026-10-14 | **The OWASP codes were re-checked against OWASP's "
        "own descriptions, and eight changed.** The codes had been read by name, and six "
        "cases were coded Not applicable on the reasoning that an accuracy failure has "
        "no attack pattern. OWASP's own one-line description of ASI09 is that confident, "
        "polished explanations misled human operators into approving harmful actions, "
        "which names the mechanism in five of those six exactly. Not applicable is no "
        "longer used by any row. The descriptions are now in the framework file and on "
        "every card, read from the same page the codes come from. The same page names "
        "worked examples for six of the ten codes, and two of them are cases in this "
        "register, so those two mappings are now marked as applied by the framework "
        "owner rather than by this register. |\n"
        f"| {WORKING} | 2026-10-14 | **A fourth failure of the same shape, found in the "
        "last check of the day.** The app reads its vocabularies from the validator so "
        "that a value the validator would reject cannot be displayed as valid. "
        "Streamlit reloads the app file when it changes and does not reload the modules "
        "the app imports, which live in memory for the life of the process. A local "
        "development server that had been running since before the mapping rule landed "
        "raised an error on the Method page for a name added to the validator that "
        "morning, and the live site was not affected because a deployment there starts "
        "a fresh process. Every "
        "headless check passed, because each of those starts a fresh process and can "
        "never see a stale one. The app now reloads the validator when its file has "
        "changed. The three failures this project had already recorded are in the "
        "section above, and this is the fourth of the same kind: a control that "
        "existed, passed, and was not watching the thing that broke. |\n"
        f"| {WORKING} | 2026-10-14 | Limits is a table rather than fourteen long "
        "bullets, with a second column saying what each limit means for a reader. The "
        "three failures this project has produced itself now have their own section "
        "rather than sitting inside a limit: a maintenance script that reverted edits "
        "while every check passed, a crash that survived six green builds, and the "
        "cache fix that never worked. All three are the shape this register codes in "
        "other people's systems as a control that was implemented and not watching the "
        "thing that broke. The first Limits row also stops saying every judgement here "
        "is mine and says what it means instead, which is that one person made every "
        "inclusion, grading and classification decision with no second rater. |\n"
        f"| {WORKING} | 2026-10-14 | Every case now says whether the AI Incident "
        "Database holds the same event, with the incident number, the basis for calling "
        "it the same event and the date that was checked. Twenty of the twenty two "
        "match. Each match was found in the database's own export, then opened and read "
        "to confirm it describes the same event rather than a similar one, which caught "
        "two whose dates differ because the database dates from the first report, and "
        "one that the database records as a bundle of several misuse cases from a single "
        "threat intelligence report. Two cases have no match, which is recorded as not "
        "found rather than as not there. The database stays on the aggregator list: "
        "these are pointers for a reader and never evidence for a row. |\n"
        f"| {WORKING} | 2026-10-14 | **Framework mappings have a rule now, and the rows "
        "were recoded under it.** Every framework column said \"Our reading\" with "
        "nothing published behind it, which is the same weakness the Limits section "
        "admits about the secondary class. The rule is on this page, above: one primary "
        "mapping per framework per case, specific provisions before general ones, and "
        "the EU ordering is checked by the build rather than asserted. 33 primary "
        "mappings changed. The largest effects: MANAGE 4.1, which covers post-deployment "
        "monitoring in general, was the primary on 11 rows and is now the primary on "
        "none, because it is the fallback and something more specific fit every time. "
        "Article 26, the general deployer duty, was the primary on no row and is now "
        "secondary everywhere a specific article exists. Five accuracy and oversight "
        "cases were labelled with an OWASP attack pattern they had no security path to, "
        "and now read Not applicable, along with one change-control case. Every lens now "
        "counts a case once under its primary mapping, so the bars add up to the number "
        "of counted cases instead of to the number of mappings. |\n"
            f"| {WORKING} | 2026-10-14 | **AIR-023 added, and it should have been here "
            "already.** On 12 October a lead was rejected for want of a second source, on the "
            "reasoning that no reputable independent outlet had covered it. One had, seven "
            "months earlier, and that report was already in the lead export the rejection was "
            "written from. The case is an own account with a reputable outlet relaying it, "
            "which is the same shape the evidence rule already accepts on three other rows. "
            "The error was a search that stopped at the first source, not a rule that was too "
            "strict. Every figure moved: 21 documented cases to 22, 20 counted to 21, 14 grade "
            "B rows to 15. The missing safeguard was not accuracy in 17 of 20, now 18 of 21. "
            "With accuracy tested first, 10 of 20 becomes 11 of 21. The record does not say "
            "who could stop the agent in 19 of 20, now 19 of 21, because this row is the "
            "first where it does. No review date in 20 of 20, now 21 of 21. The control was "
            "never built in 9 cases, now 10. No attacker was involved in 12 of 20, now 13 of "
            "21. Authority rose from 7 to 8 and is still the largest class. The MIT Minor band "
            "went from 7 to 8. Not determinable on the EU test went from 15 to 16. The primary "
            "record is the organisation's own publication in 5 cases, now 6, and the rows that "
            "rest on one party's account went from three to four. Entailed as the basis for "
            "the missing control went from 5 to 6. The leads table holds 114 rejections rather "
            "than 115, with the reconsidered row kept in place. |\n"
            f"| {WORKING} | 2026-10-14 | The fix that was meant to stop a schema "
            "change reaching the live site as a crash had never worked. Streamlit's data "
            "cache leaves out any argument whose name begins with an underscore, and the "
            "loaders took the file stamp as one, so the stamp moved on every data change "
            "and the cache key did not. The same crash reappeared on 14 October 2026 on "
            "a local development server that had been running since before a schema "
            "change, which is how it was found, and the live site was not affected on "
            "that occasion because a deployment there restarts the process. The loaders "
            "no longer name it that way. The "
            "check that was meant to catch this asserted that the stamp moved, which was "
            "never the question, and now changes the data file and asserts the loader "
            "returns the change. |\n"
            f"| {WORKING} | 2026-10-14 | Findings is reorganised around the question a "
            "reader arrives with. Three tabs, How bad, What kind of failure and Gaps in the "
            "record, with a selector on the first two reading View the cases through. The "
            "same cases can now be read through seven lenses: MIT harm severity, the EU "
            "serious-incident test, this register's own missing-control classes, the OWASP "
            "Agentic Top 10, the NIST AI RMF, the EU AI Act articles and the NIST AI 800-4 "
            "monitoring categories. Every category name and every clause text in the four "
            "new views is read from the published lists in frameworks/, and the chosen lens "
            "is carried in the URL so one view can be linked to. The bars in those four "
            "views are a single neutral blue, because severity is this site's only data "
            "colour. The harm-type filter reads the MIT ratings file, so it now appears on "
            "the MIT view alone rather than on both. |\n"
            f"| {WORKING} | 2026-10-14 | A sentence on Findings said four cases rest on "
            "a report published by an AI company, and named them by hand. One of the four "
            "was a build tool maintainer's security advisory, so the page called that "
            "maintainer an AI company. The sentence is now read off the source label and "
            "says what the label supports, which is that the primary record is the "
            "implicated organisation's own published account. That first came out as six, "
            "which counted a case whose primary record is a news outlet relaying the "
            "company's account rather than the account itself. It is five. The rows the "
            "Limits section says rest on one party's account are the subset of those five "
            "that no second source corroborates, and both figures now come from one "
            "function, so the two screens cannot disagree. |\n"
            f"| {WORKING} | 2026-10-14 | Framework values are checked against the "
            "published lists rather than against a pattern. The NIST AI RMF core, 72 "
            "subcategories with their official text, the EU AI Act article titles and the "
            "six NIST AI 800-4 monitoring categories are now files in the repository, each "
            "with its source and the date it was read. Until v1.1 the check asked only "
            "whether a value looked right, so a subcategory or an article that does not "
            "exist would pass. Both are now rejected. No existing row failed the new check: "
            "every subcategory and article already in the register is a real one, so what "
            "changed is that a wrong value can no longer get in. Two basis columns were "
            "added so each mapping says whether a framework owner applied it or this "
            "register did, and a value is allowed where no provision addresses the missing "
            "safeguard, written as None with the closest article named. |\n"
            f"| {WORKING} | 2026-10-14 | ISO/IEC 42001 column removed pending "
            "verification against the standard's text. The numbers stay in the data file "
            "and appear on no page. |\n"
            "| 1.0 | 2026-10-13 | **The watch list screen is removed.** It asked six "
            "questions about a reader's own agent and returned the tests to run. The "
            "questions did not discriminate. Three unlike systems, a read-only public "
            "chatbot, an internal coding agent and a back-office automation that spends "
            "money, each returned sixteen items. Across all sixty four possible answer "
            "sets the median was thirteen and fifty two returned ten or more, so the only "
            "way to get a short list was to describe an agent that barely exists. A "
            "questionnaire where almost every answer gives almost the same output is a "
            "list with extra steps, and sixteen items each carrying a test, a pass mark, a "
            "signal, an owner, two framework codes and a case list is not a watch list. "
            "The tests themselves were never the problem and they have not gone anywhere: "
            "every one is still on the case it came from, under Test before launch. The "
            "twenty four rules, the engine that applied them, their validator checks and "
            "their continuous integration step are removed with the screen rather than "
            "left in the repository unused. |\n"
            "| 1.0 | 2026-10-13 | **The release broke the live site, and the cause is this "
            "register's own subject.** v1.0 reached the hosted app as a KeyError on the home "
            "screen. The data loaders were cached, and the cache keys on the function's code "
            "and arguments rather than on the files it opens. Adding a column to the case data "
            "left that key identical, so new code ran against a table cached before the column "
            "existed. Every local check passed because each run starts with an empty cache, "
            "which is the difference between a control that is implemented and one that is "
            "operating. The loaders now take a stamp built from the data files, so the cache "
            "falls when the data changes. The site was broken for the time between the push "
            "and this fix. |\n"
            "| 1.0 | 2026-10-12 | **Pre-merge review.** AIR-021 moved from grade A to B: its "
            "only readable independent coverage is substantially a summary of the institute's "
            "own report, and grade A asks the second source to corroborate rather than restate. "
            "A read audit of every source on the nine new cases found four cited on a "
            "reachability check rather than a reading, and all four have now been read: two "
            "needed no change, one produced that regrade, and one had already been caught. Ten "
            "of the ninety four title-stage rejections were drawn at random with a recorded "
            "seed and checked in depth. None was wrongly rejected, so the remaining eighty four "
            "were not re-screened, but two had the wrong test named and were corrected. A new "
            "field records who pointed the agent at the harm, with a basis on every row, shown "
            "on the cards and in the filters. The three Home cards were re-picked for twenty "
            "cases. Two dead code paths were removed: a duplicate findings table that silently "
            "overwrote the one above it, and a stale comment. |\n"
            "| 1.0 | 2026-10-12 | **Release. Twelve cases to twenty one, eleven counted to twenty.** "
            "Every number below is recomputed from the data on each page load, including the case "
            "count itself. Old is version 0.9, new is this release. Said nothing untrue 5 of 11 to "
            "10 of 20. Record silent on who could stop it 10 of 11 to 19 of 20. Control never built "
            "6 of 11 to 9 of 20. Control existed and did not hold 1 of 11 to 6 of 20, plus one case "
            "in a new state, Bypassable, where the gate was built and the caller could switch it "
            "off. Missing control was not accuracy 8 of 11 to 17 of 20. Read-only agents 6 of 11 to "
            "6 of 20, the only count that did not move at all. Evidence grades 5 A and 6 B to 7 A "
            "and 13 B. Endings 8 documented, 2 partial, 1 undocumented to 14, 5 and 1. Severity on "
            "MIT's scale, counted rows only, 5 Minor, 5 Negligible and 1 Substantial to 7, 7 and 6. "
            "Missing control class 3 Accuracy, 3 Authority, 2 Boundary, 2 Oversight and 1 Vendor to "
            "3, 7, 6, 3 and 1. Event years unchanged at 2022 to 2026. |\n"
            "| 1.0 | 2026-10-12 | **Which findings held and which moved.** Held: no case in the "
            "register was only the AI being wrong, which is still true at 20 counted cases as it was "
            "at 11. Held and strengthened: the record is almost always silent on who could have "
            "halted the deployment, now 19 of 20, and a scheduled date to look again appears in "
            "none of the 20. Moved against the register's own framing: Accuracy did not grow at "
            "all, staying at 3 cases while Authority went from 3 to 7 and Boundary from 2 to 6, so "
            "the register is now mostly about what agents were allowed to do rather than what they "
            "got wrong. Weakened: Vendor is still a single case after nine admissions, so any "
            "statement about that class remains a description of one row. Worth saying rather than "
            "hiding: the two strongest Vendor candidates found in the census both failed, one on the "
            "organisation test and one on evidence. |\n"
            "| 1.0 | 2026-10-12 | **What the census says about selection.** 115 leads were checked "
            "and not included, each listed with the test it failed: 59 on agent action, 23 on harm, "
            "21 on organisation, 9 on evidence, 2 on traceability and 1 already in the register. "
            "That shape is the honest answer to how narrow this register is. The largest group is "
            "cases where an AI system produced text and a person read it, which the register "
            "excludes on purpose and which is where most public AI harm reporting sits. The "
            "evidence test excluded nine, including a first-hand postmortem of an agent destroying "
            "two and a half years of production data, which no reputable outlet covered. A single "
            "source is grade C and the inclusion rule admits only A and B, so the rule excluded a "
            "case better documented than some that are in. |\n"
            "| 1.0 | 2026-10-12 | Census complete against the lead lists. Every lead in "
            "the window was screened and 115 are listed with the test each failed. Nine cases "
            "admitted: AIR-013 and AIR-020, two campaigns run through one platform's coding agent, "
            "one espionage and one extortion of at least seventeen organisations. AIR-015, malware "
            "that asked the agents already on a machine to find its secrets. AIR-016 and AIR-019, "
            "the same posting assistant two months apart, once after an update restored deprecated "
            "code and once after an unreviewed edit to its prompt. AIR-017, an account recovery "
            "assistant that handed accounts to whoever asked. AIR-018, a research agent that routed "
            "around a government portal's blocks and wrote to an internal server. AIR-021, an "
            "evaluation body's own agents reaching the live internet and working on real people. "
            "AIR-022, a multi-agent framework running four days of government intrusion. A tenth "
            "case was admitted and withdrawn the same day for failing the organisation test. |\n"
            "| 1.0 | 2026-10-12 | Two corrections from reviewing the admitted cases. "
            "Every new case had its stop-authority answer recoded to Not disclosed. Each had been "
            "marked Yes on the strength of a platform suspending accounts, removing packages or "
            "disabling a tool after the event, which is a response and not a record of a role that "
            "could have halted the deployment. One of the original twelve still holds that answer, "
            "on a source describing sign off by two people. And AIR-016 was rewritten from the "
            "article itself after it turned out to have been drafted from a search summary, which "
            "changed what the company is quoted as saying and what it froze. |\n"
            "| 1.0 | 2026-10-11 | Three method changes forced by reviewing the first "
            "batch. Grade A now requires its second source to be on a different host from the "
            "primary record and to corroborate rather than restate it, which is what moved AIR-013 "
            "to B. A fifth control state, Bypassable, was added for a gate that was built and wired "
            "in and that the caller could switch off with a documented flag, which is a different "
            "failure from a gate that engaged and did not hold. And the pre-commit hook now runs "
            "the validator: a row had been committed with the register invalid, because the "
            "validator printed the error, the output was read by its last few lines, and nothing "
            "local refused the commit. |\n"
            "| 1.0 | 2026-10-11 | Lead sources amended, with the six inclusion tests "
            "unchanged. The MIT AI Incident Tracker was dropped as a lead list, because its "
            "incidents sit behind an embedded spreadsheet application rather than in the page and "
            "it is built from AI Incident Database reports in any case. The database's own weekly "
            "export is used instead, recorded in data/leads with its URL, download date and a "
            "checksum. Both remain lead lists and neither is ever cited: the denylist that keeps "
            "aggregators out of the evidence fields is unchanged. |\n"
            "| 0.9 | 2026-10-11 | Committed a dated inclusion rule before adding any case "
            "under it. Six tests, all of which must pass, with the window set to events and "
            "publication between 1 January 2025 and 30 September 2026. The decision never "
            "looks at a case's class, severity or whether the agent said something untrue, "
            "because those are what the findings count. Six of the original twelve predate "
            "the rule and are marked as such rather than retrofitted into it. The validator "
            "rejects any row claiming to have passed the rule with an event date outside the "
            "window. |\n"
            "| 0.9 | 2026-10-11 | Layout pass, no numbers changed. The case list merged into "
            "Home, which had been showing the same twelve rows under a second set of headline "
            "numbers. Removed every comment and review invitation, the citation block, the "
            "certainty strip, the shortcut links and a bar chart that labelled three of its "
            "five bars. Findings became three tabs on one pattern: a question, a one-sentence "
            "answer, a table, one line on how to read it. The severity grid became one row "
            "per case, because the grid cut off the Privacy column and hid the only "
            "Substantial case. On a card, only the severity pill is coloured now. |\n"
            "| 0.9 | 2026-10-11 | Severity moved from the register's own 4-level scale, which "
            "ranked cases against each other and had no external source, to MIT's 5-level "
            "harm severity framework (CSET-based, up to global scale). The two scales use "
            "different reference points, so old labels were retired, not converted. Each case "
            "was re-scored from its facts: 6 Negligible, 5 Minor, 1 Substantial. An EU AI Act "
            "serious-incident threshold view was added alongside it. |\n"
            "| 0.9 | 2026-10-10 | Checked OWASP labels against OWASP's own coded list. No "
            "change to codes. All ten names confirmed from the page that carries the codes, "
            "with the shorter official forms adopted and the longer forms kept as aliases. "
            "The same day's press release uses looser wording without codes, so it is not the "
            "source. AIR-010's code is now recorded as Stated, because that list cites "
            "EchoLeak as its own ASI01 example. Every framework value now carries a basis. |\n"
            "| 0.9 | 2026-10-10 | Removed the comment deadline, keeping the route and the "
            "commitment to log everything. Started the framework work by trying to verify the "
            "two lists it depends on, and did not get them. The OWASP entry names sit in a "
            "PDF behind a download form, and checking the ones that are public found OWASP's "
            "own announcement wording ASI01 differently from the secondary source this "
            "register used, on three cases. Allowed values now live in frameworks/, each with "
            "its source, retrieval date and whether the owner's own publication was reachable. "
            "The validator reads that file and warns on a disputed name, and the cards say so. "
            "The MIT scales are not coded, because their reachable pages give counts without "
            "naming the values. |\n"
            "| 0.9 | 2026-10-10 | Line-by-line fact check of Home, which found four claims "
            "the evidence did not carry. The headline said most of these failures were not "
            "the AI being wrong, which only holds under the accuracy-last rubric the page "
            "itself says the finding does not rest on. It is now the claim the validator "
            "enforces: none was only the AI being wrong. Three sentences asserted an absence "
            "with no source, including one about approval steps whose field, unlike the "
            "stop-authority field, carries no source at all. The Article 73 note claimed "
            "every row maps onto the Commission's template and could be lifted into a report, "
            "when that duty falls on providers of high-risk systems and most of these are "
            "not. Rebuilt Home as a hero, three dot cards and a certainty bar. |\n"
            "| 0.9 | 2026-10-09 | Home cut from about 2,000 words and eleven headings to 500 "
            "and four, after it was read as information overload. Nothing was deleted: the "
            "analysis moved to a Findings screen somebody can choose. Home now carries the "
            "finding, a chart of what the missing control governed, and the severity spread "
            "as a bar. Extended the displayed-number check to cover Home. |\n"
            "| 0.9 | 2026-10-09 | Redesign. Colour now means one thing, severity of harm, and "
            "every severity pill carries a four-bar meter and the word so nothing depends on "
            "colour alone. Evidence grade is monochrome and the chart is one hue. The cases "
            "screen leads with the question, three findings as tiles, and filters where each "
            "selection writes itself into the URL so a filtered view can be posted. Each case "
            "opens into five tabs, and the three cases with a runnable test name the file and "
            "class that runs it. Added a check that recomputes every number on screen from the "
            "data file and fails the build if a typed number ever diverges. |\n"
            "| 0.9 | 2026-10-09 | Reviewer rounds, consolidated. Late in the day, rebuilt the "
            "incident card into four tabs after it had accumulated thirty-two fields and six "
            "coloured boxes in one scroll, which was unreadable however correct each line "
            "was. Moved the repeated definitions to this page. Replaced the red block at the "
            "top of Method with plain text, because a page that opens on an alarm reads as an "
            "apology rather than as a method. |\n"
            "| 0.9 | 2026-10-09 | Earlier that day. Measured what the rubric's "
            "ordering does to the finding and rewrote the headline around the part that "
            "survives it. Separated descriptive counts from analytical ones. Decoupled "
            "severity from recovery effort. Corrected the EU AI Act dates against EUR-Lex, "
            "including that Article 50 is already in force, and labelled the two derived "
            "dates as derived. Withdrew the pre-registration claim and a nine second figure, "
            "both unevidenced. Audited how every story ended and corrected three accounts "
            "that stopped at the failure. Added an aggregator denylist, per-row aftermath "
            "citations, a stated basis for every severity rating, and the three deployment "
            "questions where Not disclosed is the default. Split the owner, added control "
            "maturity, and recorded who bore the harm against who could have prevented it. "
            "Marked how the register knows each missing control, in three tiers. Fixed a "
            "crash that had broken the register screen for six commits under a green build, "
            "and added a headless render of every screen to CI. Archived every source after "
            "finding the archiver was reverting hand edits. |\n"
            "| 0.8 | 2026-10-03 | First build. 12 cases, 11 counted, 18 watch-list rules. |"
        )


# ------------------------------------------------------------------------------ main


def main():
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    frame = load_register(data_stamp(DATA_FILE, RATINGS_FILE))

    with st.sidebar:
        st.markdown("## AI Agent Incident Register")
        # The screen lives in the URL as well as in session state, because the filter
        # tiles on Findings are links. Without this, following one would land the reader
        # back on Home with their filter applied to a page they were not looking at.
        screens = ["Home", "Findings", "Method"]
        asked = st.query_params.get("screen")
        screen = st.radio(
            "Screen",
            screens,
            index=screens.index(asked) if asked in screens else 0,
            label_visibility="collapsed",
        )
    if screen == "Home":
        if "screen" in st.query_params:
            del st.query_params["screen"]
    elif st.query_params.get("screen") != screen:
        st.query_params["screen"] = screen
    with st.sidebar:
        st.markdown("---")

    # One delegated listener for the row tabs and the open and close controls, on
    # every screen rather than only Home. It lived inside the home screen until 13
    # October 2026, which left the tabs and the controls dead on Findings: the markup
    # rendered, nothing was wired to it, and nothing errored.
    components.html(
        "<script>"
        "const doc = window.parent.document;"
        "if (!doc.__caseTabs) {"
        "  doc.__caseTabs = true;"
        "  doc.addEventListener('click', (e) => {"
        "    const all = e.target.closest && e.target.closest('.tctl-b');"
        "    if (all) {"
        "      const want = all.dataset.all === 'open';"
        "      let scope = all.parentElement;"
        "      while (scope && !scope.querySelector('details.crow')) "
        "        scope = scope.parentElement;"
        "      (scope || doc).querySelectorAll('details.crow')"
        "        .forEach(d => { d.open = want; });"
        "      return;"
        "    }"
        "    const b = e.target.closest && e.target.closest('.ctabs .tb');"
        "    if (!b) return;"
        "    const box = b.closest('.ctabs');"
        "    const tabs = [...box.querySelectorAll(':scope > .tabrow > .tb')];"
        "    const panes = [...box.querySelectorAll(':scope > .pane')];"
        "    const i = tabs.indexOf(b);"
        "    tabs.forEach((t, n) => t.classList.toggle('on', n === i));"
        "    panes.forEach((p, n) => p.classList.toggle('on', n === i));"
        "  });"
        "}"
        "</script>",
        height=0,
    )

    # A ?lens= link names a selector that lives on one of the Findings tabs, and
    # st.tabs cannot be opened from Python. The tab is clicked once, by its own label,
    # so a shared link lands on the view it names rather than on the first tab.
    wanted_tab = LENS_TAB.get(st.query_params.get("lens"))
    if screen == "Findings" and wanted_tab and wanted_tab != HOW_BAD_TAB:
        components.html(
            "<script>"
            "const doc = window.parent.document;"
            "if (!doc.__lensTab) {"
            "  doc.__lensTab = true;"
            f"  const want = {wanted_tab!r};"
            "  let n = 0;"
            "  const id = setInterval(() => {"
            "    const t = [...doc.querySelectorAll('button[role=\"tab\"]')]"
            "      .find(b => b.innerText.trim() === want);"
            "    if (t && t.getAttribute('aria-selected') === 'true') {"
            "      clearInterval(id);"
            "      return;"
            "    }"
            "    if (t) { t.click(); }"
            "    if (++n > 20) { clearInterval(id); }"
            "  }, 150);"
            "}"
            "</script>",
            height=0,
        )

    # 4d. A link on a case card has to land on the rule in one click, and a Streamlit
    # heading is not an anchor a browser will scroll to on its own after the page has
    # rendered. The parameter is read here and the section is scrolled into view once.
    rule_anchor = {"mapping": "mapping-rule", "enterprise": "enterprise"}.get(
        st.query_params.get("rule")
    )
    if screen == "Method" and rule_anchor:
        components.html(
            "<script>"
            "const doc = window.parent.document;"
            "if (!doc.__ruleJump) {"
            "  doc.__ruleJump = true;"
            "  let n = 0;"
            f"  const want = {rule_anchor!r};"
            "  const id = setInterval(() => {"
            "    const t = doc.getElementById(want);"
            "    if (t) { t.scrollIntoView({block: 'start'}); clearInterval(id); }"
            "    if (++n > 20) { clearInterval(id); }"
            "  }, 150);"
            "}"
            "</script>",
            height=0,
        )

    if screen == "Home":
        screen_home(frame)
    elif screen == "Findings":
        screen_findings(frame)
    else:
        screen_method(frame)

    with st.sidebar:
        st.caption(
            f"Version {VERSION}, {UPDATED}. {len(frame)} cases, "
            f"{int(frame['counted'].sum())} counted. Built by Sana Asif Ahmad. "
            "Not legal advice."
        )

    st.markdown("---")
    st.caption(
        f"AI Agent Incident Register, version {VERSION}. Every number on this site "
        "is computed from the case data and uses grade A and grade B rows only. The "
        f"[code and the data]({REPO_URL}) are public, and the Method page says how both "
        "work."
    )


if __name__ == "__main__":
    main()
