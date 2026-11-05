"""Command line: the buttons you press. Run `python -m onewrld --help` to see them all.

Safety and status:
  health                 show whether everything is OK
  status                 show mode + kill switch in one line
  kill  "reason"         STOP all posting and spending immediately
  resume "reason"        turn the kill switch back off
  test                   run every automated test

Database and jobs:
  migrate                create/update the database tables (safe to run any time)
  jobs                   show the job queue: counts and the 10 latest jobs
  worker                 run queued jobs (stops after --max-jobs or --max-seconds)
  alerts                 show open alerts;  ack ID  marks one as seen
  send-alerts            email any new alerts now (normally the worker does this)
  test-email             send yourself a test email
  phase1-check           the Phase 1 acceptance test (runs every drill)
  repair-schema --yes    one-time fix for bug M-004 (moves you off misplaced tables)
  diagnose               a paste-safe report (no secrets) for Claude when something fails

Brand Brain (Phase 2):
  quiz                   the voice quiz (this-or-that pairs); `voice` shows your profile
  captions import        load caption files from brand/ and score them
  captions review        approve / reject / edit captions waiting for you (10 at a time)
  captions list          show captions with scores and status
  captions score "text"  score any caption against the brand rules
  captions feedback      your decisions + reasons + quiz profile (paste to Claude)
  hooks review           approve / reject opening lines (the hook library)
  shotlist               build a shoot-day shot list (--minutes 120)

Video Studio (Phase 3):
  render-test            make a sample clip and render it + 3 variants (see the quality now)
  render FILE            render your clip: main version + variants, quality-checked
                         options: --variants 3  --caption "text"  --seconds 30
                                  --talk   (talking clip: word-by-word captions + pauses cut)
  transcribe FILE        show the words the speech model hears, and how long it took
  renders                list recent renders with quality-check results

Volume Engine (Phase 4B):
  pull-products          download your in-stock product photos from the store
  batch                  turn every photo and clip in media/products + media/inbox into
                         finished videos (main + variants), with product-matched captions

Distribution (Phase 5):
  schedule               plan the next 7 days of posts across all platforms (--days N)
  posts                  list upcoming posts;  posts review  to approve them
  kit                    export today's approved posts as a folder to post from (--date YYYY-MM-DD)
  posted N               mark post N as posted (after you post it by hand)  --url optional

Demos (nothing real is ever posted):
  demo-action            simulate one outward action directly
  demo-job "text"        queue a fake post job (run `worker` to process it)
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import uuid

from onewrld import health, safety
from onewrld.config import ConfigError, load_settings
from onewrld.errors import HaltedError, OnewrldError
from onewrld.logging_setup import setup_logging

ICONS = {health.PASS: "[ OK ]", health.WARN: "[WARN]", health.FAIL: "[FAIL]"}


def _cmd_health(settings) -> int:
    results = health.run_all(settings)
    for r in results:
        print(f"{ICONS[r.status]} {r.name:<12} {r.detail}")
    failed = [r for r in results if r.status == health.FAIL]
    print("\nOverall:", "FAIL" if failed else "OK")
    return 1 if failed else 0


def _cmd_status(settings) -> int:
    halted, reason = safety.halt_status(settings)
    print(f"mode={settings.mode}  kill_switch={'ON (' + str(reason) + ')' if halted else 'off'}")
    return 0


def _cmd_demo_action(settings) -> int:
    try:
        result = safety.outward_action(
            settings,
            "demo_post",
            lambda: "posted (demo; nothing real happened)",
            details={"platform": "demo"},
        )
    except HaltedError as e:
        print(f"Blocked: {e}")
        return 2
    print("Result:", result if result is not None else "simulated only (dry run)")
    return 0


def _cmd_migrate(settings) -> int:
    from onewrld import db

    applied = db.migrate(settings)
    print("Applied: " + ", ".join(applied) if applied else "Database already up to date.")
    return 0


def _cmd_jobs(settings) -> int:
    from onewrld import db, jobs

    with db.connect(settings) as conn:
        counts = jobs.job_counts(conn)
        print("Queue:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "empty")
        rows = conn.execute(
            """SELECT id, kind, status, attempts, max_attempts, last_error
               FROM job ORDER BY id DESC LIMIT 10"""
        ).fetchall()
    for r in rows:
        err = f"  last error: {r['last_error'][:80]}" if r["last_error"] else ""
        print(f"  #{r['id']:<5} {r['kind']:<12} {r['status']:<8} "
              f"attempt {r['attempts']}/{r['max_attempts']}{err}")
    return 0


def _cmd_worker(settings, max_jobs: int, max_seconds: int) -> int:
    from onewrld.worker import run_worker

    stats = run_worker(settings, max_jobs=max_jobs, max_seconds=max_seconds)
    print("Worker result:", dict(stats) or "nothing to do")
    return 0


def _cmd_demo_job(settings, text: str) -> int:
    from onewrld import db, jobs

    with db.connect(settings) as conn:
        job_id, created = jobs.enqueue(
            conn, "demo.post", {"text": text}, idempotency_key=f"demo:{uuid.uuid4()}"
        )
    print(f"Queued job #{job_id}. Run `python -m onewrld worker` to process it.")
    return 0


def _cmd_alerts(settings) -> int:
    from onewrld import alerts, db

    with db.connect(settings) as conn:
        rows = alerts.open_alerts(conn)
    if not rows:
        print("No open alerts.")
    for r in rows:
        print(f"  #{r['id']:<5} [{r['severity']}] {r['source']}: {r['message']}  "
              f"({r['created_at']:%Y-%m-%d %H:%M})")
    return 0


def _cmd_ack(settings, alert_id: int) -> int:
    from onewrld import alerts, db

    with db.connect(settings) as conn:
        ok = alerts.acknowledge(conn, alert_id)
    print(f"Alert #{alert_id} marked as seen." if ok else f"No open alert #{alert_id}.")
    return 0 if ok else 1


def _cmd_send_alerts(settings) -> int:
    from onewrld import db, notify

    with db.connect(settings) as conn:
        outcome = notify.flush_alert_emails(settings, conn)
    print({"sent": "Alert email sent.", "nothing": "No new alerts to email.",
           "not_configured": "Email not set up yet (RUNBOOK section 9).",
           "rate_limited": "Held back by the email cap; will go out later.",
           "busy": "Another worker is sending right now.",
           "failed": "Sending failed; see the log."}[outcome])
    return 0 if outcome in ("sent", "nothing", "rate_limited", "busy") else 1


def _cmd_test_email(settings) -> int:
    from onewrld import db, notify

    if settings.database_url:
        with db.connect(settings) as conn:
            notify.send_test_email(settings, conn)
    else:
        notify.send_test_email(settings)
    print(f"Test email sent to {settings.alert_email}. Check your inbox (and spam).")
    return 0


def _cmd_repair_schema(settings, yes: bool) -> int:
    from onewrld import db

    stray = db.misplaced_tables(settings, "public")
    if not stray:
        print("Nothing to repair: no misplaced tables in 'public'.")
        return 0
    print("Found ONEWRLD tables in the wrong place ('public'): " + ", ".join(stray))
    print("They only hold Phase 1 demo/test data. They will be removed and recreated in "
          f"'{settings.db_schema}'.")
    if not yes:
        print("Run again with --yes to do it:  python -m onewrld repair-schema --yes")
        return 1
    db.remove_misplaced_tables(settings, "public")
    applied = db.migrate(settings)
    print(f"Done. Removed {len(stray)} misplaced table(s); created: {', '.join(applied) or 'none'}")
    return 0


def _cmd_quiz(settings) -> int:
    from onewrld import db, quiz

    with db.connect(settings) as conn:
        n = quiz.run(conn)
        print(f"Saved {n} answer(s). Your voice profile:")
        for line in quiz.profile(conn):
            print("  " + line)
    return 0


def _cmd_voice(settings) -> int:
    from onewrld import db, quiz

    with db.connect(settings) as conn:
        lines = quiz.profile(conn)
    print("\n".join("  " + l for l in lines) if lines else "No quiz answers yet. Run `quiz`.")
    return 0


def _cmd_captions(settings, action: str, text: str | None, limit: int) -> int:
    from onewrld import brand, captions, db

    if action == "score":
        if not text:
            print('Usage: python -m onewrld captions score "your caption"')
            return 1
        s = brand.score_caption(text)
        verdict = "BLOCKED" if s.blocked else ("passes" if s.passes else
                                              f"below the quality floor ({brand.QUALITY_FLOOR})")
        print(f"Score {s.score}: {verdict}")
        for r in s.reasons:
            print("  - " + r)
        return 0
    with db.connect(settings) as conn:
        if action == "import":
            files = sorted(brand.BRAND_DIR.glob("captions_*.toml"))
            for f in files:
                st = captions.import_file(conn, f)
                print(f"{f.name}: {st['new']} new ({st['to_review']} to review, "
                      f"{st['blocked']} blocked, {st['below_floor']} below floor), "
                      f"{st['already_had']} already imported")
            hooks_file = brand.BRAND_DIR / "hooks.toml"
            if hooks_file.exists():
                st = captions.import_hooks(conn, hooks_file)
                print(f"hooks.toml: {st['new']} new hooks ({st['to_review']} to review), "
                      f"{st['already_had']} already imported. Review: python -m onewrld hooks review")
            return 0
        if action == "review":
            st = captions.review(conn, limit=limit)
            print(f"\nDone: {st['approved']} approved, {st['rejected']} rejected, "
                  f"{st['edited']} edited, {st['skipped']} skipped.")
            return 0
        if action == "feedback":
            print(captions.feedback_report(conn))
            return 0
        if action == "list":
            rows = conn.execute(
                """SELECT c.id, c.score, c.blocked, coalesce(a.status, '-') AS status, c.text
                   FROM caption c LEFT JOIN approval a
                     ON a.item_type='caption' AND a.item_id=c.id::text
                   ORDER BY c.id LIMIT %s""", (limit,)).fetchall()
            for r in rows:
                tag = "BLOCKED" if r["blocked"] else r["status"]
                print(f"  #{r['id']:<4} {r['score']:>3}  {tag:<9} {r['text'][:80]}")
            print("Totals:", captions.summary(conn))
            return 0
    return 1


def _print_renders(rows) -> None:
    for r in rows:
        sp = r["spec"]
        tag = "PASS" if r["qc_passed"] else "FAIL"
        bits = [sp["look"]] + ([f"zoom {sp['zoom']}"] if sp["zoom"] > 1 else []) + \
               ([f"crop {sp['crop_x']}"] if sp["crop_x"] != 0.5 else [])
        print(f"  [{tag}] {Path(r['output_path']).name}  ({', '.join(bits)})")
        if sp.get("caption"):
            print(f"         caption: {sp['caption']}")
        if not r["qc_passed"] and r["qc"]:
            bad = [k for k, ok in r["qc"]["checks"].items() if not ok]
            print(f"         failed: {', '.join(bad)}")


def _cmd_render(settings, file: str | None, variants: int, caption: str | None,
                seconds: float, talk: bool = False) -> int:
    from onewrld import db, studio, videos
    from onewrld.worker import run_worker

    studio.require_ffmpeg()
    if talk:
        from onewrld import speech
        if not speech.speech_available():
            print(speech.install_hint())
            return 1
    if file is None:  # render-test
        src = studio.make_test_clip(settings.root / "media" / "test_clip.mp4")
        print(f"Made a sample clip: {src}")
    else:
        src = Path(file)
    with db.connect(settings) as conn:
        asset = videos.register_asset(conn, src)
        job_ids = videos.plan(conn, asset, variants, caption, seconds, talk)
    print(f"Rendering {len(job_ids)} version(s). This can take a few minutes...")
    run_worker(settings, max_jobs=len(job_ids), max_seconds=3600, only_ids=job_ids)
    with db.connect(settings) as conn:
        rows = conn.execute(
            """SELECT r.* FROM render r JOIN job j ON j.idempotency_key = 'render:' || r.render_key
               WHERE j.id = ANY(%s) ORDER BY r.id""", (job_ids,)).fetchall()
        dead = conn.execute("SELECT id, last_error FROM job WHERE id = ANY(%s) AND status='dead'",
                            (job_ids,)).fetchall()
    _print_renders(rows)
    for d in dead:
        print(f"  job #{d['id']} failed: {d['last_error'][:200]}")
    print(f"\nVideos are in: {videos.renders_dir(settings)}")
    return 0 if rows and all(r["qc_passed"] for r in rows) and not dead else 1


def _cmd_transcribe(settings, file: str) -> int:
    import time
    from onewrld import speech, studio, videos

    src = Path(file)
    if not speech.speech_available():
        print(speech.install_hint())
        return 1
    t0 = time.monotonic()
    words = speech.transcribe(src, videos.renders_dir(settings) / ".transcripts",
                              studio.file_sha(src))
    took = time.monotonic() - t0
    dur = studio.probe(src)["duration"]
    segs = speech.keep_segments(words, dur)
    kept = sum(e - s for s, e in segs)
    print(" ".join(w.text for w in words))
    print(f"\n{len(words)} words in a {dur:.0f}s clip; transcribed in {took:.0f}s "
          f"(cached for next time). Cutting pauses would keep {kept:.0f}s of {dur:.0f}s.")
    return 0


def _cmd_pull_products(settings) -> int:
    from onewrld import products

    paths = products.pull_images(settings)
    print(f"{len(paths)} product photo(s) ready in {products.products_dir(settings)}")
    return 0


def _cmd_batch(settings, variants: int, include_photos: bool = False) -> int:
    from onewrld import db, studio, videos
    from onewrld.worker import run_worker

    studio.require_ffmpeg()
    videos.inbox_dir(settings).mkdir(parents=True, exist_ok=True)
    with db.connect(settings) as conn:
        plan = videos.plan_batch(conn, settings, variants, include_photos)
    ids = plan["job_ids"]
    if not ids:
        print("Nothing to render. Put your video clips in "
              f"{videos.inbox_dir(settings)}")
        return 0
    print(f"Rendering {len(ids)} video(s). Already-made ones are reused, so re-running is cheap.")
    run_worker(settings, max_jobs=len(ids), max_seconds=4 * 3600, only_ids=ids)
    with db.connect(settings) as conn:
        rows = conn.execute(
            """SELECT r.* FROM render r JOIN job j ON j.idempotency_key = 'render:' || r.render_key
               WHERE j.id = ANY(%s) ORDER BY r.id""", (ids,)).fetchall()
        dead = conn.execute("SELECT id, last_error FROM job WHERE id = ANY(%s) AND status='dead'",
                            (ids,)).fetchall()
    passed = sum(1 for r in rows if r["qc_passed"])
    print(f"\n{passed} of {len(ids)} videos passed the quality check.")
    for d in dead:
        print(f"  job #{d['id']} failed: {d['last_error'][:200]}")
    issues = videos.similarity_report(rows)
    print("Similarity check: " + ("no near-duplicates." if not issues else f"{len(issues)} near-duplicate pair(s):"))
    for i in issues:
        print("  " + i)
    if plan["uncaptioned"]:
        print(f"\n{len(plan['uncaptioned'])} file(s) have no approved caption for their product yet, "
              "so they rendered without on-screen text:")
        for u in plan["uncaptioned"][:10]:
            print("  " + u)
        print("Fix: python -m onewrld captions import   then   python -m onewrld captions review")
    print(f"\nVideos are in: {videos.renders_dir(settings)}")
    return 0 if passed == len(ids) and not dead else 1


def _cmd_schedule(settings, days: int) -> int:
    from datetime import datetime
    from onewrld import db, distribution

    with db.connect(settings) as conn:
        distribution.expire_missed(conn)
        today = datetime.now(distribution.tz()).date()
        ids = distribution.schedule(conn, today, days)
        n_ready = conn.execute("SELECT count(*) AS n FROM render WHERE qc_passed").fetchone()["n"]
    print(f"Planned {len(ids)} new post(s) over the next {days} days "
          f"(from {n_ready} finished videos).")
    if not ids:
        print("Nothing new to plan: every slot is filled, or there are no unused finished videos.")
        print("Make more with `batch` or `render`, then run `schedule` again.")
    else:
        print("Next: python -m onewrld posts review")
    return 0


def _cmd_posts(settings, action: str) -> int:
    from onewrld import db, distribution

    with db.connect(settings) as conn:
        if action == "review":
            st = distribution.review(conn)
            print(f"\nDone: {st['approved']} approved, {st['rejected']} rejected, {st['skipped']} skipped.")
            return 0
        rows = distribution.upcoming(conn)
    if not rows:
        print("No posts in the next 7 days. Run `schedule`.")
    zone = distribution.tz()
    day = None
    for r in rows:
        when = r["scheduled_at"].astimezone(zone)
        if when.date() != day:
            day = when.date()
            print(f"\n{when:%A %b %d}")
        first = r["caption_text"].splitlines()[0][:60]
        print(f"  {when:%I:%M %p}  {r['platform']:<10} #{r['id']:<5} {r['status']:<9} {first}")
    return 0


def _cmd_kit(settings, day_text: str | None) -> int:
    from datetime import date, datetime
    from onewrld import db, distribution

    day = date.fromisoformat(day_text) if day_text else datetime.now(distribution.tz()).date()
    with db.connect(settings) as conn:
        folder = distribution.export_kit(conn, settings, day)
    if folder is None:
        print(f"No approved posts for {day}. Run `schedule`, then `posts review`.")
        return 0
    print((folder / "README.txt").read_text(encoding="utf-8"))
    print(f"Open it with:  explorer {folder}")
    return 0


def _cmd_posted(settings, post_id: int, url: str | None) -> int:
    from onewrld import db, distribution

    with db.connect(settings) as conn:
        ok = distribution.mark_posted(conn, post_id, url)
    print(f"Post {post_id} marked as posted." if ok else
          f"Post {post_id} isn't approved (or doesn't exist). Check `posts`.")
    return 0 if ok else 1


def _cmd_renders(settings) -> int:
    from onewrld import db, videos

    with db.connect(settings) as conn:
        rows = videos.recent(conn)
    if not rows:
        print("No renders yet. Try: python -m onewrld render-test")
    _print_renders(rows)
    return 0


def _cmd_hooks(settings, limit: int) -> int:
    from onewrld import captions, db

    with db.connect(settings) as conn:
        st = captions.review(conn, limit=limit, kind="hook")
    print(f"\nDone: {st['approved']} approved, {st['rejected']} rejected, "
          f"{st['edited']} edited, {st['skipped']} skipped.")
    return 0


def _cmd_shotlist(settings, minutes: int, include_drop: bool) -> int:
    from datetime import date
    from onewrld import shotlist

    out = shotlist.write(settings.root, minutes, date.today(), include_drop)
    print(out.read_text(encoding="utf-8"))
    print(f"Saved to: {out}")
    return 0


def _cmd_test() -> int:
    return subprocess.call([sys.executable, "-m", "pytest", "-q", "-rs"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onewrld", description="ONEWRLD system controls")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="check that everything is OK")
    sub.add_parser("status", help="show mode and kill switch")
    k = sub.add_parser("kill", help="STOP all posting and spending")
    k.add_argument("reason", nargs="?", default="manual stop")
    r = sub.add_parser("resume", help="turn the kill switch off")
    r.add_argument("reason", help="why it is safe to resume")
    sub.add_parser("test", help="run all automated tests")
    sub.add_parser("migrate", help="create/update database tables")
    sub.add_parser("jobs", help="show the job queue")
    w = sub.add_parser("worker", help="run queued jobs (bounded)")
    w.add_argument("--max-jobs", type=int, default=25)
    w.add_argument("--max-seconds", type=int, default=300)
    sub.add_parser("alerts", help="show open alerts")
    a = sub.add_parser("ack", help="mark an alert as seen")
    a.add_argument("alert_id", type=int)
    sub.add_parser("send-alerts", help="email new alerts now")
    sub.add_parser("test-email", help="send yourself a test email")
    sub.add_parser("phase1-check", help="Phase 1 acceptance test")
    sub.add_parser("diagnose", help="paste-safe problem report")
    sub.add_parser("render-test", help="render a sample clip + 3 variants")
    rn = sub.add_parser("render", help="render a clip + variants")
    rn.add_argument("file")
    rn.add_argument("--variants", type=int, default=3)
    rn.add_argument("--caption")
    rn.add_argument("--seconds", type=float, default=30.0)
    rn.add_argument("--talk", action="store_true")
    tr = sub.add_parser("transcribe", help="show what the speech model hears")
    tr.add_argument("file")
    sub.add_parser("renders", help="list recent renders")
    sub.add_parser("pull-products", help="download in-stock product photos")
    sc = sub.add_parser("schedule", help="plan posts across platforms")
    sc.add_argument("--days", type=int, default=7)
    ps = sub.add_parser("posts", help="list upcoming posts, or `posts review`")
    ps.add_argument("action", nargs="?", default="list", choices=["list", "review"])
    kt = sub.add_parser("kit", help="export a day's approved posts to a folder")
    kt.add_argument("--date")
    pd = sub.add_parser("posted", help="mark a post as posted")
    pd.add_argument("post_id", type=int)
    pd.add_argument("--url")
    bt = sub.add_parser("batch", help="render everything in media/products and media/inbox")
    bt.add_argument("--variants", type=int, default=3)
    bt.add_argument("--photos", action="store_true", help="also turn still photos into videos (off by default)")
    hk = sub.add_parser("hooks", help="review the hook library")
    hk.add_argument("action", choices=["review"])
    hk.add_argument("--limit", type=int, default=20)
    sl = sub.add_parser("shotlist", help="build a shoot-day shot list")
    sl.add_argument("--minutes", type=int, default=120)
    sl.add_argument("--drop", action="store_true", help="include new-drop tease formats")
    sub.add_parser("quiz", help="voice quiz")
    sub.add_parser("voice", help="show your voice profile")
    cp = sub.add_parser("captions", help="caption bank: import, review, list, score")
    cp.add_argument("action", choices=["import", "review", "list", "score", "feedback"])
    cp.add_argument("text", nargs="?")
    cp.add_argument("--limit", type=int, default=10)
    rs = sub.add_parser("repair-schema", help="one-time fix for bug M-004")
    rs.add_argument("--yes", action="store_true")
    sub.add_parser("demo-action", help="simulate a post to see the safety gates")
    d = sub.add_parser("demo-job", help="queue a fake post job")
    d.add_argument("text", nargs="?", default="hello from the queue")
    args = parser.parse_args(argv)

    if args.command == "test":
        return _cmd_test()

    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"Config problem: {e}")
        return 1
    setup_logging(settings.log_dir)

    try:
        if args.command == "health":
            return _cmd_health(settings)
        if args.command == "status":
            return _cmd_status(settings)
        if args.command == "kill":
            safety.halt(settings, args.reason)
            print("Kill switch ON. All posting and spending is blocked.")
            return 0
        if args.command == "resume":
            safety.resume(settings, args.reason)
            print("Kill switch off.")
            return 0
        if args.command == "demo-action":
            return _cmd_demo_action(settings)
        if args.command == "migrate":
            return _cmd_migrate(settings)
        if args.command == "jobs":
            return _cmd_jobs(settings)
        if args.command == "worker":
            return _cmd_worker(settings, args.max_jobs, args.max_seconds)
        if args.command == "demo-job":
            return _cmd_demo_job(settings, args.text)
        if args.command == "alerts":
            return _cmd_alerts(settings)
        if args.command == "ack":
            return _cmd_ack(settings, args.alert_id)
        if args.command == "send-alerts":
            return _cmd_send_alerts(settings)
        if args.command == "test-email":
            return _cmd_test_email(settings)
        if args.command == "render-test":
            return _cmd_render(settings, None, 3, None, 30.0)
        if args.command == "render":
            return _cmd_render(settings, args.file, max(0, min(args.variants, 5)),
                               args.caption, args.seconds, args.talk)
        if args.command == "transcribe":
            return _cmd_transcribe(settings, args.file)
        if args.command == "renders":
            return _cmd_renders(settings)
        if args.command == "schedule":
            return _cmd_schedule(settings, max(1, min(args.days, 30)))
        if args.command == "posts":
            return _cmd_posts(settings, args.action)
        if args.command == "kit":
            return _cmd_kit(settings, args.date)
        if args.command == "posted":
            return _cmd_posted(settings, args.post_id, args.url)
        if args.command == "pull-products":
            return _cmd_pull_products(settings)
        if args.command == "batch":
            return _cmd_batch(settings, max(0, min(args.variants, 5)), args.photos)
        if args.command == "hooks":
            return _cmd_hooks(settings, max(1, args.limit))
        if args.command == "shotlist":
            return _cmd_shotlist(settings, max(30, min(args.minutes, 480)), args.drop)
        if args.command == "quiz":
            return _cmd_quiz(settings)
        if args.command == "voice":
            return _cmd_voice(settings)
        if args.command == "captions":
            limit = args.limit if args.action != "list" or args.limit != 10 else 100
            return _cmd_captions(settings, args.action, args.text, limit)
        if args.command == "diagnose":
            from onewrld import diagnose

            print(diagnose.collect(settings))
            print("\nSaved to diagnose.txt. It contains no passwords; safe to paste to Claude.")
            return 0
        if args.command == "repair-schema":
            return _cmd_repair_schema(settings, args.yes)
        if args.command == "phase1-check":
            from onewrld import acceptance

            return 0 if acceptance.run(settings) else 1
    except OnewrldError as e:
        # Known problems get a plain message, not a wall of Python traceback.
        print(f"Problem: {e}")
        return 1
    return 1
