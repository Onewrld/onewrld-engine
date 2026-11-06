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
    msg.textContent = error ? "That email isn't on the team. Ask Adam for an invite." : "Check your email and tap the link to log in.";
    msg.className = error ? "error" : "muted";
  } }, el("h1", {}, "Team login"), el("label", {}, "Your email"), email, el("p"), btn, msg);
  app.replaceChildren(form);
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
    .select("id,status,caption_final,posted_url,assigned_at,video_key,hook_text,pack:packs(video_key,hook_text)")
    .eq("affiliate_id", me.user.id).order("assigned_at", { ascending: false });
  if (error) throw error;
  const todo = data.filter((a) => a.status !== "posted");
  setCount("ready", todo.length);
  if (!data.length) return app.replaceChildren(el("div", { class: "card" }, el("h1", {}, "Ready to post"),
    el("p", { class: "muted" }, "Nothing yet. When Adam approves a post for you, it shows up here.")));
  const cards = [];
  for (const a of data) {
    const video = el("video", { controls: true, playsinline: true, preload: "metadata" });
    const dl = el("a", { class: "button" }, "Download video");
    const key = a.video_key || a.pack.video_key;   // each person gets their own version
    signed("packs", key).then((u) => { if (u) video.src = u; });
    signed("packs", key, true).then((u) => { if (u) dl.href = u; });
    const url = el("input", { type: "url", placeholder: "Link to your post (optional)", value: a.posted_url || "" });
    const done = el("button", { class: a.status === "posted" ? "secondary" : "primary", onclick: async () => {
      const { data: ok, error: e } = await sb.rpc("mark_posted", { p_assignment: a.id, p_url: url.value.trim() });
      if (e || !ok) return fail(e || "Couldn't update");
      toast("Marked as posted"); show("ready");
    } }, a.status === "posted" ? "Update link" : "I posted it");
    cards.push(el("div", { class: "card" },
      el("div", { class: "row" }, statusPill(a.status), el("span", { class: "muted" }, when(a.assigned_at))),
      video,
      el("label", {}, "Caption (already has your link, code and #ad)"),
      el("div", { class: "caption" }, a.caption_final),
      el("div", { class: "row" }, dl, el("button", { class: "secondary", onclick: () =>
        navigator.clipboard.writeText(a.caption_final).then(() => toast("Caption copied")) }, "Copy caption")),
      el("label", {}, "After you post"), url, el("p"), done));
  }
  app.replaceChildren(el("h1", {}, "Ready to post"), ...cards);
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
async function team() {
  const { data, error } = await sb.from("profiles").select("id,display_name,role,active,discount_code")
    .eq("active", true).order("display_name");
  if (error) throw error;
  return data;
}

async function showApprove() {
  const [{ data: packs, error }, people] = await Promise.all([
    sb.from("packs").select("id,hook_text,caption_base,video_key,alt_video_keys,created_at,submission:submissions(affiliate_id,original_name)")
      .eq("status", "pending").order("created_at", { ascending: true }),
    team()]);
  if (error) throw error;
  setCount("approve", packs.length);
  if (!packs.length) return app.replaceChildren(el("div", { class: "card" }, el("h1", {}, "Approve"),
    el("p", { class: "muted" }, "Nothing waiting. New uploads show up here once your PC has edited them.")));
  const name = Object.fromEntries(people.map((p) => [p.id, p.display_name]));
  const cards = packs.map((pk) => {
    const uploader = pk.submission?.affiliate_id;
    const boxes = people.filter((p) => p.role === "affiliate").map((p) => {
      const cb = el("input", { type: "checkbox", value: p.id, checked: p.id === uploader });
      return el("label", {}, cb, p.display_name);
    });
    const video = el("video", { controls: true, playsinline: true, preload: "metadata" });
    signed("packs", pk.video_key).then((u) => { if (u) video.src = u; });
    const chosen = () => boxes.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
    const card = el("div", { class: "card", "data-pack": pk.id },
      el("p", { class: "muted" }, `From ${name[uploader] || "the team"} · ${pk.submission?.original_name || ""}`),
      video,
      pk.hook_text ? el("p", { class: "hook" }, pk.hook_text) : null,
      (pk.alt_video_keys || []).length ? el("p", { class: "muted" },
        `${1 + pk.alt_video_keys.length} versions: each person you send it to gets a different one.`) : null,
      el("div", { class: "caption" }, pk.caption_base),
      el("div", { class: "row" }, el("strong", {}, "Send to:"),
        el("button", { class: "secondary", onclick: () => boxes.forEach((b) => { b.querySelector("input").checked = true; }) }, "Everyone")),
      el("div", { class: "people" }, boxes),
      el("div", { class: "row" },
        el("button", { class: "primary", onclick: async (e) => {
          const ids = chosen();
          if (!ids.length) return toast("Tick at least one person");
          e.target.disabled = true;
          const { data: n, error: err } = await sb.rpc("approve_pack", { p_pack: pk.id, p_affiliates: ids });
          if (err) { e.target.disabled = false; return fail(err); }
          toast(`Approved · sent to ${n} ${n === 1 ? "person" : "people"}`); card.remove();
          setCount("approve", app.querySelectorAll("[data-pack]").length);
        } }, "Approve & send"),
        el("button", { class: "danger", onclick: async () => {
          const reason = prompt("Why? (one line, helps the system learn)");
          if (reason === null) return;
          const { error: err } = await sb.rpc("reject_pack", { p_pack: pk.id, p_reason: reason });
          if (err) return fail(err);
          toast("Rejected"); card.remove(); setCount("approve", app.querySelectorAll("[data-pack]").length);
        } }, "Reject")));
    return card;
  });
  app.replaceChildren(el("h1", {}, `Approve (${packs.length})`), ...cards);
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
  const people = await team();
  app.replaceChildren(el("h1", {}, "Team"), el("div", { class: "card" },
    people.map((p) => el("div", { class: "list-item" }, el("span", {}, p.display_name),
      el("span", { class: "muted" }, p.role === "owner" ? "owner" : (p.discount_code || "no code")))),
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
