/* ============================================================================
   The form link, end to end, offline.

   Runs the REAL worker/worker.js (built the way tools/deploy.py builds it)
   against a real Postgres in memory that holds this repo's own tables
   (tests/postgrest.mjs). No network, no Supabase project, no Cloudflare.

   Proves:
     - one shared link per client: /form/<code> opens that client's draft
     - a bad or unknown code is refused and writes nothing
     - two people on one link see the same answers; saves merge per question
     - many saves at the same moment all land (none lost to a race)
     - two first saves on a new link make one draft
     - the "none" tick: its exact text passes, a blank or near answer fails
     - a page save keeps the furthest page reached, and never goes back
     - Submit files ONE onboarding_forms row and sets the form-received date
     - a second Submit, a second window, late typing: all "already submitted"
     - two Submits at the same moment: exactly one files
     - a failed filing gives the claim back, so Submit works next time
     - a client whose form is already in (date set by hand) shows "already in"
     - a hidden (show_if) answer is never filed; a shown required one is needed
     - no code: the company name makes a new client at onboarding stage 0

   Run (from apps/onboarding, after npm install):  node tests/link.test.mjs
   ========================================================================= */

import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { makeDatabase, SUPABASE_URL } from "./postgrest.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const APP = path.resolve(HERE, "..");
export const REPO = path.resolve(APP, "..", "..");

/* The worker module, built the way tools/deploy.py build() does. */
export async function buildWorker() {
  const spec = JSON.parse(readFileSync(path.join(APP, "questions.json"), "utf8"));
  const src = readFileSync(path.join(APP, "worker", "worker.js"), "utf8")
    .replace("__QUESTIONS__", JSON.stringify(spec)).replace("__BUILD_ID__", "test");
  const dir = mkdtempSync(path.join(tmpdir(), "onboarding-worker-"));
  const file = path.join(dir, "worker.mjs");
  writeFileSync(file, src);
  const worker = (await import(pathToFileURL(file).href)).default;
  return { worker, spec };
}

export const ENV = {
  SUPABASE_URL,
  SUPABASE_SECRET_KEY: "test-secret-key",
  OS_AUTOMATIONS_URL: "https://automations.example",
  OS_SHARED_SECRET: "test-shared-secret",
};

/* One full, valid set of answers for every question in the list. */
export function fullAnswers(spec, email) {
  const a = {};
  for (const q of spec.flow) {
    a[q.id] = q.type === "checkbox" ? true
      : q.type === "multi_select" ? [q.options[0]]
      : q.type === "single_select" ? q.options[0]
      : q.type === "email" ? email
      : q.type === "url" ? "https://example.com/" + q.id
      : q.type === "number" ? "12,500"
      : "answer for " + q.id;
  }
  // The controllers' first options must show every show_if question, so the
  // set is complete whatever is shown.
  for (const q of spec.flow) {
    const c = q.show_if;
    if (!c) continue;
    const ctrl = spec.flow.find((x) => x.id === c.question);
    a[ctrl.id] = c.includes !== undefined ? [c.includes] : c.equals_any ? c.equals_any[0] : c.equals;
  }
  return a;
}

/* An answer for `ctrl` that HIDES the question with show_if `cond`. */
function hidingValue(ctrl, cond) {
  if (ctrl.type === "checkbox") return !cond.equals;
  const shows = cond.includes !== undefined ? [cond.includes] : cond.equals_any || [cond.equals];
  const other = (ctrl.options || []).find((o) => !shows.includes(o));
  return ctrl.type === "multi_select" ? [other] : other;
}

let failures = 0;
function check(label, cond) {
  console.log((cond ? "  ok   " : "  FAIL ") + label);
  if (!cond) failures++;
}

async function main() {
  const repoName = path.basename(REPO);
  console.log(`\n# ${repoName}: the form link, against this repo's own tables`);
  const data = await makeDatabase(REPO);
  const told = [];
  globalThis.fetch = data.makeFetch(async (url, init) => {
    if (String(url).startsWith(ENV.OS_AUTOMATIONS_URL)) {
      told.push({ url: String(url), secret: (init.headers || {})["X-OS-Secret"], body: JSON.parse(init.body) });
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }
    throw new Error("unexpected fetch: " + url);
  });
  const { worker, spec } = await buildWorker();
  const q = data.query;

  const waits = [];
  const ctx = { waitUntil: (p) => waits.push(p) };
  const settle = async () => { while (waits.length) await waits.shift(); };
  async function call(method, pathAndQuery, body) {
    const req = new Request("https://onboarding.example/api/onboarding" + pathAndQuery, {
      method, headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const res = await worker.fetch(req, ENV, ctx);
    const json = await res.json();
    return { status: res.status, body: json, data: json.data };
  }
  async function newClient(name) {
    return (await q(`insert into clients (client_name) values ($1) returning id, form_code`, [name]))[0];
  }
  const draftOf = async (id) => (await q(`select * from onboarding_form_drafts where client_id = $1`, [id]))[0];
  const formsOf = async (id) => q(`select * from onboarding_forms where client_id = $1`, [id]);
  const pageAnswers = (all, step) => Object.fromEntries(spec.flow.filter((x) => x.step === step).map((x) => [x.id, all[x.id]]));
  const reviewStep = spec.steps.length;

  const A = await newClient("Example Client One");
  const B = await newClient("Example Client Two");

  // --- the page itself -------------------------------------------------------
  {
    const assets = { fetch: async (req) => {
      const p = new URL(req.url).pathname;
      if (p === "/form/") return new Response('<script src="/form/app.js"></script>', { status: 200, headers: { "Content-Type": "text/html" } });
      if (p === "/form/app.js") return new Response("// app", { status: 200 });
      return new Response("not found", { status: 404 });
    } };
    const page = await worker.fetch(new Request("https://onboarding.example/form/" + A.form_code + "?email=a%40example.com"), { ...ENV, ASSETS: assets }, ctx);
    check("/form/<code> serves the form page, with versioned assets", page.status === 200 && (await page.text()).includes('/form/app.js?v=test"'));
    const plain = await worker.fetch(new Request("https://onboarding.example/form"), { ...ENV, ASSETS: assets }, ctx);
    check("/form (no code) serves the same page", plain.status === 200);
    const js = await worker.fetch(new Request("https://onboarding.example/form/app.js"), { ...ENV, ASSETS: assets }, ctx);
    check("/form/app.js is still the script, not the page", js.status === 200 && (await js.text()) === "// app");
    const flow = await call("GET", "/flow");
    check("GET /flow answers the questions, with no private keys",
      flow.status === 200 && flow.data.flow.length === spec.flow.length && flow.data.review_step === reviewStep);
    await q(`update settings set agency_name = 'Your Agency' where id = 1`);
    check("...and the agency name from the settings table", (await call("GET", "/flow")).data.agency_name === "Your Agency");
  }

  // --- 1. bad or unknown codes ----------------------------------------------
  {
    const a = await call("GET", "/state?code=not%20a%20code");
    const b = await call("GET", "/state?code=" + "0".repeat(32));
    const c = await call("POST", "/draft", { code: "nope", answers: { full_name: "x" } });
    const d = await call("POST", "/draft", { answers: { full_name: "x" } });
    check("a mangled code answers 404 'not valid'", a.status === 404 && a.body.invalid_link === true);
    check("a well-formed code with no client answers 404", b.status === 404 && b.body.invalid_link === true);
    check("saving to a bad or missing code is refused",
      c.status === 404 && d.status === 404 && (await q("select count(*)::int n from onboarding_form_drafts"))[0].n === 0);
  }

  // --- 2. a new link: an empty draft on page 1 --------------------------------
  {
    const r = await call("GET", "/state?code=" + A.form_code);
    check("a new link answers an empty draft on page 1, with the client's name",
      r.status === 200 && r.data.state.status === "in_progress" && r.data.state.current_step === 1 &&
      Object.keys(r.data.state.answers).length === 0 && r.data.client_name === "Example Client One");
  }

  // --- 3. two people on one link -------------------------------------------
  {
    const w1 = await call("POST", "/draft", { code: A.form_code, answers: { full_name: "Sam Taylor", company_name: "Example Co" },
                                              prefilled: ["company_name"], by_email: "Sam@Example.com" });
    check("person 1's typing is saved", w1.status === 200 && w1.data.ok === true && !!(await draftOf(A.id)));
    const w2 = await call("GET", "/state?code=" + A.form_code);
    check("person 2 opens the link and sees person 1's answers",
      w2.data.state.answers.full_name.value === "Sam Taylor" && w2.data.state.answers.company_name.value === "Example Co");
    check("...the answer the link filled in is marked as such", w2.data.state.answers.company_name.prefilled === true);
    check("...and the draft says who saved last", (await draftOf(A.id)).last_editor_email === "sam@example.com");
    await call("POST", "/draft", { code: A.form_code, answers: { phone: "+1 555 010 0100" } });
    const after = (await call("GET", "/state?code=" + A.form_code)).data.state.answers;
    check("a save touches only its own question: the others stay",
      after.full_name.value === "Sam Taylor" && after.phone.value === "+1 555 010 0100");
    await call("POST", "/draft", { code: A.form_code, answers: { full_name: "Sam T." } });
    check("last write wins on the same question",
      (await call("GET", "/state?code=" + A.form_code)).data.state.answers.full_name.value === "Sam T.");
    const junk = await call("POST", "/draft", { code: A.form_code, answers: { not_a_question: "x", email: { bad: 1 } } });
    const d = await draftOf(A.id);
    check("unknown questions and wrong-shaped answers are never stored",
      junk.status === 400 && !("not_a_question" in d.answers) && !("email" in d.answers));
    check("the other client's link has its own, empty draft",
      Object.keys((await call("GET", "/state?code=" + B.form_code)).data.state.answers).length === 0);
    check("the browser never sees another client's draft (drafts are keyed by the link only)",
      (await q("select count(*)::int n from onboarding_form_drafts where client_id = $1", [B.id]))[0].n === 0);
  }

  // --- 4. many saves at the same moment: all land ----------------------------
  {
    const ids = spec.flow.filter((x) => ["short_text", "long_text"].includes(x.type) && !["full_name", "phone"].includes(x.id))
      .slice(0, 8).map((x) => x.id);
    const results = await Promise.all(ids.map((id, i) => call("POST", "/draft", { code: A.form_code, answers: { [id]: "value " + i } })));
    const st = (await call("GET", "/state?code=" + A.form_code)).data.state.answers;
    check(`${ids.length} saves at the same moment all succeed`, results.every((r) => r.status === 200));
    check("...and every answer is in the draft (none lost to a race)",
      ids.every((id, i) => st[id] && st[id].value === "value " + i) && st.full_name.value === "Sam T.");
    check("...still one draft row for the client",
      (await q("select count(*)::int n from onboarding_form_drafts where client_id = $1", [A.id]))[0].n === 1);
  }

  // --- 5. two first saves on a brand-new link make one draft ------------------
  {
    const C = await newClient("Example Client Three");
    await Promise.all([
      call("POST", "/draft", { code: C.form_code, answers: { full_name: "A" } }),
      call("POST", "/draft", { code: C.form_code, answers: { phone: "B" } }),
    ]);
    const st = (await call("GET", "/state?code=" + C.form_code)).data.state.answers;
    check("two first saves at once make one draft holding both answers",
      (await q("select count(*)::int n from onboarding_form_drafts where client_id = $1", [C.id]))[0].n === 1 &&
      st.full_name.value === "A" && st.phone.value === "B");
  }

  // --- 6. the "none" tick, and page saves ------------------------------------
  const all = fullAnswers(spec, "sam@example.com");
  const site = spec.flow.find((x) => x.id === "website");
  const NONE = site.none_option.value;
  {
    const p1 = pageAnswers(all, 1);
    const blank = await call("POST", "/step", { code: A.form_code, step: 1, answers: { ...p1, website: "" } });
    check("a blank website with no tick fails page 1",
      blank.status === 400 && /required/.test(blank.body.field_errors.website || ""));
    const near = await call("POST", "/step", { code: A.form_code, step: 1, answers: { ...p1, website: NONE.slice(0, -2) } });
    check("text that is almost the tick's answer fails", near.status === 400 && !!near.body.field_errors.website);
    const ok1 = await call("POST", "/step", { code: A.form_code, step: 1, answers: { ...p1, website: NONE } });
    check(`the ticked answer '${NONE}' passes page 1`,
      ok1.status === 200 && ok1.data.next_step === 2 && ok1.data.state.answers.website.value === NONE);
    await call("POST", "/step", { code: A.form_code, step: 2, answers: pageAnswers(all, 2) });
    await call("POST", "/step", { code: A.form_code, step: 3, answers: pageAnswers(all, 3) });
    check("the furthest page reached is kept on the draft", (await draftOf(A.id)).current_step === 4);
    await call("POST", "/step", { code: A.form_code, step: 1, answers: { ...p1, website: NONE } });
    check("...and never goes back when an earlier page is saved", (await draftOf(A.id)).current_step === 4);
    const bad = await call("POST", "/step", { code: A.form_code, step: reviewStep, answers: {} });
    check("the review page cannot be saved as a page", bad.status === 400);
  }

  // --- 7. Submit: one form per client ------------------------------------------
  {
    const early = await call("POST", "/submit", { code: A.form_code });
    check("Submit with answers missing is refused and files nothing",
      early.status === 400 && Object.keys(early.body.field_errors).length > 0 && (await formsOf(A.id)).length === 0);
    check("...and the form-received date stays empty",
      (await q("select form_received_at from clients where id = $1", [A.id]))[0].form_received_at === null);

    await call("POST", "/draft", { code: A.form_code, answers: { ...all, website: NONE } });
    const st = (await call("GET", "/state?code=" + A.form_code)).data.state;
    check("a full draft opens on the review page", st.current_step === reviewStep);

    const first = await call("POST", "/submit", { code: A.form_code, by_email: "sam@example.com" });
    await settle();
    const rows = await formsOf(A.id);
    const row = rows[0];
    const cl = (await q("select form_received_at, onboarding_stage from clients where id = $1", [A.id]))[0];
    check("the first Submit files the form", first.status === 200 && first.data.ok === true && first.data.state.status === "complete");
    check("...as ONE onboarding_forms row linked to the client", rows.length === 1 && row.form_key === spec.form_key);
    check("...holding the shared answers, each with its label and place",
      row.answers.website.value === NONE && row.answers.website.none === true &&
      row.answers.full_name.value === all.full_name && row.answers.full_name.label === "Your name" &&
      row.answers.full_name.n === 1 && row.answers.full_name.step === 1);
    check("...with who sent it and the company", row.submitted_by_email === "sam@example.com" &&
      row.submitted_by_name === all.full_name && row.company_name === all.company_name);
    check("...and the client's form-received date is set", cl.form_received_at !== null);
    check("...the draft records the form it filed", (await draftOf(A.id)).submission_id === row.id);
    check("...and the OS automations were told once, with the shared secret",
      told.length === 1 && told[0].url === ENV.OS_AUTOMATIONS_URL + "/form-submitted" &&
      told[0].secret === ENV.OS_SHARED_SECRET && told[0].body.onboarding_form_id === row.id && told[0].body.client_id === A.id);

    const again = await call("POST", "/submit", { code: A.form_code });
    const other = await call("GET", "/state?code=" + A.form_code);
    const typing = await call("POST", "/draft", { code: A.form_code, answers: { full_name: "late edit" } });
    const page = await call("POST", "/step", { code: A.form_code, step: 1, answers: pageAnswers(all, 1) });
    await settle();
    check("a second Submit answers 'already submitted'", again.status === 200 && again.data.already_submitted === true);
    check("...a second window opening the link gets 'already submitted'", other.data.already_submitted === true);
    check("...late typing and page saves get 'already submitted' too",
      typing.data.already_submitted === true && page.data.already_submitted === true);
    check("...none of the earlier answers are sent back", Object.keys(other.data.state.answers).length === 0);
    check("...no second row, no second message, no late edit",
      (await formsOf(A.id)).length === 1 && told.length === 1 && (await draftOf(A.id)).answers.full_name.value !== "late edit");
  }

  // --- 8. two Submits at the same moment ----------------------------------------
  {
    const R = await newClient("Example Client Race");
    await call("POST", "/draft", { code: R.form_code, answers: fullAnswers(spec, "race@example.com") });
    const before = told.length;
    const [x, y] = await Promise.all([call("POST", "/submit", { code: R.form_code }), call("POST", "/submit", { code: R.form_code })]);
    await settle();
    const filed = [x, y].filter((r) => r.data && r.data.ok === true && !r.data.already_submitted).length;
    check("two Submits at once: exactly one files", filed === 1);
    check("...the other answers 'already submitted'", [x, y].filter((r) => r.data && r.data.already_submitted).length === 1);
    check("...one row and one message", (await formsOf(R.id)).length === 1 && told.length === before + 1);
  }

  // --- 9. a filing that fails gives the claim back -------------------------------
  {
    const F = await newClient("Example Client Fail");
    await call("POST", "/draft", { code: F.form_code, answers: fullAnswers(spec, "fail@example.com") });
    const real = globalThis.fetch;
    globalThis.fetch = async (url, init) => {
      if (String(url).endsWith("/rest/v1/onboarding_forms") && (init || {}).method === "POST") {
        return new Response(JSON.stringify({ message: "boom" }), { status: 500 });
      }
      return real(url, init);
    };
    const r = await call("POST", "/submit", { code: F.form_code });
    globalThis.fetch = real;
    const cl = (await q("select form_received_at from clients where id = $1", [F.id]))[0];
    check("a filing that fails answers an error", r.status === 500);
    check("...and leaves the form-received date empty, so Submit can be tried again", cl.form_received_at === null);
    const again = await call("POST", "/submit", { code: F.form_code });
    await settle();
    check("...and the next Submit files it", again.status === 200 && again.data.ok === true && (await formsOf(F.id)).length === 1);
  }

  // --- 10. a form already in (date set by hand in the OS) -----------------------
  {
    const H = await newClient("Example Client By Hand");
    await q("update clients set form_received_at = now() where id = $1", [H.id]);
    const r = await call("GET", "/state?code=" + H.form_code);
    const s = await call("POST", "/draft", { code: H.form_code, answers: { full_name: "x" } });
    check("a client whose form-received date is set shows 'already submitted'",
      r.data.already_submitted === true && s.data.already_submitted === true && !(await draftOf(H.id)));
  }

  // --- 11. show_if: a hidden answer is never filed -----------------------------
  {
    const hidden = spec.flow.find((x) => x.show_if);
    if (!hidden) {
      check("this question list has no show_if question (nothing to test)", true);
    } else {
      const ctrl = spec.flow.find((x) => x.id === hidden.show_if.question);
      const S1 = await newClient("Example Client Show");
      // Shown and required but blank: Submit is refused.
      if (hidden.required && hidden.type !== "checkbox") {
        await call("POST", "/draft", { code: S1.form_code, answers: { ...fullAnswers(spec, "show@example.com"), [hidden.id]: "" } });
        const r = await call("POST", "/submit", { code: S1.form_code });
        check(`a shown required question ('${hidden.id}') left blank stops Submit`,
          r.status === 400 && !!r.body.field_errors[hidden.id]);
      }
      // Hidden, with an old answer still in the draft: Submit files without it.
      await call("POST", "/draft", { code: S1.form_code, answers: { ...fullAnswers(spec, "show@example.com"),
        [ctrl.id]: hidingValue(ctrl, hidden.show_if), [hidden.id]: hidden.type === "checkbox" ? true : "https://example.com/old" } });
      const r2 = await call("POST", "/submit", { code: S1.form_code });
      await settle();
      const row = (await formsOf(S1.id))[0];
      check(`a hidden question ('${hidden.id}') is not filed, even with an old answer in the draft`,
        r2.status === 200 && row && !(hidden.id in row.answers) && ctrl.id in row.answers);
    }
  }

  // --- 12. no code: the company name makes a new client at stage 0 ---------------
  {
    const empty = await call("POST", "/start", { company_name: " " });
    check("no company name: refused, no client made", empty.status === 400 && !!empty.body.field_errors.company_name);
    const before = (await q("select count(*)::int n from clients"))[0].n;
    const s = await call("POST", "/start", { company_name: "  New   Example Co " });
    const made = (await q("select id, client_name, onboarding_stage::text stage, form_code from clients where form_code = $1", [s.data.code]))[0];
    const logged = (await q("select count(*)::int n from stage_log where record_id = $1", [made.id]))[0].n;
    check("a company name makes ONE new client", s.status === 200 && (await q("select count(*)::int n from clients"))[0].n === before + 1);
    check("...named as typed, at onboarding stage 0", made.client_name === "New Example Co" && made.stage.startsWith("0 "));
    check("...with its own random link code", /^[0-9a-f]{32}$/.test(made.form_code));
    check("...and the stage log records the new client", logged === 1);
    const st = await call("GET", "/state?code=" + s.data.code);
    check("...and its link then works like any other", st.status === 200 && st.data.state.current_step === 1);
  }

  // --- 13b. a number question: whole numbers only, filed as a number ------------
  for (const nq of spec.flow.filter((x) => x.type === "number")) {
    const s0 = await call("POST", "/start", { company_name: "Number Test Co" });
    const code = s0.data.code;
    const cl = (await q("select id from clients where form_code = $1", [code]))[0];
    const page = (v) => {
      const a = {};
      for (const x of spec.flow.filter((y) => y.step === nq.step)) a[x.id] = all[x.id];
      a[nq.id] = v;
      return call("POST", "/step", { code, step: nq.step, answers: a });
    };
    const all = fullAnswers(spec, "num@example.com");
    for (const bad of ["lots", "-5", "1.5", "20k"]) {
      const r = await page(bad);
      check(`'${nq.id}': "${bad}" is refused with a plain message`, r.status === 400 && /whole number/.test(r.body.field_errors[nq.id] || ""));
    }
    for (let st = 1; st < spec.steps.length; st++) {
      const a = {};
      for (const x of spec.flow.filter((y) => y.step === st)) a[x.id] = all[x.id];
      if (st === nq.step) a[nq.id] = " 20,000 ";
      const r = await call("POST", "/step", { code, step: st, answers: a });
      if (r.status !== 200) check(`page ${st} saves`, false);
    }
    const sub = await call("POST", "/submit", { code });
    await settle();
    const row = (await formsOf(cl.id))[0];
    check(`'${nq.id}': " 20,000 " is filed as the number 20000`, sub.status === 200 && row && row.answers[nq.id].value === 20000);
    const hasCol = (await q("select count(*)::int n from information_schema.columns where table_name = 'clients' and column_name = $1", [nq.id]))[0].n;
    if (hasCol) {
      const v = (await q(`select ${nq.id} v from clients where id = $1`, [cl.id]))[0].v;
      check(`'${nq.id}': the answer lands on the client record (clients.${nq.id} = ${v})`, v === 20000);
    }
    if (nq.none_option) {
      const s1 = await call("POST", "/start", { company_name: "Not Sure Co" });
      const r = await call("POST", "/step", { code: s1.data.code, step: nq.step,
        answers: Object.fromEntries(spec.flow.filter((y) => y.step === nq.step).map((x) => [x.id, x.id === nq.id ? nq.none_option.value : all[x.id]])) });
      check(`'${nq.id}': the "${nq.none_option.value}" tick is accepted`, r.status === 200);
    }
  }

  // --- 13. the secret key stays on the server ---------------------------------
  {
    const flow = JSON.stringify((await call("GET", "/flow")).body);
    const state = JSON.stringify((await call("GET", "/state?code=" + B.form_code)).body);
    check("no answer from the server holds the secret key",
      !flow.includes(ENV.SUPABASE_SECRET_KEY) && !state.includes(ENV.SUPABASE_SECRET_KEY));
  }

  console.log(failures ? `\n${failures} check(s) FAILED` : "\nall checks passed");
  process.exit(failures ? 1 : 0);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((e) => { console.error("the test crashed:", e); process.exit(1); });
}
