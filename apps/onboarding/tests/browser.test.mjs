/* ============================================================================
   The form in a real browser (Playwright, Chromium), offline.

   Starts tests/serve.mjs (the real page and worker, on a throwaway database),
   then:
     - opens one client's link in two separate browsers (two people)
     - types in browser 1, waits for "Saved", reloads browser 2: the answer is there
     - the link's ?email= fills only an empty answer
     - ticks the website "none" box: the box goes, Continue passes
     - fills every page, checks the review page, submits: one form row
     - a second browser on the same link then shows "already in"
     - a mangled link shows "This form link is not valid"
     - /form with no code asks the company name and makes the client
     - no sideways scroll at phone width
     - screenshots at 1440x900 and 390x844 in tests/out/ (not committed)

   Needs Playwright once:  npm install --no-save playwright && npx playwright install chromium
   Run (from apps/onboarding):  npm run test:browser
   ========================================================================= */

import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { startServer } from "./serve.mjs";
import { fullAnswers } from "./link.test.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.resolve(HERE, "..");
const OUT = path.join(HERE, "out");

async function loadPlaywright() {
  const places = [APP, process.env.PLAYWRIGHT_DIR].filter(Boolean);
  for (const p of places) {
    try {
      const req = createRequire(path.join(p, "package.json"));
      const mod = await import(pathToFileURL(req.resolve("playwright")).href);
      return mod.chromium ? mod : mod.default;
    } catch (e) { /* try the next place */ }
  }
  return null;
}

let failures = 0;
function check(label, cond) {
  console.log((cond ? "  ok   " : "  FAIL ") + label);
  if (!cond) failures++;
}

/* Answer every question on the page that is on screen now, in list order, so
   a question that appears after an answer is answered too. */
async function fillPage(page, spec, step, answers) {
  for (const q of spec.flow.filter((x) => x.step === step)) {
    const v = answers[q.id];
    if (q.type === "checkbox") {
      const opt = page.locator(`[data-testid="option-${q.id}-${v ? "yes" : "no"}"]`);
      if (await opt.count()) await opt.click();
    } else if (q.type === "single_select" || q.type === "multi_select") {
      const vals = Array.isArray(v) ? v : [v];
      for (const one of vals) {
        const opt = page.locator(`[data-testid="option-${q.id}-${String(one).toLowerCase().replace(/[^a-z0-9]+/g, "-")}"]`);
        if (await opt.count() && (await opt.getAttribute("data-selected")) !== "1") await opt.click();
      }
    } else {
      const box = page.locator(`[data-testid="input-${q.id}"]`);
      if (await box.count() && await box.isVisible()) await box.fill(String(v));
    }
  }
}

async function main() {
  const pw = await loadPlaywright();
  if (!pw) {
    console.log("SKIPPED: Playwright is not installed. Run: npm install --no-save playwright && npx playwright install chromium");
    return;
  }
  fs.mkdirSync(OUT, { recursive: true });
  const spec = JSON.parse(fs.readFileSync(path.join(APP, "questions.json"), "utf8"));
  const srv = await startServer({ port: 0, examples: false });
  const q = srv.data.query;
  const client = (await q("insert into clients (client_name) values ('Example Browser Co') returning id, form_code"))[0];
  const link = `${srv.url}/form/${client.form_code}`;
  const browser = await pw.chromium.launch();
  const shot = async (page, name) => page.screenshot({ path: path.join(OUT, name + ".png"), fullPage: true });

  try {
    // Two people, two separate browsers, one link.
    const one = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
    const two = await (await browser.newContext({ viewport: { width: 390, height: 844 } })).newPage();
    const errors = [];
    for (const p of [one, two]) p.on("pageerror", (e) => errors.push(String(e)));

    await one.goto(link + "?email=sam%40example.com");
    await one.waitForSelector('[data-testid="input-full_name"]');
    check("the link opens page 1 with the grey box at the top", await one.locator('[data-testid="intro-box"]').isVisible());
    check("the link's email fills the empty email answer",
      (await one.locator('[data-testid="input-email"]').inputValue()) === "sam@example.com");
    await one.locator('[data-testid="input-full_name"]').fill("Sam Taylor");
    await one.waitForFunction(() => document.querySelector('[data-testid="save-status"]').dataset.state === "saved");
    await shot(one, "1-page1-desktop");

    await two.goto(link + "?email=other%40example.com");
    await two.waitForSelector('[data-testid="input-full_name"]');
    check("person 2, in another browser, sees person 1's name",
      (await two.locator('[data-testid="input-full_name"]').inputValue()) === "Sam Taylor");
    check("...and the link never overwrites an answer already saved",
      (await two.locator('[data-testid="input-email"]').inputValue()) === "sam@example.com");
    check("no sideways scroll at phone width",
      await two.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await shot(two, "2-page1-phone");

    // The "none" tick under the website box.
    const answers = fullAnswers(spec, "sam@example.com");
    await fillPage(one, spec, 1, { ...answers, full_name: "Sam Taylor" });
    await one.locator('[data-testid="none-website"]').check();
    check("ticking 'no website yet' hides the website box", !(await one.locator('[data-testid="input-website"]').isVisible()));

    // Every page, then the review page, then Submit.
    const reviewStep = spec.steps.length;
    for (let s = 1; s < reviewStep; s++) {
      if (s > 1) await fillPage(one, spec, s, answers);
      if (s === 3) await shot(one, "3-page3-desktop");
      await one.locator('[data-testid="btn-continue"]').click();
      await one.waitForFunction((n) => /^Step (\d+)/.exec(document.querySelector(".eyebrow").textContent)[1] === String(n), s + 1);
    }
    check("every page passes and the review page opens", await one.locator('[data-testid="btn-submit"]').isVisible());
    check("the review page shows the 'no website yet' answer",
      (await one.locator('[data-testid="review-value-website"]').textContent()) === spec.flow.find((x) => x.id === "website").none_option.value);
    await shot(one, "4-review-desktop");
    await one.locator('[data-testid="btn-submit"]').click();
    await one.waitForSelector('[data-testid="done-screen"]');
    await shot(one, "5-done-desktop");
    const rows = await q("select answers from onboarding_forms where client_id = $1", [client.id]);
    check("Submit shows the thank-you page and files ONE form row", rows.length === 1 && rows[0].answers.full_name.value === "Sam Taylor");

    await two.reload();
    await two.waitForSelector('[data-testid="already-sent"]');
    check("person 2 then sees 'This form is already in'", true);
    await shot(two, "6-already-in-phone");

    // A mangled link.
    await two.goto(`${srv.url}/form/not-a-real-code`);
    await two.waitForSelector('[data-testid="fatal"]');
    check("a mangled link says the link is not valid", /not valid/.test(await two.locator('[data-testid="fatal"]').textContent()));

    // No code: the company name makes a new client.
    await two.goto(`${srv.url}/form?email=new%40example.com`);
    await two.waitForSelector('[data-testid="start-screen"]');
    await shot(two, "7-start-phone");
    await two.locator('[data-testid="input-start-company"]').fill("New Example Co");
    await two.locator('[data-testid="btn-start"]').click();
    await two.waitForURL(/\/form\/[0-9a-f]{32}\?/);
    await two.waitForSelector('[data-testid="input-company_name"]');
    const made = await q("select onboarding_stage::text s from clients where client_name = 'New Example Co'");
    check("/form with no code makes a new client at stage 0 and opens its link",
      made.length === 1 && made[0].s.startsWith("0 ") &&
      (await two.locator('[data-testid="input-company_name"]').inputValue()) === "New Example Co" &&
      (await two.locator('[data-testid="input-email"]').inputValue()) === "new@example.com");

    check("no script errors on any page" + (errors.length ? ": " + errors.join(" | ") : ""), errors.length === 0);
  } finally {
    await browser.close();
    await srv.close();
  }
  console.log(`\nscreenshots: ${OUT}`);
}

main().then(() => {
  console.log(failures ? `\n${failures} check(s) FAILED` : "\nall checks passed");
  process.exit(failures ? 1 : 0);
}).catch((e) => { console.error("the test crashed:", e); process.exit(1); });
