/* ============================================================================
   The onboarding form: the browser half.

   Everything about the form arrives at run time:
     * window.ONBOARDING_FORM (config.js): which route the server answers on
     * GET <route>/flow: the questions, the page titles, the box at the top of
       page 1 (`intro`) and the thank-you page (`done`)
   So the questions live in one file (questions.json, served by the worker) and
   this page never holds them in its code.

   Two addresses:
     * /form/<code>  a client's own link. ONE draft on the server, shared by
                     everyone who opens the link. Answers save as people type.
                     This browser keeps nothing.
     * /form         no code: ask the company name, make a new client, then
                     carry on at /form/<code>.
   ========================================================================= */

(function () {
  "use strict";

  var CFG = window.ONBOARDING_FORM || {};
  var API = CFG.api === undefined ? "" : CFG.api;
  var ROUTE = CFG.route || "/api/onboarding";

  var EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  var URL_RE = /^(https?:\/\/)?[^\s.]+\.[^\s]{2,}$/i;

  var S = {
    code: "",
    flow: [],
    steps: [],
    reviewStep: 2,
    step: 1,
    intro: null,       // the box at the top of page 1, from the questions file
    done: null,        // the thank-you page, from the questions file
    agency: "",        // the agency's name, from the settings table
    clientName: "",
    answers: {},       // { qid: value }
    prefilled: {},     // { qid: true }
    errors: {},        // { qid: message }
    busy: false,
    submitted: false,
    alreadySent: false,

    dirty: {},          // { qid: value } typed but not saved yet
    prefillDirty: {},   // { qid: true } of those, the ones the link filled in
    beforeNone: {},     // { qid: what was typed } before the none tick was ticked
    saveTimer: null,
    inflight: null,
    retryMs: 0,
    saveState: "saved"  // saved | pending | saving | retrying | failed
  };

  /* ---------- small helpers ---------------------------------------------- */

  var $ = function (id) { return document.getElementById(id); };

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      if (k === "class") n.className = attrs[k];
      else if (k === "text") n.textContent = attrs[k];
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) {
        n.setAttribute(k, attrs[k]);
      }
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(c); });
    return n;
  }

  function api(path, opts) {
    opts = opts || {};
    return fetch(API + path, {
      method: opts.method || "GET",
      headers: opts.body ? { "Content-Type": "application/json" } : {},
      body: opts.body ? JSON.stringify(opts.body) : undefined
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, status: r.status, json: j }; });
    });
  }

  function qs() {
    var out = {}, s = window.location.search.replace(/^\?/, "");
    if (!s) return out;
    s.split("&").forEach(function (pair) {
      if (!pair) return;
      var i = pair.indexOf("=");
      var k = decodeURIComponent((i < 0 ? pair : pair.slice(0, i)).replace(/\+/g, " "));
      var v = i < 0 ? "" : decodeURIComponent(pair.slice(i + 1).replace(/\+/g, " "));
      out[k] = v;
    });
    return out;
  }

  function byStep(n) {
    return S.flow.filter(function (q) { return q.step === n; });
  }

  function isBlank(v) {
    return v === null || v === undefined || (typeof v === "string" && !v.trim());
  }

  function asArray(v) {
    return Array.isArray(v) ? v : (isBlank(v) ? [] : [v]);
  }

  // A show_if question only exists while its controlling answer matches.
  // The server keeps the same rule; this keeps the page honest.
  function visible(q) {
    if (!q.show_if) return true;
    var c = q.show_if;
    var v = S.answers[c.question];
    if (c.includes !== undefined) return asArray(v).map(String).indexOf(String(c.includes)) >= 0;
    var s = String(v === undefined || v === null ? "" : v).trim();
    if (c.equals_any) return c.equals_any.map(String).indexOf(s) >= 0;
    return s === String(c.equals);
  }

  function visibleByStep(n) {
    return byStep(n).filter(visible);
  }

  function stepMeta(n) {
    for (var i = 0; i < S.steps.length; i++) if (S.steps[i].step === n) return S.steps[i];
    return { step: n, title: "Step " + n, blurb: "" };
  }

  /* ---------- checks: the same as the server, which has the last word ----- */

  function noneValue(q) { return (q.none_option && q.none_option.value) || ""; }
  function isNone(q, v) { return !!noneValue(q) && typeof v === "string" && v.trim() === noneValue(q); }

  function validate(q, v) {
    if (isNone(q, v)) return null;
    if (q.type === "checkbox") {
      if (q.required && v !== true) return "please complete this before you continue";
      if (v != null && typeof v !== "boolean") return "please choose yes or not yet";
      return null;
    }
    if (q.type === "single_select") {
      if (isBlank(v)) return q.required ? "please choose one" : null;
      if ((q.options || []).indexOf(String(v)) < 0) return "please choose one of the options";
      return null;
    }
    if (q.type === "multi_select") {
      var arr = asArray(v);
      if (!arr.length) return q.required ? "please choose at least one option" : null;
      var bad = arr.some(function (x) { return (q.options || []).indexOf(String(x)) < 0; });
      if (bad) return "please choose from the options";
      return null;
    }
    if (isBlank(v)) return q.required ? "this field is required" : null;
    var s = String(v).trim();
    if (q.type === "email" && !EMAIL_RE.test(s)) return "please enter a valid email address";
    if (q.type === "url" && !URL_RE.test(s)) return "please enter a valid web address";
    return null;
  }

  function validateStep(n) {
    var errs = {};
    visibleByStep(n).forEach(function (q) {
      var e = validate(q, S.answers[q.id]);
      if (e) errs[q.id] = e;
    });
    return errs;
  }

  /* ---------- the link ---------------------------------------------------- */

  // The one path part after /form/, or "" on the plain /form address.
  function codeFromPath() {
    var m = /^\/form\/([^\/.]+)\/?$/.exec(window.location.pathname || "");
    return m ? decodeURIComponent(m[1]) : "";
  }

  // The link's ?email=&company_name= (a question's id or its prefill key) fill
  // only answers that are still empty: what anyone saved before always wins.
  function fillFromQuery() {
    var p = qs();
    S.flow.forEach(function (q) {
      if (!q.prefill) return;
      var v = p[q.id] !== undefined ? p[q.id] : p[q.prefill];
      if (v && String(v).trim() && isBlank(S.answers[q.id])) {
        S.answers[q.id] = String(v).trim();
        S.prefilled[q.id] = true;
        S.dirty[q.id] = S.answers[q.id];
        S.prefillDirty[q.id] = true;
      }
    });
    if (Object.keys(S.dirty).length) scheduleSave(0);
  }

  // Take the server's answers for every question with nothing unsaved here, so
  // this window shows what other windows saved.
  function adoptServer(answers) {
    Object.keys(answers || {}).forEach(function (qid) {
      if (qid in S.dirty) return;
      S.answers[qid] = (answers[qid] || {}).value;
    });
  }

  /* ---------- saving as people type --------------------------------------- */

  var SAVE_TEXT = {
    saved: "Saved",
    pending: "Saving…",
    saving: "Saving…",
    retrying: "Not saved yet. Trying again…",
    failed: "Not saved. Please refresh the page."
  };

  function setSaveState(st) {
    S.saveState = st;
    var n = $("saveStatus");
    if (!n) return;
    n.textContent = SAVE_TEXT[st] || "";
    n.setAttribute("data-state", st);
    n.hidden = !S.code || S.submitted;
  }

  function scheduleSave(ms) {
    if (!S.code || S.submitted) return;
    clearTimeout(S.saveTimer);
    S.saveTimer = setTimeout(flushSave, ms === undefined ? 800 : ms);
    if (S.saveState !== "retrying" && S.saveState !== "saving") setSaveState("pending");
  }

  // Send everything typed since the last save. Resolves true once nothing is
  // left unsaved, false when the save failed (it then retries by itself).
  function flushSave() {
    clearTimeout(S.saveTimer);
    S.saveTimer = null;
    if (!S.code || S.submitted) return Promise.resolve(true);
    if (S.inflight) return S.inflight.then(function () { return flushSave(); });
    var ids = Object.keys(S.dirty);
    if (!ids.length) {
      if (S.saveState !== "failed") setSaveState("saved");
      return Promise.resolve(true);
    }
    var batch = {}, pre = [];
    ids.forEach(function (id) {
      batch[id] = S.dirty[id];
      if (S.prefillDirty[id]) pre.push(id);
    });
    S.dirty = {};
    S.prefillDirty = {};
    setSaveState("saving");
    function putBack() {   // anything typed since is newer, and stays
      ids.forEach(function (id) { if (!(id in S.dirty)) S.dirty[id] = batch[id]; });
    }
    S.inflight = api(ROUTE + "/draft", {
      method: "POST",
      body: { code: S.code, answers: batch, prefilled: pre, by_email: qs().email || "" }
    }).then(function (r) {
      S.inflight = null;
      if (r.ok && r.json.data && r.json.data.already_submitted) { showAlreadySent(); return false; }
      if (!r.ok) {
        if (r.status >= 400 && r.status < 500 && r.status !== 408 && r.status !== 429) {
          putBack();
          setSaveState("failed");   // the link stopped working: trying again cannot help
          return false;
        }
        throw new Error("save failed: " + r.status);
      }
      S.retryMs = 0;
      if (Object.keys(S.dirty).length) return flushSave();
      setSaveState("saved");
      return true;
    }).catch(function () {
      S.inflight = null;
      putBack();
      S.retryMs = Math.min((S.retryMs || 1000) * 2, 30000);
      setSaveState("retrying");
      clearTimeout(S.saveTimer);
      S.saveTimer = setTimeout(flushSave, S.retryMs);
      return false;
    });
    return S.inflight;
  }

  function hydrate(state) {
    S.step = Math.min(state.current_step || 1, S.reviewStep);
    S.answers = {};
    S.prefilled = {};
    Object.keys(state.answers || {}).forEach(function (qid) {
      var entry = state.answers[qid] || {};
      S.answers[qid] = entry.value;
      if (entry.prefilled) S.prefilled[qid] = true;
    });
    if (state.status === "complete") S.submitted = true;
  }

  /* ---------- start ------------------------------------------------------- */

  function boot() {
    api(ROUTE + "/flow").then(function (r) {
      if (!r.ok) return fatal("We could not load the form. Please refresh the page.");
      var d = r.json.data;
      S.flow = d.flow;
      S.steps = d.steps;
      S.reviewStep = d.review_step;
      S.intro = d.intro || null;
      S.done = d.done || null;
      S.agency = d.agency_name || "";
      showAgency();

      S.code = codeFromPath();
      if (!S.code) return startScreen();
      return api(ROUTE + "/state?code=" + encodeURIComponent(S.code)).then(function (sr) {
        if (!sr.ok) {
          S.code = "";
          return fatal(sr.status === 404
            ? "This form link is not valid. Please ask us for a new one."
            : "We could not load your form. Please refresh the page.",
            sr.status === 404 ? "This link does not work" : null);
        }
        var data = sr.json.data;
        if (data.already_submitted) S.alreadySent = true;
        S.clientName = data.client_name || "";
        hydrate(data.state);
        if (!S.submitted) fillFromQuery();
        render();
      });
    }).catch(function () {
      fatal("We could not reach the server. Please check your connection and refresh the page.");
    });
  }

  // The agency's name in the header and the tab title, from the settings table.
  function showAgency() {
    var name = S.agency || "";
    var mark = $("wordmark");
    if (mark) mark.textContent = name;
    var foot = $("footName");
    if (foot) foot.textContent = name;
    document.title = "Client onboarding" + (name ? " · " + name : "");
  }

  // No code in the address: ask the company name, make the client, then open
  // the client's own link. The rest of the form runs on that link.
  function startScreen() {
    $("rail").innerHTML = "";
    var card = $("card");
    card.innerHTML = "";
    var input = el("input", { id: "in-start-company", type: "text", placeholder: "e.g. Example Co",
                              autocomplete: "organization", "data-testid": "input-start-company" });
    input.value = qs().company_name || qs().company || "";
    var err = el("p", { class: "field-error", "data-testid": "error-start-company" });
    var go = el("button", { class: "btn btn-primary", type: "button", text: "Start the form",
                            "data-testid": "btn-start" });
    function start() {
      var name = input.value.replace(/\s+/g, " ").trim();
      if (name.length < 2) {
        err.textContent = "please enter your company name";
        input.parentNode.setAttribute("data-invalid", "1");
        return;
      }
      go.disabled = true;
      go.textContent = "Starting…";
      api(ROUTE + "/start", { method: "POST", body: { company_name: name } }).then(function (r) {
        if (!r.ok || !r.json.data || !r.json.data.code) {
          go.disabled = false;
          go.textContent = "Start the form";
          err.textContent = "We could not start the form. Please try again.";
          return;
        }
        var p = qs(), q = ["company_name=" + encodeURIComponent(name)];
        if (p.email) q.push("email=" + encodeURIComponent(p.email));
        if (p.name) q.push("name=" + encodeURIComponent(p.name));
        window.location.replace("/form/" + encodeURIComponent(r.json.data.code) + "?" + q.join("&"));
      }).catch(function () {
        go.disabled = false;
        go.textContent = "Start the form";
        err.textContent = "We could not reach the server. Please try again.";
      });
    }
    go.addEventListener("click", start);
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") start(); });
    var label = el("label", { class: "field-label", for: "in-start-company" });
    label.appendChild(document.createTextNode("Company name"));
    label.appendChild(el("span", { class: "req", text: "*", "aria-label": "required" }));
    card.appendChild(el("div", { "data-testid": "start-screen" }, [
      el("p", { class: "eyebrow", text: "Client onboarding" }),
      el("h1", { text: "Welcome. Let's get you set up." }),
      el("p", { class: "blurb", text: "Tell us your company name to start. If someone sent you a link for your company, use that link instead, so your team fills in one form together." }),
      el("div", { class: "field" }, [label, input, err]),
      el("div", { class: "nav" }, [el("span", { class: "nav-spacer" }), go])
    ]));
    input.focus();
  }

  function fatal(msg, heading) {
    $("card").innerHTML = "";
    $("card").appendChild(el("div", { class: "centred", "data-testid": "fatal" }, [
      el("h1", { text: heading || "Something went wrong" }),
      el("p", { class: "blurb", text: msg })
    ]));
    $("rail").innerHTML = "";
  }

  /* ---------- the progress rail ------------------------------------------- */

  function renderRail() {
    var rail = $("rail");
    rail.innerHTML = "";
    if (S.submitted) return;
    S.steps.forEach(function (meta, i) {
      if (i > 0) {
        rail.appendChild(el("div", { class: "rail-line", "data-state": meta.step <= S.step ? "done" : "todo" }));
      }
      var state = meta.step === S.step ? "active" : (meta.step < S.step ? "done" : "todo");
      var clickable = meta.step < S.step;
      var btn = el("button", {
        class: "rail-step", type: "button",
        "data-state": state, "data-clickable": clickable ? "1" : "0",
        "data-testid": "rail-step-" + meta.step,
        "aria-current": state === "active" ? "step" : null
      }, [
        el("span", { class: "rail-dot", text: state === "done" ? "✓" : String(meta.step) }),
        el("span", { class: "rail-label", text: meta.title })
      ]);
      if (clickable) btn.addEventListener("click", function () { goTo(meta.step); });
      rail.appendChild(btn);
    });
  }

  /* ---------- one question ------------------------------------------------ */

  function fieldNode(q) {
    var wrap = el("div", { class: "field", "data-field": q.id, "data-invalid": S.errors[q.id] ? "1" : null });

    var label = el("label", { class: "field-label", for: "in-" + q.id });
    label.appendChild(document.createTextNode(q.label));
    if (q.required) label.appendChild(el("span", { class: "req", text: "*", "aria-label": "required" }));
    else label.appendChild(el("span", { class: "opt", text: "optional" }));
    wrap.appendChild(label);

    if (q.help) wrap.appendChild(el("p", { class: "field-help", text: q.help }));

    if (q.info) {
      var ib = el("button", { class: "info-btn", type: "button", "data-testid": "info-" + q.id, text: "ⓘ  " + q.info.title });
      ib.addEventListener("click", function () { openModal(q.info); });
      wrap.appendChild(ib);
    }

    if (q.links && q.links.length) {
      var lw = el("div", { class: "field-links" });
      q.links.forEach(function (l) {
        lw.appendChild(el("a", { href: l.url, target: "_blank", rel: "noopener noreferrer",
                                 text: l.label + " ↗", "data-testid": "link-" + q.id }));
      });
      wrap.appendChild(lw);
    }

    if (q.type === "checkbox") {
      wrap.appendChild(checkboxCards(q));
    } else if (q.type === "single_select") {
      wrap.appendChild(selectCards(q, false));
    } else if (q.type === "multi_select") {
      wrap.appendChild(selectCards(q, true));
    } else if (q.type === "long_text") {
      if (q.chips && q.chips.length) wrap.appendChild(chipRow(q));
      var ta = el("textarea", { id: "in-" + q.id, rows: q.rows || 4, placeholder: q.placeholder || "",
                                "data-testid": "input-" + q.id });
      ta.value = isNone(q, S.answers[q.id]) ? "" : (S.answers[q.id] || "");
      ta.addEventListener("input", function () { setAnswer(q.id, ta.value); });
      ta.addEventListener("blur", function () { flushSave(); });
      if (isNone(q, S.answers[q.id])) ta.hidden = true;
      wrap.appendChild(ta);
      if (q.none_option) wrap.appendChild(noneTick(q));
    } else {
      var type = q.type === "email" ? "email" : (q.type === "url" ? "url" : "text");
      var inp = el("input", { id: "in-" + q.id, type: type, placeholder: q.placeholder || "",
                              "data-testid": "input-" + q.id, autocomplete: q.type === "email" ? "email" : "off" });
      inp.value = isNone(q, S.answers[q.id]) ? "" : (S.answers[q.id] || "");
      inp.addEventListener("input", function () { setAnswer(q.id, inp.value); });
      inp.addEventListener("blur", function () { flushSave(); });
      if (isNone(q, S.answers[q.id])) inp.hidden = true;
      wrap.appendChild(inp);
      if (q.none_option) wrap.appendChild(noneTick(q));
      if (S.prefilled[q.id] && !isNone(q, S.answers[q.id])) {
        wrap.appendChild(el("p", { class: "field-help prefilled-note",
                                   text: "Filled in from your link. Change it if it is not right." }));
      }
    }

    wrap.appendChild(el("p", { class: "field-error", "data-testid": "error-" + q.id, text: S.errors[q.id] || "" }));
    return wrap;
  }

  // The tick under a text box ("We do not have one yet", "I need help with
  // this, let's do it on the call"). Ticked, the box goes and the answer is
  // the tick's own text. Unticked, what was typed comes back.
  function noneTick(q) {
    var on = isNone(q, S.answers[q.id]);
    var cb = el("input", { type: "checkbox", id: "none-" + q.id, "data-testid": "none-" + q.id });
    cb.checked = on;
    cb.addEventListener("change", function () {
      if (cb.checked) {
        S.beforeNone[q.id] = isNone(q, S.answers[q.id]) ? "" : (S.answers[q.id] || "");
        setAnswer(q.id, noneValue(q));
      } else {
        setAnswer(q.id, S.beforeNone[q.id] || "");
      }
      flushSave();
      render();
    });
    return el("label", { class: "none-tick", for: "none-" + q.id, "data-checked": on ? "1" : "0" }, [
      cb, el("span", { text: q.none_option.label })
    ]);
  }

  function checkboxCards(q) {
    var v = S.answers[q.id];
    var opts = [
      { val: true, t: "Yes, this is done", d: "Choose this when you have done the step above." },
      { val: false, t: "Not yet", d: q.required
          ? "We need this before we can start. Come back to it. Your answers are saved."
          : "That is fine. We will do it with you on the onboarding call." }
    ];
    var box = el("div", { class: "cards", role: "radiogroup", "aria-label": q.label });
    opts.forEach(function (o) {
      var sel = v === o.val;
      var card = el("label", { class: "opt-card", "data-selected": sel ? "1" : "0",
                               "data-testid": "option-" + q.id + "-" + (o.val ? "yes" : "no") });
      var radio = el("input", { type: "radio", name: "r-" + q.id });
      radio.checked = sel;
      radio.addEventListener("change", function () { setAnswer(q.id, o.val); flushSave(); render(); });
      card.appendChild(radio);
      card.appendChild(el("span", {}, [el("span", { class: "t", text: o.t }), el("span", { class: "d", text: o.d })]));
      box.appendChild(card);
    });
    return box;
  }

  // Option cards from the question's own options: radios for single_select,
  // ticks for multi_select. A new option is an edit to questions.json only.
  function selectCards(q, multi) {
    var cur = multi ? asArray(S.answers[q.id]).map(String) : [String(S.answers[q.id])];
    var box = el("div", { class: "cards", role: multi ? "group" : "radiogroup", "aria-label": q.label });
    (q.options || []).forEach(function (opt) {
      var sel = cur.indexOf(String(opt)) >= 0;
      var card = el("label", { class: "opt-card", "data-selected": sel ? "1" : "0",
                               "data-testid": "option-" + q.id + "-" + String(opt).toLowerCase().replace(/[^a-z0-9]+/g, "-") });
      var input = el("input", { type: multi ? "checkbox" : "radio", name: "r-" + q.id });
      input.checked = sel;
      input.addEventListener("change", function () {
        if (multi) {
          var next = asArray(S.answers[q.id]).map(String);
          var i = next.indexOf(String(opt));
          if (input.checked) { if (i < 0) next.push(String(opt)); }
          else if (i >= 0) { next.splice(i, 1); }
          setAnswer(q.id, next);
        } else {
          setAnswer(q.id, opt);
        }
        flushSave();
        render();
      });
      card.appendChild(input);
      var help = (q.option_help || {})[opt];
      card.appendChild(el("span", {}, [
        el("span", { class: "t", text: String(opt) }),
        help ? el("span", { class: "d", text: help }) : null
      ]));
      box.appendChild(card);
    });
    return box;
  }

  function chipRow(q) {
    var row = el("div", { class: "chips" });
    q.chips.forEach(function (c) {
      // A chip is a plain string (the label is the text it adds) or {label, starter}.
      var label = (c && c.label) || String(c);
      var starter = (c && c.starter !== undefined && c.starter !== null) ? c.starter : label;
      var b = el("button", { class: "chip", type: "button", text: label,
                             "data-testid": "chip-" + q.id + "-" + label.toLowerCase().replace(/[^a-z0-9]+/g, "-") });
      b.addEventListener("click", function () {
        var cur = S.answers[q.id] || "";
        var gap = cur && !/\n$/.test(cur) ? "\n" : "";
        setAnswer(q.id, cur + gap + starter);
        flushSave();
        var ta = $("in-" + q.id);
        if (ta) { ta.value = S.answers[q.id]; ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
      });
      row.appendChild(b);
    });
    return row;
  }

  function setAnswer(qid, val) {
    S.answers[qid] = val;
    S.dirty[qid] = val;
    delete S.prefillDirty[qid];
    scheduleSave();
    if (S.errors[qid]) {
      delete S.errors[qid];
      var f = document.querySelector('[data-field="' + qid + '"]');
      if (f) f.setAttribute("data-invalid", "0");
    }
  }

  /* ---------- the review page --------------------------------------------- */

  function displayValue(q) {
    var v = S.answers[q.id];
    if (q.type === "checkbox") {
      if (v === true) return { text: "Yes, done", cls: "yes" };
      return { text: v === false ? "Not yet" : "Not answered", cls: v === false ? "no" : "empty" };
    }
    if (q.type === "multi_select") {
      var arr = asArray(v);
      return arr.length ? { text: arr.join(", "), cls: "" } : { text: "Not answered", cls: "empty" };
    }
    if (isBlank(v)) return { text: "Not answered", cls: "empty" };
    return { text: String(v), cls: "" };
  }

  function reviewNode() {
    var frag = document.createDocumentFragment();
    S.steps.forEach(function (meta) {
      if (meta.step >= S.reviewStep) return;
      var list = visibleByStep(meta.step);
      if (!list.length) return;
      var head = el("h2", {}, [el("span", { text: meta.title })]);
      var edit = el("button", { class: "edit-link", type: "button", text: "Edit", "data-testid": "edit-step-" + meta.step });
      edit.addEventListener("click", function () { goTo(meta.step); });
      head.appendChild(edit);
      var g = el("div", { class: "review-group", "data-testid": "review-group-" + meta.step }, [head]);
      list.forEach(function (q) {
        var d = displayValue(q);
        g.appendChild(el("div", { class: "review-row" }, [
          el("p", { class: "review-q", text: q.label }),
          el("p", { class: "review-a " + d.cls, text: d.text, "data-testid": "review-value-" + q.id })
        ]));
      });
      frag.appendChild(g);
    });
    return frag;
  }

  /* ---------- drawing ----------------------------------------------------- */

  // The step on screen now. Drawing the SAME step again (a click, a failed
  // check, a question appearing) keeps the scroll place. Only a new step
  // scrolls to the top.
  var drawnStep = null;

  // render() is the safe wrapper; draw() does the work. A drawing bug shows
  // as a drawing problem, never as "we could not reach the server".
  function render() {
    try {
      draw();
    } catch (e) {
      if (window.console && console.error) console.error("onboarding form: drawing failed", e);
      showBanner("Something went wrong on this page. Your answers are saved. Please refresh the page.");
    }
  }

  // The grey box at the top of page 1: how long it takes, that it saves, and
  // what to have ready before you start.
  function introNode() {
    var i = S.intro || {};
    var lines = [];
    if (i.minutes) lines.push(el("p", {}, [el("strong", { text: "This takes about " + i.minutes + " minutes." })]));
    lines.push(el("p", { text: "Your answers save as you type. Anyone with this link sees the same answers, " +
                                 "so your team can fill it in with you. Close the page when you like, and open " +
                                 "the link again to carry on." }));
    if (i.bring && i.bring.length) {
      lines.push(el("p", { text: "Have these ready before you start:" }));
      var ul = el("ul");
      i.bring.forEach(function (b) { ul.appendChild(el("li", { text: b })); });
      lines.push(ul);
    }
    return el("div", { class: "note", "data-testid": "intro-box" }, lines);
  }

  function draw() {
    var card = $("card");
    var sameStep = drawnStep === S.step && !S.submitted;
    var keepY = sameStep ? (window.scrollY || window.pageYOffset || 0) : 0;

    // Drawing again removes the control that had focus. Remember it by its
    // testid, so focus goes back to the new one.
    var focusKey = null;
    if (sameStep && document.activeElement && document.activeElement.closest) {
      var holder = document.activeElement.closest("[data-testid]");
      if (holder) focusKey = holder.getAttribute("data-testid");
    }

    renderRail();
    card.innerHTML = "";
    $("saveHint").hidden = true;

    if (S.submitted) return renderDone(card);

    var meta = stepMeta(S.step);
    var isReview = S.step === S.reviewStep;

    card.appendChild(el("p", {
      class: "eyebrow",
      text: "Step " + S.step + " of " + S.reviewStep + (S.clientName ? " · " + S.clientName : "")
    }));
    card.appendChild(el("h1", { text: isReview ? "Check your answers" : meta.title }));
    if (meta.blurb) card.appendChild(el("p", { class: "blurb", text: meta.blurb }));

    card.appendChild(el("div", { class: "banner", id: "banner", "data-testid": "form-banner" }));

    if (S.step === 1) card.appendChild(introNode());

    if (isReview) card.appendChild(reviewNode());
    else visibleByStep(S.step).forEach(function (q) { card.appendChild(fieldNode(q)); });

    var back = el("button", { class: "btn btn-ghost", type: "button", text: "Back", "data-testid": "btn-back" });
    back.addEventListener("click", function () { goTo(S.step - 1); });
    var next = el("button", { class: "btn btn-primary", type: "button",
                              text: isReview ? "Submit the form" : "Continue",
                              "data-testid": isReview ? "btn-submit" : "btn-continue" });
    next.addEventListener("click", isReview ? submit : advance);
    var nav = el("div", { class: "nav" });
    if (S.step > 1) nav.appendChild(back);
    nav.appendChild(el("span", { class: "nav-spacer" }));
    nav.appendChild(next);
    card.appendChild(nav);

    var hint = $("saveHint");
    hint.hidden = false;
    hint.textContent = "Saved as you type. Anyone with this link sees the same answers.";
    setSaveState(S.saveState);

    drawnStep = S.step;

    if (sameStep) {
      window.scrollTo({ top: keepY });
      if (focusKey) {
        var again = card.querySelector('[data-testid="' + focusKey + '"]');
        if (again) {
          var control = again.querySelector("input, textarea, select, button") || again;
          if (control.focus) control.focus({ preventScroll: true });
        }
      }
    } else {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  // The thank-you page comes from the `done` block in questions.json.
  function renderDone(card) {
    $("rail").innerHTML = "";
    $("saveHint").hidden = true;
    if ($("saveStatus")) $("saveStatus").hidden = true;
    drawnStep = null;
    var d = S.done || {};

    card.appendChild(el("div", { class: "centred", "data-testid": "done-screen" }, [
      el("div", { class: "tick", text: "✓" }),
      el("h1", { text: S.alreadySent ? "This form is already in" : (d.heading || "That's everything. Thank you.") }),
      S.alreadySent
        ? el("p", { class: "blurb", "data-testid": "already-sent",
                    text: "We have the answers for your company, so there is nothing more to fill in. If something has changed, tell us on the onboarding call." })
        : (d.blurb ? el("p", { class: "blurb", text: d.blurb }) : null)
    ]));

    if (d.next && (d.next.items || []).length) {
      var nb = el("div", { class: "done-block", "data-testid": "next-block" }, [
        d.next.heading ? el("h2", { text: d.next.heading }) : null
      ]);
      var ol = el("ol", { class: "done-steps" });
      d.next.items.forEach(function (item, i) { ol.appendChild(el("li", { text: item, "data-testid": "next-item-" + i })); });
      nb.appendChild(ol);
      card.appendChild(nb);
    }

    (d.links || []).forEach(function (l, i) {
      if (!l.url) return;
      card.appendChild(el("div", { class: "done-block", "data-testid": "done-link-" + i }, [
        l.heading ? el("h2", { text: l.heading }) : null,
        l.body ? el("p", { class: "done-body", text: l.body }) : null,
        el("p", { style: "margin:0" }, [
          el("a", { class: "done-link", href: l.url, target: "_blank", rel: "noopener noreferrer",
                    text: (l.cta || "Open") + " ↗", "data-testid": "done-link-a-" + i })
        ])
      ]));
    });
  }

  /* ---------- moving between pages --------------------------------------- */

  function goTo(n) {
    if (n < 1 || n > S.reviewStep || S.busy) return;
    S.errors = {};
    S.step = n;
    render();
  }

  function showBanner(msg) {
    var b = $("banner");
    if (!b) return;
    b.textContent = msg;
    b.setAttribute("data-show", "1");
  }

  function advance() {
    if (S.busy) return;
    S.errors = validateStep(S.step);
    if (Object.keys(S.errors).length) {
      render();
      showBanner("Please check the answers marked in red before you continue.");
      var first = document.querySelector('[data-invalid="1"]');
      if (first) first.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    var payload = {};
    visibleByStep(S.step).forEach(function (q) {
      var v = S.answers[q.id];
      if (q.type === "checkbox") { if (typeof v === "boolean") payload[q.id] = v; }
      else if (q.type === "multi_select") payload[q.id] = asArray(v);
      else payload[q.id] = (v === undefined || v === null ? "" : v);
    });

    setBusy(true, "Saving…");
    flushSave().then(function () {
      return api(ROUTE + "/step", { method: "POST",
        body: { code: S.code, step: S.step, answers: payload, by_email: qs().email || "" } });
    }).then(function (r) {
      setBusy(false);
      if (!r.ok) {
        S.errors = (r.json && r.json.field_errors) || {};
        render();
        showBanner(Object.keys(S.errors).length
          ? "Please check the answers marked in red before you continue."
          : "We could not save that. Please try again.");
        return;
      }
      if (r.json.data.already_submitted) return showAlreadySent();
      S.step = r.json.data.next_step;
      S.errors = {};
      // Someone else on the same link may have saved other pages meanwhile.
      adoptServer((r.json.data.state || {}).answers);
      render();
    }).catch(function () {
      setBusy(false);
      showBanner("We could not reach the server. Your answers are still here. Please try again.");
    });
  }

  function submit() {
    if (S.busy) return;
    var errs = {};
    for (var n = 1; n < S.reviewStep; n++) {
      var e = validateStep(n);
      Object.keys(e).forEach(function (k) { errs[k] = e[k]; });
    }
    if (Object.keys(errs).length) {
      S.errors = errs;
      for (var m = 1; m < S.reviewStep; m++) {
        if (Object.keys(validateStep(m)).length) { S.step = m; break; }
      }
      render();
      showBanner("Some answers are still missing. We have taken you back to them.");
      return;
    }

    setBusy(true, "Sending…");
    flushSave().then(function (saved) {
      if (!saved) return { ok: false, status: 0, unsaved: true, json: {} };
      return api(ROUTE + "/submit", { method: "POST", body: { code: S.code, by_email: qs().email || "" } });
    }).then(function (r) {
      setBusy(false);
      if (r.unsaved) {
        showBanner("We could not save your latest answers, so the form was not sent. Please try again.");
        return;
      }
      if (!r.ok) {
        // The server checks what everyone saved: go to the first page with a gap.
        S.errors = (r.json && r.json.field_errors) || {};
        var bad = S.flow.filter(function (q) { return S.errors[q.id]; }).map(function (q) { return q.step; });
        if (bad.length) S.step = Math.min.apply(null, bad);
        render();
        showBanner(bad.length
          ? "Some answers are still missing. We have taken you back to them."
          : "We could not send the form. Please try again.");
        return;
      }
      if (r.json.data.already_submitted) return showAlreadySent();
      S.submitted = true;
      render();
    }).catch(function () {
      setBusy(false);
      showBanner("We could not reach the server. Nothing was lost. Please try again.");
    });
  }

  function showAlreadySent() {
    S.alreadySent = true;
    S.submitted = true;
    S.errors = {};
    render();
  }

  function setBusy(on, label) {
    S.busy = on;
    var b = document.querySelector('[data-testid="btn-continue"], [data-testid="btn-submit"]');
    if (!b) return;
    b.disabled = on;
    if (on) { b.dataset.was = b.textContent; b.textContent = label || "Working…"; }
    else if (b.dataset.was) { b.textContent = b.dataset.was; }
  }

  /* ---------- the info window --------------------------------------------- */

  function openModal(info) {
    $("modalTitle").textContent = info.title;
    var ul = $("modalBody");
    ul.innerHTML = "";
    (info.items || []).forEach(function (line) { ul.appendChild(el("li", { text: line })); });
    $("modalBack").setAttribute("data-open", "1");
  }

  function closeModal() { $("modalBack").removeAttribute("data-open"); }

  $("modalClose").addEventListener("click", closeModal);
  $("modalBack").addEventListener("click", function (e) { if (e.target === $("modalBack")) closeModal(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeModal(); });

  boot();
})();
