/* ============================================================================
   The onboarding form: the server half.

   A Cloudflare Pages "advanced mode" worker. It answers the form routes under
   /api/onboarding/* and hands everything else to the static site.

   It is the only part that talks to the database. It uses the Supabase SECRET
   key, which is a Cloudflare secret on the Pages project. The key never
   reaches the browser.

   QUESTIONS is put in at build time from apps/onboarding/questions.json by
   tools/deploy.py, so the questions live in one file. The browser never holds
   them: it fetches GET /api/onboarding/flow when the page loads.

   The rules, all kept here and never in the browser:
     * One link per client: /form/<code>. The code is clients.form_code.
     * One shared draft per client (onboarding_form_drafts). Everyone with the
       link sees and edits the same answers, on any browser. The browser keeps
       nothing and never decides which draft opens.
     * Saves merge per question: two people on different questions never undo
       each other.
     * A hidden question (show_if) is never checked and never filed.
     * Submit works once per client. It files one onboarding_forms row and sets
       clients.form_received_at.
     * No code in the link: the form asks for the company name and makes a new
       client at onboarding stage 0, then carries on as that client's link.
   ========================================================================= */

const QUESTIONS = __QUESTIONS__;
// A hash of the form's files, put in by tools/deploy.py. It versions the
// page's script and style addresses, so a new deploy reaches every browser.
const BUILD_ID = "__BUILD_ID__";

/* Keys the browser may see. */
const PUBLIC_KEYS = [
  "step", "id", "label", "type", "required", "help", "placeholder", "rows",
  "options", "chips", "info", "prefill", "show_if", "option_help", "none_option", "links",
];

const ROUTE = "/api/onboarding";
const FORM_KEY = QUESTIONS.form_key;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const URL_RE = /^(https?:\/\/)?[^\s.]+\.[^\s]{2,}$/i;
const CODE_RE = /^[A-Za-z0-9_-]{8,64}$/;
const MAX_TEXT = 20000;   // one answer, in characters
const MAX_ITEMS = 50;     // one multi_select answer

/* ---------- small helpers ------------------------------------------------ */

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

const ok = (data) => json({ status: "success", data });
const fail = (error, status = 400, extra = {}) => json({ status: "error", error, ...extra }, status);

/* ---------- the question list -------------------------------------------- */

const publicFlow = () =>
  QUESTIONS.flow.map((q) => {
    const out = {};
    for (const k of PUBLIC_KEYS) if (k in q) out[k] = q[k];
    return out;
  });

const questionsForStep = (step) => QUESTIONS.flow.filter((q) => q.step === step);

/* The review page is always the last page, and holds no questions. */
const reviewStep = () => QUESTIONS.steps.length;

function asArray(value) {
  if (Array.isArray(value)) return value;
  if (value == null) return [];
  const s = String(value).trim();
  return s ? [s] : [];
}

/* A show_if question only exists while its controlling answer matches.
   `answers` is the flat {id: value} shape. */
function visible(q, answers) {
  const cond = q.show_if;
  if (!cond) return true;
  const c = answers[cond.question];
  if (cond.includes !== undefined) return asArray(c).map(String).includes(String(cond.includes));
  const s = String(c == null ? "" : c).trim();
  if (cond.equals_any) return cond.equals_any.map(String).includes(s);
  return s === String(cond.equals);
}

/* The answer a ticked none_option box stores, or "". */
const noneValue = (q) => (q.none_option && q.none_option.value) || "";

function validate(q, value) {
  if (noneValue(q) && typeof value === "string" && value.trim() === noneValue(q)) return null;
  if (q.type === "checkbox") {
    if (q.required && value !== true) return "please complete this before you continue";
    if (value != null && typeof value !== "boolean") return "please choose yes or not yet";
    return null;
  }
  if (q.type === "multi_select") {
    const arr = asArray(value);
    if (!arr.length) return q.required ? "please choose at least one option" : null;
    const bad = arr.filter((v) => !(q.options || []).includes(String(v)));
    if (bad.length) return "please choose from: " + (q.options || []).join(", ");
    return null;
  }
  if (value == null || (typeof value === "string" && !value.trim())) {
    return q.required ? "this field is required" : null;
  }
  const s = String(value).trim();
  if (q.type === "email" && !EMAIL_RE.test(s)) return "please enter a valid email address";
  if (q.type === "url" && !URL_RE.test(s)) return "please enter a valid web address";
  if (q.type === "single_select" && !(q.options || []).includes(s)) {
    return "please choose one of: " + (q.options || []).join(", ");
  }
  return null;
}

function validateStep(step, flat) {
  const errors = {};
  for (const q of questionsForStep(step)) {
    if (!visible(q, flat)) continue;
    const err = validate(q, flat[q.id]);
    if (err) errors[q.id] = err;
  }
  return errors;
}

function validateAll(flat) {
  const errors = {};
  for (let s = 1; s < reviewStep(); s++) Object.assign(errors, validateStep(s, flat));
  return errors;
}

/* Stored entries {id: {value, ...}} -> the flat {id: value} shape. */
const flatOf = (answers) => {
  const f = {};
  for (const [id, e] of Object.entries(answers || {})) f[id] = (e || {}).value;
  return f;
};

/* The first page with an answer still missing, else the review page. */
function firstOpenStep(answers) {
  const flat = flatOf(answers);
  for (let s = 1; s < reviewStep(); s++) if (Object.keys(validateStep(s, flat)).length) return s;
  return reviewStep();
}

/* What a half-typed answer may be before Continue checks it: text, true or
   false, or a list of options. Anything else is dropped, never stored. */
function draftValue(q, raw) {
  if (q.type === "checkbox") return typeof raw === "boolean" ? raw : undefined;
  if (q.type === "multi_select") {
    return Array.isArray(raw) ? raw.slice(0, MAX_ITEMS).map((x) => String(x).slice(0, 500)) : undefined;
  }
  if (raw == null) return "";
  if (typeof raw !== "string" && typeof raw !== "number") return undefined;
  return String(raw).slice(0, MAX_TEXT);
}

/* {question id: typed value} -> draft entries, known questions only. */
function draftEntries(submitted, prefilled, at) {
  const out = {};
  const pre = Array.isArray(prefilled) ? prefilled : [];
  for (const q of QUESTIONS.flow) {
    if (!submitted || !(q.id in submitted)) continue;
    const v = draftValue(q, submitted[q.id]);
    if (v === undefined) continue;
    out[q.id] = { value: v, answered_at: at };
    if (pre.includes(q.id)) out[q.id].prefilled = true;
  }
  return out;
}

/* Who saved: the email in the link, else the email typed in the form. */
function savedBy(byEmail, flat) {
  for (const t of [byEmail, (flat || {}).email]) {
    const s = typeof t === "string" ? t.trim() : "";
    if (EMAIL_RE.test(s)) return s.slice(0, 320).toLowerCase();
  }
  return null;
}

/* The answers as they are filed: visible questions only, each with its label,
   page and place in the form (a jsonb object does not keep key order). */
function filedAnswers(answers) {
  const flat = flatOf(answers);
  const out = {};
  QUESTIONS.flow.forEach((q, n) => {
    const e = answers[q.id];
    if (!e || !visible(q, flat)) return;
    out[q.id] = { n: n + 1, step: q.step, label: q.label, type: q.type, value: e.value };
    if (noneValue(q) && e.value === noneValue(q)) out[q.id].none = true;
  });
  return out;
}

/* ---------- Supabase (PostgREST), with the secret key --------------------- */

class Store {
  constructor(env) {
    const base = String(env.SUPABASE_URL || "").replace(/\/+$/, "").replace(/\/rest\/v1$/, "");
    if (!base) throw new Error("SUPABASE_URL is not set");
    if (!env.SUPABASE_SECRET_KEY) throw new Error("SUPABASE_SECRET_KEY is not set");
    this.base = base + "/rest/v1";
    this.h = {
      apikey: env.SUPABASE_SECRET_KEY,
      Authorization: "Bearer " + env.SUPABASE_SECRET_KEY,
      "Content-Type": "application/json",
    };
  }

  async call(path, init = {}) {
    const r = await fetch(this.base + path, { ...init, headers: { ...this.h, ...(init.headers || {}) } });
    const text = await r.text();
    if (!r.ok) throw new Error(`supabase ${r.status}: ${text.slice(0, 400)}`);
    return text ? JSON.parse(text) : null;
  }

  async agencyName() {
    const rows = await this.call("/settings?id=eq.1&select=agency_name");
    return (rows && rows[0] && rows[0].agency_name) || "";
  }

  /* The client a form link names, or null. */
  async client(code) {
    if (!CODE_RE.test(code)) return null;
    const rows = await this.call(
      `/clients?form_code=eq.${encodeURIComponent(code)}` +
        "&select=id,client_name,contact_name,contact_email,form_received_at&limit=1");
    return rows && rows.length ? rows[0] : null;
  }

  /* True once the client's form is in: the form-received date is set (by a
     Submit, or by hand in the OS), or a form is already linked to the client. */
  async finished(client) {
    if (client.form_received_at) return true;
    const rows = await this.call(
      `/onboarding_forms?client_id=eq.${client.id}&form_key=eq.${encodeURIComponent(FORM_KEY)}&select=id&limit=1`);
    return Boolean(rows && rows.length);
  }

  /* A new client at onboarding stage 0, for a link with no code. */
  async newClient(companyName) {
    const rows = await this.call("/clients", {
      method: "POST",
      headers: { Prefer: "return=representation" },
      body: JSON.stringify({
        client_name: companyName,
        notes: "Made by the onboarding form. The person used the form address with no client code.",
      }),
    });
    return rows[0];
  }

  draftPath(clientId) {
    return `/onboarding_form_drafts?client_id=eq.${clientId}&form_key=eq.${encodeURIComponent(FORM_KEY)}`;
  }

  async draft(clientId) {
    const rows = await this.call(this.draftPath(clientId) +
      "&select=client_id,answers,current_step,updated_at,submission_id&limit=1");
    return rows && rows.length ? rows[0] : null;
  }

  /* Merge `changes` ({question id: entry}) into the client's draft. Last write
     wins PER QUESTION: answers this request does not name are never touched,
     even when another window saved them a moment ago.

     A compare-and-swap: read the row, merge, and write it back only if
     updated_at is still what was read. The table's trigger sets updated_at to
     the database time on every write, so a writer that lost the race finds a
     new value, reads again and retries. */
  async saveDraft(clientId, changes, byEmail) {
    for (let attempt = 0; attempt < 8; attempt++) {
      const cur = await this.draft(clientId);
      if (cur && cur.submission_id) return "submitted";
      if (!cur) {
        const made = await this.call("/onboarding_form_drafts?on_conflict=client_id,form_key", {
          method: "POST",
          headers: { Prefer: "resolution=ignore-duplicates,return=representation" },
          body: JSON.stringify({ client_id: clientId, form_key: FORM_KEY, answers: changes,
                                 last_editor_email: byEmail || null }),
        });
        if (made && made.length) return made[0];
        continue;   // another window made it first: merge into theirs
      }
      const rows = await this.call(
        this.draftPath(clientId) + `&updated_at=eq.${encodeURIComponent(cur.updated_at)}&submission_id=is.null`, {
          method: "PATCH",
          headers: { Prefer: "return=representation" },
          body: JSON.stringify({ answers: { ...(cur.answers || {}), ...changes },
                                 last_editor_email: byEmail || null }),
        });
      if (rows && rows.length) return rows[0];
    }
    throw new Error("the form is busy saving from another window, please try again");
  }

  /* The furthest page anyone reached on this link. It only ever goes up. */
  async raiseStep(clientId, step) {
    await this.call(this.draftPath(clientId) + `&current_step=lt.${Number(step)}`, {
      method: "PATCH", headers: { Prefer: "return=minimal" }, body: JSON.stringify({ current_step: Number(step) }),
    });
  }

  /* Claim the client's one Submit by setting the form-received date. Of two
     Submits at the same moment, only one gets the row back. */
  async claim(clientId) {
    const rows = await this.call(`/clients?id=eq.${clientId}&form_received_at=is.null`, {
      method: "PATCH", headers: { Prefer: "return=representation" },
      body: JSON.stringify({ form_received_at: new Date().toISOString() }),
    });
    return rows && rows.length ? rows[0].form_received_at : null;
  }

  /* Give the claim back when the form could not be filed after all. */
  async release(clientId, claimedAt) {
    await this.call(`/clients?id=eq.${clientId}&form_received_at=eq.${encodeURIComponent(claimedAt)}`, {
      method: "PATCH", headers: { Prefer: "return=minimal" }, body: JSON.stringify({ form_received_at: null }),
    });
  }

  async file(row) {
    const rows = await this.call("/onboarding_forms", {
      method: "POST", headers: { Prefer: "return=representation" }, body: JSON.stringify(row),
    });
    return rows[0];
  }

  async markFiled(clientId, formId) {
    await this.call(this.draftPath(clientId), {
      method: "PATCH", headers: { Prefer: "return=minimal" }, body: JSON.stringify({ submission_id: formId }),
    });
  }
}

/* After a Submit: tell the OS automations (tab 3), which post the new
   form in the new-tasks channel. Only when both values are set on the Pages
   project. It never makes a Submit fail. */
async function tellAutomations(env, form) {
  const base = String(env.OS_AUTOMATIONS_URL || "").replace(/\/+$/, "");
  if (!base || !env.OS_SHARED_SECRET) return "skipped";
  try {
    const r = await fetch(base + "/form-submitted", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-OS-Secret": env.OS_SHARED_SECRET },
      body: JSON.stringify({ onboarding_form_id: form.id, client_id: form.client_id }),
    });
    return r.ok ? "ok" : "error:" + r.status;
  } catch (e) {
    return "error:" + e.name;
  }
}

/* ---------- the routes --------------------------------------------------- */

/* "This form is already in." Carries none of the earlier answers. */
const alreadySent = () => ({
  ok: false,
  already_submitted: true,
  state: { status: "complete", current_step: reviewStep(), answers: {} },
});

const linkState = (answers, step) => ({
  status: "in_progress",
  current_step: step || firstOpenStep(answers),
  answers: answers || {},
  total_steps: QUESTIONS.steps.length,
});

async function flowPayload(store) {
  let agency = "";
  try { agency = await store.agencyName(); } catch (e) { agency = ""; }
  return {
    flow: publicFlow(),
    steps: QUESTIONS.steps,
    total_steps: QUESTIONS.steps.length,
    review_step: reviewStep(),
    question_count: QUESTIONS.flow.length,
    title: QUESTIONS.title,
    intro: QUESTIONS.intro || null,
    done: QUESTIONS.done || null,
    agency_name: agency,
  };
}

async function handleApi(request, env, path, ctx) {
  const store = new Store(env);
  const now = () => new Date().toISOString();
  const u = new URL(request.url);
  const body = request.method === "POST" ? await request.json().catch(() => ({})) : {};

  /* GET /flow: what the page draws. Also the deploy health check. */
  if (path === "/flow" && request.method === "GET") return ok(await flowPayload(store));

  /* POST /start: no code in the link. Make a new client at onboarding stage 0
     and answer its code. The page then opens /form/<code>. */
  if (path === "/start" && request.method === "POST") {
    const name = String(body.company_name || "").replace(/\s+/g, " ").trim();
    if (name.length < 2 || name.length > 200) {
      return fail("please enter your company name", 400, { field_errors: { company_name: "please enter your company name" } });
    }
    const client = await store.newClient(name);
    return ok({ code: client.form_code });
  }

  if (!["/state", "/draft", "/step", "/submit"].includes(path)) return fail("not found", 404);

  // Every other route names one client by its link code.
  const code = String((request.method === "GET" ? u.searchParams.get("code") : body.code) || "").trim();
  const client = await store.client(code);
  if (!client) return fail("this form link is not valid", 404, { invalid_link: true });
  if (await store.finished(client)) return ok(alreadySent());

  /* GET /state?code=: the shared draft. */
  if (path === "/state" && request.method === "GET") {
    const d = await store.draft(client.id);
    if (d && d.submission_id) return ok(alreadySent());
    return ok({ state: linkState(d && d.answers), client_name: client.client_name });
  }

  /* POST /draft: save answers as they are typed. Not checked yet (half-typed
     text is normal). Only the questions named are touched. */
  if (path === "/draft" && request.method === "POST") {
    const changes = draftEntries(body.answers, body.prefilled, now());
    if (!Object.keys(changes).length) return fail("nothing to save", 400);
    const row = await store.saveDraft(client.id, changes, savedBy(body.by_email, flatOf(changes)));
    if (row === "submitted") return ok(alreadySent());
    return ok({ ok: true, saved: Object.keys(changes), updated_at: row.updated_at || null });
  }

  /* POST /step: one page, checked, then saved into the shared draft. */
  if (path === "/step" && request.method === "POST") {
    const last = reviewStep();
    const step = Number(body.step);
    if (!(step >= 1 && step < last)) return fail(`step must be between 1 and ${last - 1}`, 400);
    const submitted = body.answers || {};
    // Check the page against everyone's answers, so a show_if question follows
    // an answer saved on another page.
    const d = await store.draft(client.id);
    const merged = { ...flatOf(d && d.answers), ...submitted };
    const errors = validateStep(step, merged);
    if (Object.keys(errors).length) return fail("some answers need attention", 400, { field_errors: errors });
    const page = {};
    for (const q of questionsForStep(step)) if (q.id in submitted) page[q.id] = submitted[q.id];
    const row = await store.saveDraft(client.id, draftEntries(page, [], now()), savedBy(body.by_email, merged));
    if (row === "submitted") return ok(alreadySent());
    const nextStep = Math.min(step + 1, last);
    await store.raiseStep(client.id, nextStep);
    return ok({ ok: true, next_step: nextStep, state: linkState(row.answers, nextStep) });
  }

  /* POST /submit: file the client's one form from the shared draft. */
  if (path === "/submit" && request.method === "POST") {
    const d = await store.draft(client.id);
    if (d && d.submission_id) return ok(alreadySent());
    const early = validateAll(flatOf(d && d.answers));
    if (!d || Object.keys(early).length) {
      return fail("the form is not complete", 400, { field_errors: d ? early : validateAll({}) });
    }

    // Claim: of two Submits at once, only one gets past here.
    const claimedAt = await store.claim(client.id);
    if (!claimedAt) return ok(alreadySent());

    let form;
    try {
      // File what the draft holds NOW (a save may have landed since the read above).
      const now_ = await store.draft(client.id);
      const answers = (now_ && now_.answers) || {};
      const flat = flatOf(answers);
      const late = validateAll(flat);
      if (Object.keys(late).length) {
        await store.release(client.id, claimedAt);
        return fail("the form is not complete", 400, { field_errors: late });
      }
      const text = (v) => (v == null || !String(v).trim() ? null : String(v).trim());
      form = await store.file({
        client_id: client.id,
        form_key: FORM_KEY,
        submitted_by_name: text(flat.full_name) || client.contact_name || null,
        submitted_by_email: savedBy(flat.email, {}) || savedBy(body.by_email, {}) || client.contact_email || null,
        company_name: text(flat.company_name) || client.client_name,
        answers: filedAnswers(answers),
        submitted_at: claimedAt,
      });
    } catch (e) {
      await store.release(client.id, claimedAt).catch(() => null);   // nothing filed: Submit can be tried again
      throw e;
    }
    await store.markFiled(client.id, form.id).catch(() => null);
    const told = tellAutomations(env, form);
    if (ctx && ctx.waitUntil) ctx.waitUntil(told);
    return ok({ ok: true, onboarding_form_id: form.id, state: { status: "complete", current_step: reviewStep(), answers: {} } });
  }

  return fail("not found", 404);
}

/* no-cache: the browser may keep a copy but must ask first, so a deploy is
   picked up on the very next load. */
function freshHeaders(from) {
  const h = new Headers(from);
  h.set("Cache-Control", "no-cache");
  return h;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname.startsWith(ROUTE + "/")) {
      const path = url.pathname.slice(ROUTE.length);
      try {
        return await handleApi(request, env, path, ctx);
      } catch (e) {
        return fail("server error: " + String(e.message).slice(0, 300), 500);
      }
    }

    // The form is at /form (a new client) and /form/<code> (a client's own
    // link). Both are the same page; it reads the code from the address. The
    // page's asset paths are absolute, so they work under /form/<code> too.
    if (url.pathname === "/form" || url.pathname === "/form/" || url.pathname === "/form/index.html" ||
        /^\/form\/[^/.]+\/?$/.test(url.pathname)) {
      const page = await env.ASSETS.fetch(new Request(new URL("/form/", url), request));
      if (!page.ok) return page;
      const html = (await page.text()).replace(
        /(\/form\/(?:app|config)\.js|\/form\/styles\.css)"/g, "$1?v=" + BUILD_ID + '"');
      return new Response(html, { status: 200, headers: freshHeaders(page.headers) });
    }

    // The form's own script and styles: always checked, never served stale.
    if (/^\/form\/[^/]+\.(js|css)$/.test(url.pathname)) {
      const asset = await env.ASSETS.fetch(request);
      if (!asset.ok) return asset;
      return new Response(asset.body, { status: asset.status, headers: freshHeaders(asset.headers) });
    }

    return env.ASSETS.fetch(request);
  },
};
