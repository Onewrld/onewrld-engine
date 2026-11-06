"""Affiliate Portal security: every rule is attacked here, as the people who'd break it.

Runs on a plain Postgres with a small stand-in for Supabase's login system (auth.users,
auth.uid(), the anon/authenticated roles). It REFUSES to run against a Supabase database,
so it can never touch your real logins.
"""

import uuid
from contextlib import contextmanager

import psycopg
import pytest

from onewrld import portal

STUB_AUTH = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY, email text);
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
  $$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
GRANT USAGE ON SCHEMA auth TO authenticated, anon;
GRANT EXECUTE ON FUNCTION auth.uid() TO authenticated, anon;
CREATE SCHEMA IF NOT EXISTS storage;
CREATE TABLE IF NOT EXISTS storage.buckets (id text PRIMARY KEY, name text, public boolean);
CREATE TABLE IF NOT EXISTS storage.objects (id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                                            bucket_id text, name text, owner uuid);
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
CREATE OR REPLACE FUNCTION storage.foldername(name text) RETURNS text[] LANGUAGE sql IMMUTABLE AS
  $$ SELECT (string_to_array(name, '/'))[1:array_length(string_to_array(name, '/'), 1) - 1] $$;
GRANT USAGE ON SCHEMA storage TO authenticated, anon;
GRANT SELECT, INSERT ON storage.objects TO authenticated;
"""


@pytest.fixture
def pdb(db_settings):
    """(connection, portal schema) with the portal set up in a throwaway schema."""
    if "supabase" in db_settings.database_url:
        pytest.skip("portal security tests only run on a local test database")
    from onewrld import db
    schema = f"ptest_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(db_settings.database_url, autocommit=True) as c:
        c.execute(STUB_AUTH)
        c.execute("DELETE FROM storage.objects")   # local stand-in only: start each test empty
        c.execute(f"CREATE SCHEMA {schema}")
        # behave like Supabase: new tables are granted to anon/authenticated by default
        c.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT ALL ON TABLES TO anon, authenticated")
        c.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT ALL ON SEQUENCES TO anon, authenticated")
    with db.connect(db_settings) as conn:
        assert portal.setup(conn, schema) == ["0001_portal.sql", "0002_storage.sql"]
        assert portal.setup(conn, schema) == []          # safe to run again
        try:
            yield conn, schema
        finally:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")
            conn.execute("DELETE FROM storage.objects")


def signup(conn, email):
    """A person logs in for the first time (Supabase creates the auth.users row)."""
    uid = uuid.uuid4()
    conn.execute("INSERT INTO auth.users (id, email) VALUES (%s, %s)", (uid, email))
    return uid


@contextmanager
def as_user(conn, uid):
    """Run statements exactly as the website would for this logged-in person."""
    with conn.transaction():
        conn.execute("SET LOCAL ROLE authenticated")
        conn.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (str(uid) if uid else "",))
        yield


@contextmanager
def as_anon(conn):
    with conn.transaction():
        conn.execute("SET LOCAL ROLE anon")
        yield


def upload(conn, s, uid, key, consent=True):
    conn.execute(f"""INSERT INTO {s}.submissions (affiliate_id, storage_key, consent_at)
                     VALUES (%s, %s, {'now()' if consent else 'NULL'})""", (uid, key))


@pytest.fixture
def team(pdb):
    conn, s = pdb
    portal.invite(conn, "Blake@Example.com", "Blake", code="BLAKE10", link="https://onewrld.us/?ref=blake", schema=s)
    portal.invite(conn, "jess@example.com", "Jess", code="JESS10", schema=s)
    portal.invite(conn, "boss@example.com", "Adam", schema=s)
    ids = {n: signup(conn, f"{n}@example.com") for n in ("blake", "jess", "boss")}
    assert portal.make_owner(conn, "boss@example.com", schema=s)
    return conn, s, ids


def test_only_invited_emails_get_an_account(team):
    conn, s, ids = team
    stranger = signup(conn, "stranger@example.com")
    assert conn.execute(f"SELECT count(*) AS n FROM {s}.profiles").fetchone()["n"] == 3
    with pytest.raises(psycopg.errors.InsufficientPrivilege):   # RLS blocks the insert
        with as_user(conn, stranger):
            upload(conn, s, stranger, "x/stranger.mp4")


def test_upload_needs_consent_and_must_be_your_own(team):
    conn, s, ids = team
    with as_user(conn, ids["blake"]):
        upload(conn, s, ids["blake"], "blake/1.mp4")
    with pytest.raises(psycopg.errors.Error):
        with as_user(conn, ids["blake"]):
            upload(conn, s, ids["blake"], "blake/2.mp4", consent=False)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with as_user(conn, ids["blake"]):
            upload(conn, s, ids["jess"], "pretend-to-be-jess.mp4")


def test_affiliates_only_see_their_own_uploads_owner_sees_all(team):
    conn, s, ids = team
    for name in ("blake", "jess"):
        with as_user(conn, ids[name]):
            upload(conn, s, ids[name], f"{name}/1.mp4")
    with as_user(conn, ids["blake"]):
        keys = [r["storage_key"] for r in conn.execute(f"SELECT storage_key FROM {s}.submissions")]
    assert keys == ["blake/1.mp4"]
    with as_user(conn, ids["boss"]):
        assert conn.execute(f"SELECT count(*) AS n FROM {s}.submissions").fetchone()["n"] == 2
    with as_user(conn, ids["blake"]):  # can't see who else is on the team either
        assert [r["display_name"] for r in conn.execute(f"SELECT display_name FROM {s}.profiles")] == ["Blake"]


def _pack(conn, s, uploader):
    sub = conn.execute(f"""INSERT INTO {s}.submissions (affiliate_id, storage_key, consent_at)
                           VALUES (%s, %s, now()) RETURNING id""", (uploader, f"k{uuid.uuid4().hex}")).fetchone()["id"]
    return conn.execute(f"""INSERT INTO {s}.packs (submission_id, video_key, caption_base)
                            VALUES (%s, 'packs/1.mp4', 'Heavy cotton sweats. Cut wide from the knee down.')
                            RETURNING id""", (sub,)).fetchone()["id"]


def test_only_the_owner_can_approve(team):
    conn, s, ids = team
    pk = _pack(conn, s, ids["blake"])
    with pytest.raises(psycopg.errors.RaiseException, match="only the owner"):
        with as_user(conn, ids["blake"]):
            conn.execute(f"SELECT {s}.approve_pack(%s, %s)", (pk, [ids["blake"]]))


def test_approve_assigns_with_each_affiliates_code_link_and_disclosure(team):
    conn, s, ids = team
    pk = _pack(conn, s, ids["blake"])
    with as_user(conn, ids["blake"]):   # not assigned yet: invisible to affiliates
        assert conn.execute(f"SELECT count(*) AS n FROM {s}.packs").fetchone()["n"] == 0
    with as_user(conn, ids["boss"]):
        n = conn.execute(f"SELECT {s}.approve_pack(%s, %s) AS n", (pk, [ids["blake"], ids["jess"]])).fetchone()["n"]
        again = conn.execute(f"SELECT {s}.approve_pack(%s, %s) AS n", (pk, [ids["blake"]])).fetchone()["n"]
    assert n == 2 and again == 0            # pressing twice never double-assigns
    with as_user(conn, ids["blake"]):
        rows = conn.execute(f"SELECT caption_final FROM {s}.assignments").fetchall()
        assert conn.execute(f"SELECT count(*) AS n FROM {s}.packs").fetchone()["n"] == 1
    cap = rows[0]["caption_final"]
    assert len(rows) == 1 and "https://onewrld.us/?ref=blake" in cap and "Code BLAKE10" in cap
    assert "#ad" in cap and "JESS10" not in cap


def test_inactive_affiliates_get_nothing(team):
    conn, s, ids = team
    portal.set_active(conn, "jess@example.com", False, schema=s)
    pk = _pack(conn, s, ids["blake"])
    with as_user(conn, ids["boss"]):
        assert conn.execute(f"SELECT {s}.approve_pack(%s, %s) AS n", (pk, [ids["jess"]])).fetchone()["n"] == 0


def test_rejected_pack_cannot_be_assigned(team):
    conn, s, ids = team
    pk = _pack(conn, s, ids["blake"])
    with as_user(conn, ids["boss"]):
        conn.execute(f"SELECT {s}.reject_pack(%s, 'too dark')", (pk,))
    with pytest.raises(psycopg.errors.RaiseException, match="rejected"):
        with as_user(conn, ids["boss"]):
            conn.execute(f"SELECT {s}.approve_pack(%s, %s)", (pk, [ids["blake"]]))


def test_mark_posted_only_on_your_own_assignment(team):
    conn, s, ids = team
    pk = _pack(conn, s, ids["blake"])
    with as_user(conn, ids["boss"]):
        conn.execute(f"SELECT {s}.approve_pack(%s, %s)", (pk, [ids["blake"], ids["jess"]]))
    jess_assignment = conn.execute(f"SELECT id FROM {s}.assignments WHERE affiliate_id=%s",
                                   (ids["jess"],)).fetchone()["id"]
    with as_user(conn, ids["blake"]):
        assert conn.execute(f"SELECT {s}.mark_posted(%s, '') AS ok", (jess_assignment,)).fetchone()["ok"] is False
    with as_user(conn, ids["jess"]):
        assert conn.execute(f"SELECT {s}.mark_posted(%s, 'https://tiktok.com/v/1') AS ok",
                            (jess_assignment,)).fetchone()["ok"] is True
    row = conn.execute(f"SELECT status, posted_url FROM {s}.assignments WHERE id=%s", (jess_assignment,)).fetchone()
    assert row["status"] == "posted" and row["posted_url"] == "https://tiktok.com/v/1"


def test_logged_out_visitors_see_nothing(team):
    conn, s, ids = team
    for table in ("profiles", "submissions", "packs", "assignments", "invites"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with as_anon(conn):
                conn.execute(f"SELECT * FROM {s}.{table}")


def test_invite_rejects_bad_email(pdb):
    from onewrld.errors import PermanentError
    conn, s = pdb
    with pytest.raises(PermanentError):
        portal.invite(conn, "not-an-email", "X", schema=s)


@pytest.mark.parametrize("sql", [
    "INSERT INTO {s}.packs (submission_id, video_key, caption_base) VALUES (1, 'x', 'x')",
    "INSERT INTO {s}.assignments (pack_id, affiliate_id, caption_final) VALUES (1, '{me}', 'x')",
    "UPDATE {s}.assignments SET status = 'posted'",
    "DELETE FROM {s}.submissions",
    "UPDATE {s}.profiles SET role = 'owner'",
    "INSERT INTO {s}.invites (email, display_name) VALUES ('friend@x.com', 'Friend')",
])
def test_affiliates_cannot_write_around_the_buttons(team, sql):
    conn, s, ids = team
    with as_user(conn, ids["blake"]):
        upload(conn, s, ids["blake"], "blake/keep.mp4")
    try:
        with as_user(conn, ids["blake"]):
            cur = conn.execute(sql.format(s=s, me=ids["blake"]))
            changed = cur.rowcount
    except psycopg.errors.InsufficientPrivilege:
        changed = 0  # blocked outright: good
    assert changed == 0
    assert conn.execute(f"SELECT role FROM {s}.profiles WHERE id=%s", (ids["blake"],)).fetchone()["role"] == "affiliate"
    assert conn.execute(f"SELECT count(*) AS n FROM {s}.submissions").fetchone()["n"] == 1



# --- video storage rules --------------------------------------------------------------

def _put(conn, bucket, name):
    conn.execute("INSERT INTO storage.objects (bucket_id, name) VALUES (%s, %s)", (bucket, name))


def _visible(conn, bucket):
    return sorted(r["name"] for r in conn.execute(
        "SELECT name FROM storage.objects WHERE bucket_id=%s", (bucket,)))


def test_affiliates_upload_only_into_their_own_folder(team):
    conn, s, ids = team
    with as_user(conn, ids["blake"]):
        _put(conn, "uploads", f"{ids['blake']}/clip1.mp4")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with as_user(conn, ids["blake"]):
            _put(conn, "uploads", f"{ids['jess']}/sneaky.mp4")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with as_user(conn, ids["blake"]):
            _put(conn, "packs", "packs/fake.mp4")     # only the engine writes finished posts


def test_affiliates_see_only_their_own_raw_clips(team):
    conn, s, ids = team
    for n in ("blake", "jess"):
        with as_user(conn, ids[n]):
            _put(conn, "uploads", f"{ids[n]}/{n}.mp4")
    with as_user(conn, ids["blake"]):
        assert _visible(conn, "uploads") == [f"{ids['blake']}/blake.mp4"]
    with as_user(conn, ids["boss"]):
        assert len(_visible(conn, "uploads")) == 2


def test_finished_post_files_only_for_assigned_affiliates(team):
    conn, s, ids = team
    pk = _pack(conn, s, ids["blake"])                # its video_key is 'packs/1.mp4'
    _put(conn, "packs", "packs/1.mp4")                # written by the engine (service role)
    with as_user(conn, ids["jess"]):
        assert _visible(conn, "packs") == []           # not assigned yet: can't even see it
    with as_user(conn, ids["boss"]):
        conn.execute(f"SELECT {s}.approve_pack(%s, %s)", (pk, [ids["jess"]]))
    with as_user(conn, ids["jess"]):
        assert _visible(conn, "packs") == ["packs/1.mp4"]
    with as_user(conn, ids["blake"]):
        assert _visible(conn, "packs") == []           # Blake wasn't sent this one


# --- creating logins through Supabase's admin API (no network: fake server) ---------------

class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_create_login_sends_confirmed_email_with_service_key(make_settings):
    s = make_settings(SUPABASE_URL="https://abc.supabase.co/", SUPABASE_SERVICE_ROLE_KEY="secret-key")
    seen = {}

    def opener(req, timeout=None):
        seen["url"], seen["auth"], seen["body"] = req.full_url, req.headers["Authorization"], req.data
        return _Resp()
    assert portal.create_login(s, "Blake@Example.com", opener) == "created"
    assert seen["url"] == "https://abc.supabase.co/auth/v1/admin/users"
    assert seen["auth"] == "Bearer secret-key"
    assert b'"email": "blake@example.com"' in seen["body"] and b'"email_confirm": true' in seen["body"]
    assert "secret-key" not in repr(s)          # never printed


def test_create_login_existing_user_is_fine_and_unconfigured_skips(make_settings):
    import io
    import urllib.error
    s = make_settings(SUPABASE_URL="https://abc.supabase.co", SUPABASE_SERVICE_ROLE_KEY="k")

    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 422, "x", {}, io.BytesIO(b'{"msg":"already registered"}'))
    assert portal.create_login(s, "a@b.com", opener) == "exists"
    from dataclasses import replace
    assert portal.create_login(replace(s, supabase_url="", supabase_service_key=""), "a@b.com") == "skipped"



def test_new_secret_keys_go_in_apikey_header_only(make_settings):
    s = make_settings(SUPABASE_URL="https://abc.supabase.co", SUPABASE_SERVICE_ROLE_KEY="sb_secret_abc123")
    seen = {}

    def opener(req, timeout=None):
        seen.update({k.lower(): v for k, v in req.header_items()})
        return _Resp()
    portal.create_login(s, "a@b.com", opener)
    assert seen["apikey"] == "sb_secret_abc123" and "authorization" not in seen
