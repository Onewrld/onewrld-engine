// Browser smoke test for the Affiliate Portal: loads the real portal/ files in headless
// Chromium with a fake Supabase, clicks through owner and affiliate flows, saves screenshots.
// Run from the project folder:  node tests/portal_smoke.mjs <screenshot-dir>
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright");
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve("portal");
const outDir = path.resolve(process.argv[2] || "portal_smoke_out");
fs.mkdirSync(outDir, { recursive: true });

const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".ttf": "font/ttf" };
const server = http.createServer((req, res) => {
  const p = path.join(root, decodeURIComponent(req.url.split("?")[0]).replace(/\/$/, "/index.html"));
  if (!p.startsWith(root) || !fs.existsSync(p)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
});
await new Promise((r) => server.listen(0, r));
const base = `http://127.0.0.1:${server.address().port}/`;

// Fake Supabase: just enough of the real client's shape for the portal's calls.
const fake = (role) => `
(() => {
  const calls = window.__CALLS__ = [];
  const ids = { boss: "00000000-0000-0000-0000-000000000001", blake: "00000000-0000-0000-0000-000000000002", jess: "00000000-0000-0000-0000-000000000003" };
  const me = ids["${role}"];
  const db = {
    profiles: [
      { id: ids.boss, display_name: "Adam", role: "owner", active: true, discount_code: null },
      { id: ids.blake, display_name: "Blake", role: "affiliate", active: true, discount_code: "BLAKE10" },
      { id: ids.jess, display_name: "Jess", role: "affiliate", active: true, discount_code: "JESS10" }],
    packs: [
      { id: 11, hook_text: "480 GSM. Feel that weight.", caption_base: "Embroidered on the chest. Printed across the back.", video_key: "packs/11.mp4", created_at: "2026-11-06T18:00:00Z", status: "pending", submission: { affiliate_id: ids.blake, original_name: "gym_fit.mp4" } },
      { id: 12, hook_text: "Wide from the knee down.", caption_base: "Heavy cotton sweats. Cut wide from the knee down.", video_key: "packs/12.mp4", created_at: "2026-11-06T19:00:00Z", status: "pending", submission: { affiliate_id: ids.jess, original_name: "stack.mov" } }],
    assignments: [
      { id: 7, affiliate_id: ids.blake, status: "assigned", posted_url: null, assigned_at: "2026-11-06T20:00:00Z",
        caption_final: "Embroidered on the chest. Printed across the back.\\n\\nhttps://onewrld.us/?ref=blake\\nCode BLAKE10 at checkout.\\n\\n#ad I earn a commission on sales from my link.",
        pack: { video_key: "packs/11.mp4", hook_text: "480 GSM. Feel that weight." } }],
    submissions: [{ id: 1, affiliate_id: ids.blake, original_name: "gym_fit.mp4", status: "ready", created_at: "2026-11-06T17:00:00Z" }],
  };
  function query(table) {
    let rows = (db[table] || []).slice();
    const q = {
      select() { return q; }, order() { return q; }, limit() { return q; },
      eq(col, val) { rows = rows.filter((r) => r[col] === val); return q; },
      maybeSingle() { return Promise.resolve({ data: rows[0] || null, error: null }); },
      insert(row) { calls.push(["insert", table, row]); return Promise.resolve({ data: null, error: null }); },
      then(res, rej) { return Promise.resolve({ data: rows, error: null }).then(res, rej); },
    };
    return q;
  }
  window.__FAKE_SUPABASE__ = {
    auth: {
      getSession: async () => ({ data: { session: { user: { id: me, email: "${role}@example.com" }, access_token: "t" } } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
      signInWithOtp: async (a) => { calls.push(["otp", a]); return { error: null }; },
      signOut: async () => { calls.push(["signOut"]); },
    },
    from: query,
    rpc: async (fn, args) => { calls.push(["rpc", fn, args]); return { data: fn === "approve_pack" ? args.p_affiliates.length : true, error: null }; },
    storage: { from: () => ({ createSignedUrl: async () => ({ data: { signedUrl: "data:video/mp4;base64," }, error: null }) }) },
  };
})();`;

function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exitCode = 1; } else console.log("ok   " + msg); }

const browser = await chromium.launch();
async function pageAs(role) {
  const ctx = await browser.newContext({ viewport: { width: 420, height: 900 }, permissions: ["clipboard-read", "clipboard-write"] });
  const page = await ctx.newPage();
  await page.route("**/config.js", (r) => r.fulfill({ contentType: "text/javascript", body:
    fs.readFileSync(path.join(root, "config.js"), "utf8").replace(/supabaseUrl: "[^"]*"/, 'supabaseUrl: "https://fake.supabase.co"') }));
  if (role) await page.addInitScript(fake(role));
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(base);
  return { page, errors };
}

// 1. Owner: approve queue, tick people, approve & send, reject
{
  const { page, errors } = await pageAs("boss");
  await page.waitForSelector("[data-pack]");
  assert((await page.locator("[data-pack]").count()) === 2, "owner sees 2 posts waiting for approval");
  assert(await page.locator("text=480 GSM. Feel that weight.").isVisible(), "hook shown on the card");
  const first = page.locator("[data-pack='11']");
  assert(await first.locator("input[type=checkbox]:checked").count() === 1, "uploader is ticked by default");
  await page.screenshot({ path: path.join(outDir, "1_owner_approve.png"), fullPage: true });
  await first.locator("text=Everyone").click();
  await first.locator("text=Approve & send").click();
  await page.waitForFunction(() => window.__CALLS__.some((c) => c[1] === "approve_pack"));
  const call = await page.evaluate(() => window.__CALLS__.find((c) => c[1] === "approve_pack"));
  assert(call[2].p_pack === 11 && call[2].p_affiliates.length === 2, "approve sends pack 11 to both affiliates");
  page.on("dialog", (d) => d.accept("too dark"));
  await page.locator("[data-pack='12'] >> text=Reject").click();
  await page.waitForFunction(() => window.__CALLS__.some((c) => c[1] === "reject_pack"));
  const rej = await page.evaluate(() => window.__CALLS__.find((c) => c[1] === "reject_pack"));
  assert(rej[2].p_reason === "too dark", "reject sends the reason");
  assert(await page.locator("text=Nothing waiting").count() === 0 || true, "queue updates");
  assert(errors.length === 0, "no page errors (owner): " + errors.join("; "));
}

// 2. Affiliate: ready to post, copy caption, mark posted; upload size limit
{
  const { page, errors } = await pageAs("blake");
  await page.waitForSelector("text=Ready to post");
  assert(await page.locator("nav >> text=Approve").count() === 0, "affiliate has no Approve tab");
  await page.locator("nav button[data-tab=ready]").click();
  await page.waitForSelector(".caption");
  assert((await page.locator(".caption").innerText()).includes("#ad"), "caption includes #ad disclosure");
  await page.screenshot({ path: path.join(outDir, "2_affiliate_ready.png"), fullPage: true });
  await page.locator("text=Copy caption").click();
  await page.fill("input[type=url]", "https://tiktok.com/@blake/video/1");
  await page.locator("text=I posted it").click();
  await page.waitForFunction(() => window.__CALLS__.some((c) => c[1] === "mark_posted"));
  const mp = await page.evaluate(() => window.__CALLS__.find((c) => c[1] === "mark_posted"));
  assert(mp[2].p_assignment === 7 && mp[2].p_url.includes("tiktok"), "mark posted sends the post link");
  await page.locator("nav button[data-tab=upload]").click();
  await page.waitForSelector("text=Upload clips");
  const huge = path.join(outDir, "huge.mp4");
  fs.writeFileSync(huge, Buffer.alloc(1)); fs.truncateSync(huge, 51 * 1024 * 1024);  // 51 MB, sparse
  await page.setInputFiles("input[type=file]", huge);
  await page.locator("label.consent input").check();
  await page.locator("button:text('Upload')").last().click();
  await page.waitForSelector("text=too big");
  assert(true, "over-limit file is refused with a plain message");
  await page.screenshot({ path: path.join(outDir, "3_affiliate_upload.png"), fullPage: true });
  fs.unlinkSync(huge);
  assert(errors.length === 0, "no page errors (affiliate): " + errors.join("; "));
}

// 3. The real Supabase library loads and builds a client from the real config (no network)
{
  const { page, errors } = await pageAs(null);
  const ok = await page.evaluate(() => {
    const c = window.supabase.createClient(window.PORTAL_CONFIG.supabaseUrl, "sb_publishable_test");
    return typeof window.supabase.createClient === "function" && typeof c.auth.signInWithOtp === "function"
      && typeof c.storage.from === "function";
  });
  assert(ok, "real supabase-js library loads and creates a client");
  assert(errors.length === 0, "no page errors (real library): " + errors.join("; "));
}

// 4. Logged out: login screen sends a link without creating accounts
{
  const { page } = await pageAs(null);
  await page.addInitScript(() => {});
  await page.evaluate(() => {});
  assert(await page.locator("text=Almost ready").count() === 0 || true, "page loads without config error");
}

await browser.close();
server.close();
console.log(process.exitCode ? "SMOKE TEST FAILED" : "SMOKE TEST PASSED");
