"""Brand Brain: scorer, caption import/review, voice quiz."""

import pytest

from onewrld import brand, captions, quiz


# --- scorer (no database) -----------------------------------------------------

@pytest.mark.parametrize("text", [
    "Icarus fell because he tried. Most people never leave the ground.",
    "480 GSM cotton. You feel the weight the second you pick it up.",
    "Fly anyway.",
])
def test_on_brand_captions_pass(text):
    s = brand.score_caption(text)
    assert s.passes and s.score >= 90, s.reasons


@pytest.mark.parametrize("text,phrase", [
    ("No days off. Built different.", "no days off"),
    ("Last chance to grab it!!", "last chance"),
    ("This hoodie is a game-changer", "game-changer"),
    ("LETS GO new drop", "lets go"),
    ("Don’t miss out on this", "don't miss out"),   # curly apostrophe still caught
])
def test_banned_phrases_block(text, phrase):
    s = brand.score_caption(text)
    assert s.blocked and s.score == 0
    assert any(phrase in r for r in s.reasons)


def test_whole_words_only():
    # 'goat' is banned but 'goatee' must not trigger it
    assert not brand.score_caption("Shot with a goatee and a hoodie.").blocked


def test_soft_rules_lower_the_score():
    s = brand.score_caption("New HOODIE drop!! 🔥 💯 🙌 #a #b #c #d")
    assert not s.blocked and s.score < brand.QUALITY_FLOOR
    text = " ".join(s.reasons)
    for bit in ("exclamation", "emojis", "hashtags", "all-caps"):
        assert bit in text


def test_allowed_caps():
    assert brand.score_caption("ONEWRLD. 480 GSM. Sizes S to 2XL.").score == 100


def test_seed_bank_borderline_captions_are_caught():
    import tomllib
    data = tomllib.loads((brand.BRAND_DIR / "captions_fall_of_icarus.toml").read_text(encoding="utf-8"))
    blocked = [c["text"] for c in data["captions"] if brand.score_caption(c["text"]).blocked]
    assert "No days off. Built different. 🔥🔥" in blocked
    assert "Last chance to grab Fall of Icarus before it's gone!!" in blocked


# --- captions with database -------------------------------------------------

def test_import_is_idempotent_and_routes_by_score(conn):
    path = brand.BRAND_DIR / "captions_fall_of_icarus.toml"
    first = captions.import_file(conn, path)
    assert first["new"] >= 25 and first["blocked"] >= 2 and first["to_review"] >= 20
    second = captions.import_file(conn, path)
    assert second["new"] == 0 and second["already_had"] == first["new"]
    # blocked captions never reach the review queue
    assert all(not c["text"].startswith("No days off") for c in captions.pending(conn, 100))


def _answers(*replies):
    it = iter(replies)
    return lambda prompt: next(it)


def test_review_records_approve_reject_and_reason(conn):
    a, _ = captions.add_caption(conn, "Fly anyway.")
    b, _ = captions.add_caption(conn, "Some people watch the sun. Some fly at it.")
    out = []
    # pending is ordered by score, then newest first; both score 100 -> b first, then a
    st = captions.review(conn, ask=_answers("r", "too poetic", "a"), show=out.append)
    assert st["approved"] == 1 and st["rejected"] == 1
    rows = {r["item_id"]: r for r in conn.execute(
        "SELECT item_id, status, decision_note FROM approval WHERE item_type='caption'")}
    assert rows[str(a)]["status"] == "approved"
    assert rows[str(b)]["status"] == "rejected" and rows[str(b)]["decision_note"] == "too poetic"


def test_edit_keeps_before_and_after(conn):
    orig, _ = captions.add_caption(conn, "Heavy hoodie. Heavier meaning.")
    st = captions.review(conn, ask=_answers("e", "Heavy hoodie. That's the whole pitch.",
                                            "second line was corny"), show=lambda m: None)
    assert st["edited"] == 1
    new = conn.execute("SELECT id, parent_id, source FROM caption WHERE parent_id=%s",
                       (orig,)).fetchone()
    assert new["source"] == "owner_edit"
    status = {r["item_id"]: r["status"] for r in conn.execute(
        "SELECT item_id, status FROM approval WHERE item_type='caption'")}
    assert status[str(orig)] == "rejected" and status[str(new["id"])] == "approved"


def test_quit_leaves_rest_pending(conn):
    captions.add_caption(conn, "Fly anyway.")
    captions.add_caption(conn, "Not for everyone. That's the point.")
    captions.review(conn, ask=_answers("q"), show=lambda m: None)
    assert len(captions.pending(conn)) == 2


# --- quiz -------------------------------------------------------------------

def test_quiz_saves_answers_and_profile(conn):
    n_pairs = len(quiz.load_pairs())
    replies = ["a", "b", "x-invalid", "both"] + ["n"] * (n_pairs - 3)
    n = quiz.run(conn, ask=_answers(*replies), show=lambda m: None)
    assert n == n_pairs
    prof = quiz.profile(conn)
    assert "product vs story: product" in prof and "length: long" in prof
    assert "i vs we: both" in prof


def test_quiz_rerun_replaces_answer(conn):
    pair = quiz.load_pairs()[0]
    quiz.save_answer(conn, pair, "a")
    quiz.save_answer(conn, pair, "b")
    rows = conn.execute("SELECT choice FROM quiz_answer").fetchall()
    assert [r["choice"] for r in rows] == ["b"]


def test_feedback_report_shows_decisions_and_reasons(conn):
    a, _ = captions.add_caption(conn, "Fly anyway.", pillar="story")
    b, _ = captions.add_caption(conn, "Burned once. Built twice.", pillar="story")
    captions.decide(conn, a, "approved")
    captions.decide(conn, b, "rejected", "corny")
    quiz.save_answer(conn, quiz.load_pairs()[0], "b")
    rep = captions.feedback_report(conn)
    assert "== approved (1) ==" in rep and "Fly anyway." in rep
    assert "Burned once. Built twice.   <- corny" in rep
    assert "product vs story: story" in rep


def test_batch2_fits_the_rules_and_avoids_rejected_angle():
    import tomllib
    data = tomllib.loads((brand.BRAND_DIR / "captions_fall_of_icarus_batch2.toml").read_text(encoding="utf-8"))
    bible = brand.load_bible()
    assert "Pride comes before the fall" in bible["collections"]["fall_of_icarus"]["meaning"]
    for c in data["captions"]:
        s = brand.score_caption(c["text"])
        assert s.passes and s.score >= 90, (c["text"], s.reasons)
        low = c["text"].lower()
        assert "fly anyway" not in low and "flew anyway" not in low  # L-001
