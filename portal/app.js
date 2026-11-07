// ONEWRLD Team Portal. Plain JavaScript, no build step.
// Screens:
//   Affiliates: Upload · Ready to post · My uploads
//   Owner:      Approve · Uploads · Team · Upload
// Every action is also checked by the database's security rules (db/portal/*.sql), so this
// file only decides what to SHOW; it can't grant anyone more than the rules allow.
"use strict";

const cfg = window.PORTAL_CONFIG;
const sb = window.__FAKE_SUPABASE__ ||
  window.supabase.createClient(cfg.supabaseUrl, cfg.supabaseAnonKey);
const app = document.getElementById("app");
const tabsEl = document.getElementById("tabs");
let me = null;        // { user, profile }
let currentTab = null;

// ---------- small helpers ----------
function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v === true) n.setAttribute(k, "");
    else if (v !== false && v != null) n.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null) n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return n;
}
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._h); toast._h = setTimeout(() => t.classList.remove("show"), 2600);
}
function fail(err) { console.error(err); toast(err?.message || String(err)); }
function when(ts) { return ts ? new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : ""; }
function statusPill(s) {
  const cls = ["ready", "approved", "posted"].includes(s) ? "ok" : ["failed", "rejected"].includes(s) ? "bad" : "";
  const label = { uploaded: "waiting to be edited", processing: "being edited", ready: "edited", failed: "couldn't be edited",
                  rejected: "rejected", pending: "waiting for approval", approved: "approved", assigned: "ready to post", posted: "posted" }[s] || s;
  return el("span", { class: "status " + cls }, label);
}
async function signed(bucket, key, download = false) {
  if (!key) return null;
  const { data, error } = await sb.storage.from(bucket).createSignedUrl(key, 3600, download ? { download: true } : undefined);
  if (error) { console.warn(error); return null; }
  return data.signedUrl;
}
function safeName(name) { return name.toLowerCase().replace(/[^a-z0-9.\-_]+/g, "-").slice(-80); }

// ---------- start ----------
async function start() {
  const { data } = await sb.auth.getSession();
  sb.auth.onAuthStateChange((_event, session) => { if (!!session !== !!me) boot(session); });
  await boot(data.session);
}

async function boot(session) {
  if (!session) { me = null; tabsEl.hidden = true; document.getElementById("who").textContent = ""; return showLogin(); }
  const { data: profile, error } = await sb.from("profiles").select("*").eq("id", session.user.id).maybeSingle();
  if (error) return fail(error);
  if (!profile || !profile.active) return showNotOnTeam(session.user.email);
  me = { user: session.user, profile };
  document.getElementById("who").textContent = profile.display_name + (profile.role === "owner" ? " · owner" : "");
  const tabs = profile.role === "owner"
    ? [["approve", "Approve"], ["uploads", "Uploads"], ["team", "Team"], ["upload", "Upload"]]
    : [["upload", "Upload"], ["ready", "Ready to post"], ["mine", "My uploads"]];
  tabsEl.replaceChildren(...tabs.map(([id, label]) =>
    el("button", { "data-tab": id, onclick: () => show(id) }, label, el("span", { class: "count", id: "count-" + id }))));
  tabsEl.append(el("button", { onclick: () => sb.auth.signOut() }, "Log out"));
  tabsEl.hidden = false;
  show(tabs[0][0]);
}

function show(tab) {
  currentTab = tab;
  for (const b of tabsEl.querySelectorAll("button[data-tab]")) b.classList.toggle("active", b.dataset.tab === tab);
  const screens = { upload: showUpload, ready: showReady, mine: showMine, approve: showApprove, uploads: showAllUploads, team: showTeam };
  screens[tab]().catch(fail);
}

// ---------- login ----------
function showLogin() {
  const email = el("input", { type: "email", placeholder: "you@email.com", autocomplete: "email", required: true });
  const btn = el("button", { class: "primary wide", type: "submit" }, "Send me a login link");
  const msg = el("p", { class: "muted" });
  const form = el("form", { class: "card", onsubmit: async (e) => {
    e.preventDefault(); btn.disabled = true;
    const { error } = await sb.auth.signInWithOtp({ email: email.value.trim(),
      options: { shouldCreateUser: false, emailRedirectTo: location.origin + location.pathname } });
    btn.disabled = false;
    msg.textContent = error ? loginError(error) : "Check your email and tap the link to log in.";
    msg.className = error ? "error" : "muted";
  } }, el("h1", {}, "Team login"), el("label", {}, "Your email"), email, el("p"), btn, msg);
  app.replaceChildren(form);
}

// Show the REAL reason a login email failed (M-013): only "not invited" errors say so.
function loginError(error) {
  const m = (error && (error.message || error.code || String(error))) || "";
  if (/signups? not allowed|user not found|not allowed for otp|otp_disabled/i.test(m))
    return "That email isn't on the team. Ask Adam for an invite.";
  if (/rate limit|security purposes|too many|over_email_send_rate_limit/i.test(m))
    return "Too many login emails were sent recently (the limit is a few per hour). Wait a while, then try once.";
  if (/redirect/i.test(m))
    return "Login is not set up for this web address yet (Supabase URL settings). Tell Adam.";
  return "Couldn't send the login email: " + m;
}

function showNotOnTeam(email) {
  app.replaceChildren(el("div", { class: "card" }, el("h1", {}, "Not on the team yet"),
    el("p", {}, `${email} hasn't been invited. Ask Adam to add you.`),
    el("button", { class: "secondary", onclick: () => sb.auth.signOut() }, "Log out")));
}

// ---------- upload (affiliates and owner) ----------
async function showUpload() {
  const files = el("input", { type: "file", accept: "video/*", multiple: true });
  const product = el("select", {}, el("option", { value: "" }, "Not sure / more than one"),
    ...cfg.products.map((p) => el("option", { value: p.handle }, p.name)));
  const note = el("textarea", { placeholder: "Anything Adam should know (optional)" });
  const consent = el("input", { type: "checkbox" });
  const btn = el("button", { class: "primary wide" }, "Upload");
  const list = el("div");
  btn.onclick = async () => {
    if (!files.files.length) return toast("Pick at least one video");
    if (!consent.checked) return toast("Tick the box to agree first");
    btn.disabled = true;
    for (const f of files.files) await uploadOne(f, product.value, note.value.trim(), list);
    btn.disabled = false; files.value = ""; note.value = "";
  };
  app.replaceChildren(el("div", { class: "card" },
    el("h1", {}, "Upload clips"),
    el("p", { class: "muted" }, `Vertical video works best. Up to ${cfg.maxUploadMB} MB per clip.`),
    el("label", {}, "Videos"), files,
    el("label", {}, "Which piece is in it?"), product,
    el("label", {}, "Note"), note,
    el("p"), el("label", { class: "consent" }, consent,
      el("span", {}, "I filmed this or have permission to share it, and I give ONEWRLD the right to edit, post and repost it, including in ads.")),
    el("p"), btn, list));
}

function uploadOne(file, productHandle, note, list) {
  const bar = el("div"); const label = el("span", {}, file.name);
  const row = el("div", { class: "card" }, label, el("div", { class: "progress" }, bar));
  list.prepend(row);
  if (file.size > cfg.maxUploadMB * 1024 * 1024) {
    label.textContent = `${file.name}: too big (${Math.round(file.size / 1048576)} MB, max ${cfg.maxUploadMB} MB). Trim it or send a shorter clip.`;
    label.className = "error";
    return Promise.resolve();
  }
  const objectName = `${me.user.id}/${Date.now()}_${safeName(file.name)}`;
  return new Promise(async (resolve) => {
    const { data: { session } } = await sb.auth.getSession();
    const storageHost = cfg.supabaseUrl.replace(".supabase.co", ".storage.supabase.co");
    const up = new tus.Upload(file, {
      endpoint: `${storageHost}/storage/v1/upload/resumable`,
      retryDelays: [0, 3000, 5000, 10000, 20000],
      headers: { authorization: `Bearer ${session.access_token}`, apikey: cfg.supabaseAnonKey, "x-upsert": "false" },
      uploadDataDuringCreation: true,
      removeFingerprintOnSuccess: true,
      metadata: { bucketName: "uploads", objectName, contentType: file.type || "video/mp4", cacheControl: "3600" },
      chunkSize: 6 * 1024 * 1024,
      onError: (err) => { label.textContent = `${file.name}: upload failed. ${err.message || err}`; label.className = "error"; resolve(); },
      onProgress: (sent, total) => { bar.style.width = `${Math.round((sent / total) * 100)}%`; },
      onSuccess: async () => {
        const { error } = await sb.from("submissions").insert({
          affiliate_id: me.user.id, storage_key: objectName, original_name: file.name,
          size_bytes: file.size, product_handle: productHandle || null, note: note || null,
          consent_at: new Date().toISOString() });
        if (error) { label.textContent = `${file.name}: uploaded, but couldn't be saved. ${error.message}`; label.className = "error"; }
        else { label.textContent = `${file.name}: uploaded`; toast("Uploaded"); }
        resolve();
      },
    });
    up.start();
  });
}

// ---------- affiliates: ready to post ----------
async function showReady() {
  const { data, error } = await sb.from("assignments")
    .select("id,status,caption_final,posted_url,assigned_at,posted_at,video_key,hook_text,pack:packs(video_key,hook_text)")
    .eq("affiliate_id", me.user.id).order("assigned_at", { ascending: true });
  if (error) throw error;
  const todo = data.filter((a) => a.status !== "posted");
  const done = data.filter((a) => a.status === "posted").reverse();
  setCount("ready", todo.length);
  const weekAgo = Date.now() - 7 * 864e5;
  const thisWeek = done.filter((a) => a.posted_at && new Date(a.posted_at).getTime() > weekAgo).length;
  if (!data.length) return app.replaceChildren(el("div", { class: "card" }, el("h1", {}, "Ready to post"),
    el("p", { class: "muted" }, "Nothing yet. When Adam approves posts, they show up here by themselves.")));
  const keyOf = (a) => a.video_key || a.pack.video_key;   // each person gets their own version
  const card = (a, i) => {
    const video = el("video", { controls: true, playsinline: true, preload: "metadata" });
    const dl = el("a", { class: "button" }, "Download");
    signed("packs", keyOf(a)).then((u) => { if (u) video.src = u; });
    signed("packs", keyOf(a), true).then((u) => { if (u) dl.href = u; });
    const url = el("input", { type: "url", placeholder: "Link to your post (optional)", value: a.posted_url || "" });
    const doneBtn = el("button", { class: a.status === "posted" ? "secondary" : "primary", onclick: async (e) => {
      e.target.disabled = true;
      const { data: ok, error: err } = await sb.rpc("mark_posted", { p_assignment: a.id, p_url: url.value.trim() });
      if (err || !ok) { e.target.disabled = false; return fail(err || "Couldn't update"); }
      toast(a.status === "posted" ? "Link saved" : "Posted. Next one is up."); show("ready");
    } }, a.status === "posted" ? "Update link" : "I posted it");
    return el("div", { class: "card", "data-assignment": a.id },
      el("div", { class: "row" }, a.status === "posted" ? statusPill("posted") : el("strong", {}, `#${i + 1}`),
        el("span", { class: "muted" }, when(a.assigned_at))),
      video,
      el("label", {}, "Caption (already has your link, code and #ad)"),
      el("div", { class: "caption" }, a.caption_final),
      el("div", { class: "row" }, dl, el("button", { class: "secondary", onclick: () =>
        navigator.clipboard.writeText(a.caption_final).then(() => toast("Caption copied")) }, "Copy caption")),
      el("label", {}, "After you post"), url, el("p"), doneBtn);
  };
  const downloadAll = el("button", { class: "secondary", onclick: async (e) => {
    e.target.disabled = true;
    for (const a of todo) {           // one after another: browsers block a burst of downloads
      const u = await signed("packs", keyOf(a), true);
      if (u) { const link = el("a", { href: u, download: "" }); document.body.append(link); link.click(); link.remove(); }
      await new Promise((r) => setTimeout(r, 900));
    }
    e.target.disabled = false; toast(`${todo.length} video(s) downloading`);
  } }, `Download all (${todo.length})`);
  const head = el("div", { class: "card" },
    el("h1", {}, `Ready to post (${todo.length})`),
    el("p", { class: "muted" }, todo.length
      ? "Post them in order, one at a time across your accounts. Each time you mark one posted, the next one shows up."
      : "All done. New posts appear here as soon as Adam approves more."),
    el("p", {}, el("strong", {}, String(thisWeek)), el("span", { class: "muted" }, " posted in the last 7 days")),
    todo.length > 1 ? downloadAll : null);
  const posted = done.length ? el("details", { class: "card" },
    el("summary", {}, `Posted (${done.length})`), ...done.map((a) => card(a, 0))) : null;
  app.replaceChildren(...[head, ...todo.map(card), posted].filter(Boolean));
}

async function showMine() {
  const { data, error } = await sb.from("submissions").select("id,original_name,status,created_at")
    .eq("affiliate_id", me.user.id).order("created_at", { ascending: false });
  if (error) throw error;
  app.replaceChildren(el("h1", {}, "My uploads"), el("div", { class: "card" },
    data.length ? data.map((s) => el("div", { class: "list-item" },
      el("span", {}, s.original_name || "clip", el("br"), el("span", { class: "muted" }, when(s.created_at))), statusPill(s.status)))
      : el("p", { class: "muted" }, "No uploads yet.")));
}

// ---------- owner: approve and send ----------
// Built for volume (D-067): one post at a time, big buttons (or keys A / R / S), and the
// database hands each approved post's versions out to the team by itself. "Approve all"
// clears the whole queue in one tap. "Choose people" is still there for hand-picking.
async function team() {
  const { data, error } = await sb.from("profiles").select("id,display_name,role,active,discount_code,max_open")
    .eq("active", true).order("display_name");
  if (error) throw error;
  return data;
}

const REJECT_REASONS = ["Weak hook", "Bad look", "Off brand", "Low quality"];
let approveKeys = null;

async function showApprove() {
  const [{ data: packs, error }, people] = await Promise.all([
    sb.from("packs").select("id,hook_text,alt_hooks,caption_base,video_key,alt_video_keys,created_at,submission:submissions(affiliate_id,original_name)")
      .eq("status", "pending").order("created_at", { ascending: true }),
    team()]);
  if (error) throw error;
  const name = Object.fromEntries(people.map((p) => [p.id, p.display_name]));
  const affiliates = people.filter((p) => p.role === "affiliate");
  const queue = packs.slice();
  let pos = 0, approved = 0, sent = 0, rejected = 0;
  if (approveKeys) document.removeEventListener("keydown", approveKeys);

  const remaining = () => queue.length;
  const done = (msg) => {
    setCount("approve", remaining());
    if (pos >= queue.length) pos = 0;
    render(msg);
  };
  async function approve(ids) {
    let a = 0, s = 0;
    for (let i = 0; i < ids.length; i += 200) {                  // the database takes 200 at a time
      const { data: r, error: err } = await sb.rpc("approve_packs", { p_packs: ids.slice(i, i + 200) });
      if (err) { fail(err); break; }
      a += r.approved; s += r.sent;
    }
    approved += a; sent += s;
    for (const id of ids) { const k = queue.findIndex((p) => p.id === id); if (k >= 0) { queue.splice(k, 1); if (k < pos) pos--; } }
    return [a, s];
  }
  async function reject(pk, reason) {
    const { error: err } = await sb.rpc("reject_packs", { p_packs: [pk.id], p_reason: reason });
    if (err) return fail(err);
    rejected++; queue.splice(queue.indexOf(pk), 1); done("Rejected: " + reason);
  }

  function render(msg) {
    if (msg) toast(msg);
    const summary = approved || rejected
      ? el("p", { class: "muted" }, `This session: ${approved} approved (${sent} handed out), ${rejected} rejected.`) : null;
    if (!queue.length) {
      return app.replaceChildren(el("div", { class: "card" }, el("h1", {}, "Approve"),
        el("p", { class: "muted" }, "Nothing waiting. New uploads show up here once your PC has edited them."), summary));
    }
    const pk = queue[pos];
    const uploader = pk.submission?.affiliate_id;
    const keys = [pk.video_key, ...(pk.alt_video_keys || [])];
    const hooks = [pk.hook_text, ...(pk.alt_hooks || [])];
    const video = el("video", { controls: true, playsinline: true, autoplay: true, muted: true, preload: "auto" });
    const hookLine = el("p", { class: "hook" }, hooks[0] || "");
    const chips = keys.map((k, i) => el("button", { class: "chip" + (i === 0 ? " on" : ""), onclick: (e) => {
      for (const c of chips) c.classList.remove("on");
      e.target.classList.add("on"); hookLine.textContent = hooks[i] || hooks[0] || "";
      signed("packs", k).then((u) => { if (u) video.src = u; });
    } }, `V${i + 1}`));
    signed("packs", keys[0]).then((u) => { if (u) video.src = u; });
    const next = queue[(pos + 1) % queue.length];                // warm up the next video
    if (next && next !== pk) signed("packs", next.video_key);

    const reasons = el("div", { class: "row", hidden: true },
      ...REJECT_REASONS.map((r) => el("button", { class: "chip", onclick: () => reject(pk, r) }, r)),
      el("button", { class: "chip", onclick: () => { const r = prompt("Why? (one line, helps the system learn)"); if (r) reject(pk, r); } }, "Other…"));
    const boxes = affiliates.map((p) => el("label", {},
      el("input", { type: "checkbox", value: p.id, checked: p.id === uploader }), p.display_name));
    const picker = el("div", { hidden: true },
      el("div", { class: "row" }, el("strong", {}, "Send to:"),
        el("button", { class: "secondary", onclick: () => boxes.forEach((b) => { b.querySelector("input").checked = true; }) }, "Everyone")),
      el("div", { class: "people" }, boxes),
      el("button", { class: "primary", onclick: async (e) => {
        const ids = boxes.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
        if (!ids.length) return toast("Tick at least one person");
        e.target.disabled = true;
        const { data: n, error: err } = await sb.rpc("approve_pack", { p_pack: pk.id, p_affiliates: ids });
        if (err) { e.target.disabled = false; return fail(err); }
        approved++; sent += n; queue.splice(pos, 1);
        done(`Approved · sent to ${n} ${n === 1 ? "person" : "people"}`);
      } }, "Approve & send to these"));

    const approveOne = async () => { const [, s] = await approve([pk.id]); done(`Approved · ${s} handed out`); };
    const showReasons = () => { reasons.hidden = !reasons.hidden; };
    const skip = () => { pos = (pos + 1) % queue.length; render(); };
    approveKeys = (e) => {
      if (currentTab !== "approve" || /INPUT|TEXTAREA/.test(e.target.tagName) || e.metaKey || e.ctrlKey) return;
      const k = e.key.toLowerCase();
      if (k === "a") approveOne(); else if (k === "r") showReasons(); else if (k === "s" || k === "arrowright") skip();
    };
    document.addEventListener("keydown", approveKeys);

    const all = el("button", { class: "secondary", onclick: async (e) => {
      if (!confirm(`Approve all ${queue.length} posts? Each one is handed out to your team automatically.`)) return;
      e.target.disabled = true;
      const [a, s] = await approve(queue.map((p) => p.id));
      done(`Approved ${a} · ${s} handed out`);
    } }, `Approve all (${queue.length})`);

    app.replaceChildren(...[
      el("div", { class: "row spread" }, el("h1", {}, `Approve (${queue.length})`), all),
      summary,
      el("div", { class: "card", "data-pack": pk.id },
        el("div", { class: "row spread" },
          el("span", { class: "muted" }, `${pos + 1} of ${queue.length} · from ${name[uploader] || "the team"} · ${pk.submission?.original_name || ""}`)),
        video,
        keys.length > 1 ? el("div", { class: "row" }, el("span", { class: "muted" },
          `${keys.length} versions, one per person:`), ...chips) : null,
        hookLine,
        el("div", { class: "caption" }, pk.caption_base),
        el("div", { class: "decide" },
          el("button", { class: "danger", onclick: showReasons }, "Reject"),
          el("button", { class: "secondary", onclick: skip }, "Skip"),
          el("button", { class: "primary", onclick: approveOne }, "Approve")),
        reasons,
        el("p", { class: "muted small" }, "Keys: A approve · R reject · S skip. Approved posts go out to the team by themselves."),
        el("button", { class: "link", onclick: () => { picker.hidden = !picker.hidden; } }, "Choose people instead"),
        picker)].filter(Boolean));
  }
  setCount("approve", queue.length);
  render();
}

async function showAllUploads() {
  const [{ data, error }, people] = await Promise.all([
    sb.from("submissions").select("id,affiliate_id,original_name,status,created_at,note").order("created_at", { ascending: false }).limit(200),
    team()]);
  if (error) throw error;
  const name = Object.fromEntries(people.map((p) => [p.id, p.display_name]));
  app.replaceChildren(el("h1", {}, "Uploads"), el("div", { class: "card" },
    data.length ? data.map((s) => el("div", { class: "list-item" },
      el("span", {}, `${name[s.affiliate_id] || "?"}: ${s.original_name || "clip"}`, el("br"),
        el("span", { class: "muted" }, when(s.created_at) + (s.note ? ` · ${s.note}` : ""))), statusPill(s.status)))
      : el("p", { class: "muted" }, "No uploads yet.")));
}

async function showTeam() {
  const [people, { data: rows, error }] = await Promise.all([team(),
    sb.from("assignments").select("affiliate_id,status,posted_at").order("assigned_at", { ascending: false }).limit(5000)]);
  if (error) throw error;
  const weekAgo = Date.now() - 7 * 864e5;
  const stat = {};
  for (const r of rows) {
    const s = stat[r.affiliate_id] ||= { waiting: 0, week: 0 };
    if (r.status === "assigned") s.waiting++;
    else if (r.posted_at && new Date(r.posted_at).getTime() > weekAgo) s.week++;
  }
  const line = (p) => {
    if (p.role === "owner") return el("div", { class: "list-item" }, el("span", {}, p.display_name), el("span", { class: "muted" }, "owner"));
    const s = stat[p.id] || { waiting: 0, week: 0 };
    let max = p.max_open ?? 5;
    const label = el("span", { class: "cap" }, `${s.waiting} / ${max}`);
    const change = (d) => async () => {
      const n = Math.max(0, Math.min(50, max + d));
      const { error: err } = await sb.rpc("set_max_open", { p_affiliate: p.id, p_max: n });
      if (err) return fail(err);
      max = n; toast(n ? `${p.display_name}: up to ${n} waiting` : `${p.display_name}: paused`); showTeam();
    };
    return el("div", { class: "list-item", "data-person": p.id },
      el("span", {}, p.display_name, el("br"), el("span", { class: "muted small" },
        `${p.discount_code || "no code"} · ${s.week} posted this week`)),
      el("span", { class: "row" }, el("button", { class: "chip", onclick: change(-1) }, "−"), label,
        el("button", { class: "chip", onclick: change(1) }, "+")));
  };
  app.replaceChildren(el("h1", {}, "Team"), el("div", { class: "card" },
    el("p", { class: "muted" }, "Waiting / limit: posts in each person's queue, and the most they can have at once. 0 pauses them."),
    people.map(line),
    el("p", { class: "muted" }, 'Add someone from your PC: python -m onewrld portal invite EMAIL "Name" --code CODE')));
}

function setCount(tab, n) {
  const c = document.getElementById("count-" + tab);
  if (c) c.textContent = n ? String(n) : "";
}

if (!cfg || cfg.supabaseUrl.includes("YOUR-PROJECT") || cfg.supabaseAnonKey.startsWith("YOUR-")) {
  app.replaceChildren(el("div", { class: "card" }, el("h1", {}, "Almost ready"),
    el("p", {}, "Fill in portal/config.js with your Supabase URL and anon key (RUNBOOK section 19).")));
} else {
  start().catch(fail);
}
