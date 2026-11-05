"""Captions: import caption files, score them, and record your approve/reject/edit decisions.

Decisions go in the shared `approval` table (item_type 'caption'), so the future
dashboard's approvals inbox sees captions, posts and ad changes in one place.
Your reason for every reject or edit is stored: that is the feedback the Brand Brain
learns from.
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Callable

import psycopg
from psycopg.types.json import Jsonb

from onewrld.brand import QUALITY_FLOOR, score_caption
from onewrld.logging_setup import get_logger

log = get_logger(__name__)


def text_hash(text: str) -> str:
    norm = " ".join(text.lower().split())
    return hashlib.sha256(norm.encode()).hexdigest()[:32]


def add_caption(conn: psycopg.Connection, text: str, *, pillar: str | None = None,
                product: str | None = None, source: str = "session",
                fact_check: bool = False, parent_id: int | None = None,
                kind: str = "caption", hook_type: str | None = None) -> tuple[int, bool]:
    """Score and store one caption. Returns (id, created). Same text twice = no-op.
    Captions at or above the quality floor get a pending approval automatically."""
    s = score_caption(text)
    # Hooks are hashed separately, so the same words can be approved as a caption AND a hook.
    h = text_hash(text) if kind == "caption" else text_hash(f"{kind}: {text}")
    with conn.transaction():
        row = conn.execute(
            """INSERT INTO caption (text, text_hash, pillar, product, source, fact_check,
                                    score, blocked, score_reasons, parent_id, kind, hook_type)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (text_hash) DO NOTHING RETURNING id""",
            (text.strip(), h, pillar, product, source, fact_check,
             s.score, s.blocked, Jsonb(s.reasons), parent_id, kind, hook_type)).fetchone()
        if row is None:
            # Already have this caption: keep its approval history, but refresh the
            # labels (pillar, product, fact_check) from the file, which is the source of truth.
            existing = conn.execute(
                """UPDATE caption SET pillar = COALESCE(%s, pillar),
                                      product = COALESCE(%s, product),
                                      hook_type = COALESCE(%s, hook_type),
                                      fact_check = %s
                   WHERE text_hash = %s RETURNING id""",
                (pillar, product, hook_type, fact_check, h)).fetchone()
            return existing["id"], False
        if s.passes:
            conn.execute(
                """INSERT INTO approval (item_type, item_id, summary)
                   VALUES ('caption', %s, %s) ON CONFLICT DO NOTHING""",
                (str(row["id"]), text.strip()[:200]))
    return row["id"], True


def import_file(conn: psycopg.Connection, path: Path) -> dict[str, int]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    product = data.get("product")
    stats = {"new": 0, "already_had": 0, "blocked": 0, "below_floor": 0, "to_review": 0}
    for item in data["captions"]:
        cid, created = add_caption(conn, item["text"], pillar=item.get("pillar"),
                                   product=item.get("product", product), fact_check=bool(item.get("fact_check")))
        if not created:
            stats["already_had"] += 1
            continue
        stats["new"] += 1
        row = conn.execute("SELECT score, blocked FROM caption WHERE id=%s", (cid,)).fetchone()
        if row["blocked"]:
            stats["blocked"] += 1
        elif row["score"] < QUALITY_FLOOR:
            stats["below_floor"] += 1
        else:
            stats["to_review"] += 1
    return stats


def pending(conn: psycopg.Connection, limit: int = 10, kind: str = "caption") -> list[dict]:
    return conn.execute(
        """SELECT c.id, c.text, c.pillar, c.score, c.score_reasons, c.fact_check, c.hook_type
           FROM approval a JOIN caption c ON c.id = a.item_id::bigint
           WHERE a.item_type = 'caption' AND a.status = 'pending' AND c.kind = %s
           ORDER BY c.score DESC,
                    CASE WHEN c.kind = 'hook' THEN c.id END ASC,   -- hooks: library order
                    c.id DESC                                       -- captions: newest batch first
           LIMIT %s""", (kind, limit)).fetchall()


def decide(conn: psycopg.Connection, caption_id: int, status: str, note: str = "") -> None:
    if status not in ("approved", "rejected"):
        raise ValueError("status must be approved or rejected")
    conn.execute(
        """UPDATE approval SET status=%s, decision_note=%s, decided_at=now()
           WHERE item_type='caption' AND item_id=%s""",
        (status, note.strip() or None, str(caption_id)))


def record_edit(conn: psycopg.Connection, caption_id: int, new_text: str, note: str = "") -> int:
    """Your edit = the original is rejected with your reason, and your version is saved as
    an approved caption linked to it. The pair (before, after) is the learning signal."""
    orig = conn.execute("SELECT pillar, product, fact_check, kind, hook_type FROM caption WHERE id=%s",
                        (caption_id,)).fetchone()
    decide(conn, caption_id, "rejected", f"edited by owner. {note}".strip())
    new_id, _ = add_caption(conn, new_text, pillar=orig["pillar"], product=orig["product"],
                            source="owner_edit", fact_check=orig["fact_check"],
                            parent_id=caption_id,
                            kind=orig["kind"], hook_type=orig["hook_type"])
    conn.execute(
        """INSERT INTO approval (item_type, item_id, summary, status, decided_at, decision_note)
           VALUES ('caption', %s, %s, 'approved', now(), 'owner edit')
           ON CONFLICT (item_type, item_id) DO UPDATE
           SET status='approved', decided_at=now(), decision_note='owner edit'""",
        (str(new_id), new_text.strip()[:200]))
    return new_id


def review(conn: psycopg.Connection, limit: int = 10,
           ask: Callable[[str], str] = input, show: Callable[[str], None] = print,
           kind: str = "caption") -> dict:
    """Walk through pending captions one at a time, newest batch first. a=approve r=reject e=edit s=skip q=quit."""
    stats = {"approved": 0, "rejected": 0, "edited": 0, "skipped": 0}
    items = pending(conn, limit, kind)
    if not items:
        show("Nothing waiting for review.")
        return stats
    for i, c in enumerate(items, 1):
        label = c["hook_type"] if kind == "hook" else c["pillar"]
        show(f"\n[{i}/{len(items)}]  score {c['score']}  ({label})")
        show(f"    {c['text']}")
        if c["score_reasons"]:
            show(f"    notes: {'; '.join(c['score_reasons'])}")
        if c["fact_check"]:
            show("    (states a fact: must still be true on the day it's posted)")
        choice = ask("  a = approve, r = reject, e = edit, s = skip, q = quit: ").strip().lower()
        if choice == "q":
            break
        if choice == "a":
            decide(conn, c["id"], "approved")
            stats["approved"] += 1
        elif choice == "r":
            why = ask("  why? (one line, helps it learn): ")
            decide(conn, c["id"], "rejected", why)
            stats["rejected"] += 1
        elif choice == "e":
            new = ask("  type your version: ").strip()
            if new:
                why = ask("  what was wrong with the original? (optional): ")
                record_edit(conn, c["id"], new, why)
                stats["edited"] += 1
            else:
                stats["skipped"] += 1
        else:
            stats["skipped"] += 1
    return stats


def summary(conn: psycopg.Connection) -> dict:
    row = conn.execute(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE c.blocked) AS blocked,
                  count(*) FILTER (WHERE a.status='pending') AS pending,
                  count(*) FILTER (WHERE a.status='approved') AS approved,
                  count(*) FILTER (WHERE a.status='rejected') AS rejected
           FROM caption c LEFT JOIN approval a
             ON a.item_type='caption' AND a.item_id = c.id::text""").fetchone()
    return dict(row)


def feedback_report(conn: psycopg.Connection) -> str:
    """Everything you decided, with your reasons, plus your quiz profile. Paste-safe:
    it contains only caption text and your notes, nothing secret."""
    from onewrld import quiz

    out = ["ONEWRLD VOICE FEEDBACK", "", "== voice quiz =="]
    prof = quiz.profile(conn)
    out += [f"  {l}" for l in prof] if prof else ["  (quiz not taken)"]
    for status in ("approved", "rejected"):
        rows = conn.execute(
            """SELECT c.text, c.pillar, a.decision_note FROM approval a
               JOIN caption c ON c.id = a.item_id::bigint
               WHERE a.item_type='caption' AND a.status=%s ORDER BY a.decided_at""",
            (status,)).fetchall()
        out += ["", f"== {status} ({len(rows)}) =="]
        for r in rows:
            note = f"   <- {r['decision_note']}" if r["decision_note"] else ""
            out.append(f"  [{r['pillar']}] {r['text']}{note}")
    return "\n".join(out)


def import_hooks(conn: psycopg.Connection, path: Path) -> dict[str, int]:
    """Load the hook library (brand/hooks.toml). Same scoring and approval as captions."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    stats = {"new": 0, "already_had": 0, "to_review": 0, "blocked": 0}
    for item in data["hooks"]:
        hid, created = add_caption(conn, item["text"], pillar="hook", product=item.get("product"),
                                   fact_check=bool(item.get("fact_check")), kind="hook",
                                   hook_type=item.get("type"))
        if not created:
            stats["already_had"] += 1
            continue
        stats["new"] += 1
        row = conn.execute("SELECT blocked, score FROM caption WHERE id=%s", (hid,)).fetchone()
        stats["blocked" if row["blocked"] else "to_review"] += 1
    return stats
