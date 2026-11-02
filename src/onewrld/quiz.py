"""Voice quiz: this-or-that pairs that locate your voice on each style dimension."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

import psycopg
import yaml

from onewrld.brand import BRAND_DIR

CHOICES = {"a": "a", "b": "b", "1": "a", "2": "b", "both": "both", "n": "neither",
           "neither": "neither", "ab": "both"}


def load_pairs() -> list[dict]:
    return yaml.safe_load((BRAND_DIR / "voice_quiz.yaml").read_text(encoding="utf-8"))["pairs"]


def save_answer(conn: psycopg.Connection, pair: dict, choice: str) -> None:
    value = {"a": pair["a"]["value"], "b": pair["b"]["value"]}.get(choice)
    conn.execute(
        """INSERT INTO quiz_answer (pair_id, dimension, choice, value) VALUES (%s,%s,%s,%s)
           ON CONFLICT (pair_id) DO UPDATE
           SET choice=EXCLUDED.choice, value=EXCLUDED.value, answered_at=now()""",
        (pair["id"], pair["dimension"], choice, value))


def run(conn: psycopg.Connection, ask: Callable[[str], str] = input,
        show: Callable[[str], None] = print) -> int:
    pairs = load_pairs()
    show("Pick the one that sounds more like ONEWRLD. Type a, b, both, or n (neither).\n")
    answered = 0
    for i, p in enumerate(pairs, 1):
        show(f"[{i}/{len(pairs)}]")
        show(f"  a)  {p['a']['text']}")
        show(f"  b)  {p['b']['text']}")
        while True:
            raw = ask("  your pick: ").strip().lower()
            if raw == "q":
                return answered
            if raw in CHOICES:
                save_answer(conn, p, CHOICES[raw])
                answered += 1
                break
            show("  type a, b, both, n, or q to stop")
        show("")
    return answered


def profile(conn: psycopg.Connection) -> list[str]:
    """Plain-English summary of your answers, one line per dimension."""
    rows = conn.execute("SELECT dimension, choice, value FROM quiz_answer ORDER BY pair_id").fetchall()
    out = []
    by_dim = defaultdict(list)
    for r in rows:
        by_dim[r["dimension"]].append(r)
    for dim, rs in by_dim.items():
        r = rs[-1]
        label = r["value"] if r["choice"] in ("a", "b") else r["choice"]
        out.append(f"{dim.replace('_', ' ')}: {label}")
    return out
