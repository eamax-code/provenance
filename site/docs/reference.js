/* The API reference (GH #20): renders /openapi.json in the site's own layout. Text is set with
   textContent throughout; nothing from the description is parsed as HTML. */
(() => {
  const GROUPS = [
    ["companies", "Companies", "Identity, filings, facts and freshness for one company."],
    ["connections", "Connections", "Insiders, their other companies, 5% holders and subsidiaries, each with its filing."],
    ["ipos", "Going public", "Companies registering, effective, listing and pricing, each step with its filing."],
    ["facts", "Facts across companies", "Rank companies by a metric, optionally as of a date."],
    ["search", "Search", "Companies and passages from filing sections."],
    ["events", "Event feed", "New filings, officer changes and listing events, in order."],
    ["watches", "Watches", "Webhook and email alerts for a company or a market."],
    ["markets", "Listings", "Instruments, events and issuers in Canada, the UK and the EU."],
    ["exports", "Exports", "Bounded CSV and JSON downloads."],
    ["chat", "Chat", "Questions answered from the data, with citations."],
    ["developer", "Keys and usage", "Usage, keys, profile and key requests, with your API key."],
    ["public", "Public", "No key needed: plans, showcase companies and listing events."],
    ["operations", "Operations", "Health and readiness of this deployment."],
  ];
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  // `code` spans and **bold** in descriptions, built as nodes, never parsed as markup.
  const rich = (tag, text) => {
    const n = el(tag);
    String(text || "").split(/(`[^`]+`|\*\*[^*]+\*\*)/).forEach((part) => {
      if (part.startsWith("`")) n.append(el("code", null, part.slice(1, -1)));
      else if (part.startsWith("**")) n.append(el("strong", null, part.slice(2, -2)));
      else if (part) n.append(document.createTextNode(part));
    });
    return n;
  };
  let spec;
  const resolve = (s) => {
    let n = 0;
    while (s && s.$ref && n++ < 10) s = spec.components.schemas[s.$ref.split("/").pop()];
    return s || {};
  };
  const typeOf = (s) => {
    s = resolve(s);
    if (s.anyOf) return s.anyOf.map(typeOf).filter((t) => t !== "null").join(" or ") || "any";
    if (s.allOf && s.allOf.length === 1) return typeOf(s.allOf[0]);
    if (s.enum) return s.enum.join(" | ");
    if (s.type === "array") return `array of ${typeOf(s.items || {})}`;
    if (s.title && !s.type) return s.title;
    let t = s.format ? `${s.type} (${s.format})` : s.type || "object";
    if (s.title && s.type === "object") t = s.title;
    return t;
  };
  const limits = (s) => {
    s = resolve(s);
    const out = [];
    if (s.default !== undefined && s.default !== null) out.push(`default ${JSON.stringify(s.default)}`);
    if (s.minimum !== undefined) out.push(`min ${s.minimum}`);
    if (s.maximum !== undefined) out.push(`max ${s.maximum}`);
    if (s.pattern) out.push(s.pattern.replace(/^\^\(?|\)?\$$/g, "").replaceAll("|", ", "));
    if (s.maxLength) out.push(`up to ${s.maxLength} chars`);
    return out.join("; ");
  };
  const table = (head, rows) => {
    const wrap = el("div", "table-wrap");
    const t = el("table", "doc-table");
    const tr = el("tr");
    head.forEach((h) => { const th = el("th", null, h); th.scope = "col"; tr.append(th); });
    const thead = el("thead");
    thead.append(tr);
    t.append(thead);
    const body = el("tbody");
    rows.forEach((cells) => {
      const r = el("tr");
      cells.forEach((c) => { const td = el("td"); if (c instanceof Node) td.append(c); else td.textContent = c ?? ""; r.append(td); });
      body.append(r);
    });
    t.append(body);
    wrap.append(t);
    return wrap;
  };
  const fieldRows = (schema) => {
    const s = resolve(schema);
    const req = new Set(s.required || []);
    return Object.entries(s.properties || {}).map(([name, p]) => {
      const n = el("span");
      n.append(el("code", null, name));
      if (req.has(name)) n.append(el("span", "req", "required"));
      return [n, typeOf(p), rich("span", resolve(p).description || p.description || limits(p))];
    });
  };
  const authOf = (op) => {
    const sec = op.security;
    if (!sec || !sec.length) return "No key";
    if (sec.some((s) => s.AdminToken)) return "Admin token";
    return "API key";
  };
  // reference paths that the playground has as an endpoint of its own
  const PLAY = { "/v1/companies/search": "company-search", "/v1/companies": "company-list", "/v1/companies/{cik}": "company-profile", "/v1/companies/{cik}/filings": "company-filings", "/v1/companies/{cik}/facts": "company-facts", "/v1/companies/{cik}/freshness": "company-freshness", "/v1/facts/screen": "facts-screen", "/v1/events": "events", "/v1/markets/events": "listing-events", "/v1/markets/instruments": "listing-instruments", "/v1/markets/": "venues", "/v1/stats": "stats", "/v1/public/plans": "plans" };
  const SAMPLE = { cik: "320193", metric: "revenue", q: "apple", year: "2024", period: "annual", limit: "3" };
  const filled = (path, op) => {
    let p = path.replace(/\{(\w+)\}/g, (m, k) => SAMPLE[k] || m);
    const q = (op.parameters || []).filter((x) => x.in === "query" && (x.required || SAMPLE[x.name] && ["metric", "limit"].includes(x.name)))
      .map((x) => `${x.name}=${SAMPLE[x.name] || "…"}`).join("&");
    return p + (q ? `?${q}` : "");
  };
  const runnable = (method, path, op) => method === "get" && authOf(op) !== "Admin token" && !/\{(?!cik\})/.test(path) && !/stream|sessions|watches|usage|keys|profile|exports|developer/.test(path)
    && (op.parameters || []).filter((x) => x.in === "query" && x.required).every((x) => SAMPLE[x.name]);
  const sampleOf = (schema, depth = 0) => {
    const s = resolve(schema);
    if (s.anyOf) return sampleOf(s.anyOf.find((x) => resolve(x).type !== "null") || {}, depth);
    if (s.allOf && s.allOf.length === 1) return sampleOf(s.allOf[0], depth);
    if (s.enum) return s.enum[0];
    if (s.type === "array") return depth > 3 ? [] : [sampleOf(s.items || {}, depth + 1)];
    if (s.type === "object" || s.properties) {
      if (depth > 3) return {};
      const o = {};
      Object.entries(s.properties || {}).slice(0, 14).forEach(([k, v]) => { o[k] = sampleOf(v, depth + 1); });
      return o;
    }
    if (s.type === "integer" || s.type === "number") return 0;
    if (s.type === "boolean") return false;
    return s.format === "date" ? "2026-01-31" : s.format === "date-time" ? "2026-01-31T12:00:00Z" : "string";
  };
  const curl = (method, path, op, demo) => {
    const base = location.origin;
    const q = (op.parameters || []).filter((p) => p.in === "query" && p.required).map((p) => `${p.name}=…`).join("&");
    let line = `curl -s${method === "get" ? "" : ` -X ${method.toUpperCase()}`} "${base}${demo ? filled(path, op) : path + (q ? `?${q}` : "")}"`;
    if (authOf(op) === "API key") line += demo ? ' \\\n  -H "X-API-Key: demo"' : ' \\\n  -H "X-API-Key: $PROVENANCE_API_KEY"';
    if (authOf(op) === "Admin token") line += ' \\\n  -H "X-Admin-Token: $ADMIN_TOKEN"';
    if (op.requestBody) line += ' \\\n  -H "Content-Type: application/json" -d \'{…}\'';
    return line;
  };
  const operation = (method, path, op) => {
    const d = el("details", "ref-op");
    d.id = op.operationId;
    d.dataset.search = `${method} ${path} ${op.summary || ""} ${op.description || ""}`.toLowerCase();
    const s = el("summary");
    const pathEl = el("span", "ref-path");
    path.split("/").forEach((part, i) => { if (i) { pathEl.append("/"); pathEl.append(el("wbr")); } pathEl.append(part); });
    s.append(el("span", `method ${method}`, method.toUpperCase()), pathEl, el("span", "ref-auth", authOf(op)), el("span", "ref-sum", op.summary || ""));
    d.append(s);
    const body = el("div", "ref-detail");
    if (op.description) op.description.split(/\n\n+/).forEach((para) => body.append(rich("p", para.trim())));
    const params = op.parameters || [];
    if (params.length) {
      body.append(el("h3", null, "Parameters"));
      body.append(table(["Name", "In", "Type", "Notes"], params.map((p) => {
        const n = el("span");
        n.append(el("code", null, p.name));
        if (p.required) n.append(el("span", "req", "required"));
        const notes = [p.description || resolve(p.schema).description, limits(p.schema)].filter(Boolean).join(". ");
        return [n, p.in, typeOf(p.schema), rich("span", notes)];
      })));
    }
    const rb = op.requestBody?.content?.["application/json"]?.schema;
    if (rb) {
      body.append(el("h3", null, "Request body (JSON)"));
      const rows = fieldRows(rb);
      if (rows.length) body.append(table(["Field", "Type", "Notes"], rows));
    }
    const responses = Object.entries(op.responses || {});
    if (responses.length) {
      body.append(el("h3", null, "Responses"));
      body.append(table(["Status", "Meaning"], responses.map(([code, r]) => [code, r.description || ""])));
      const ok = op.responses["200"] || op.responses["201"];
      const schema = ok?.content?.["application/json"]?.schema;
      const rows = schema ? fieldRows(schema) : [];
      if (rows.length) {
        body.append(el("h3", null, "Response fields"));
        body.append(table(["Field", "Type", "Notes"], rows));
      }
    }
    // beside the reference: the request, and a response (live with the demo key where it can run)
    const side = el("div", "ref-side");
    const canRun = runnable(method, path, op);
    side.append(el("h3", null, "Request"));
    const code = el("div", "code");
    const pre = el("pre");
    pre.append(el("code", null, curl(method, path, op, canRun)));
    code.append(pre);
    side.append(code);
    side.append(el("h3", null, canRun ? "Response" : "Response shape"));
    const out = el("div", "code ref-out");
    const outPre = el("pre");
    const okSchema = (op.responses?.["200"] || op.responses?.["201"])?.content?.["application/json"]?.schema;
    outPre.append(el("code", null, okSchema ? JSON.stringify(sampleOf(okSchema), null, 2) : "(no JSON body)"));
    out.append(outPre);
    side.append(out);
    const actions = el("p", "ref-actions");
    if (canRun) {
      const run = el("button", "btn small", "Run it with the demo key");
      run.type = "button";
      run.addEventListener("click", () => {
        run.disabled = true; run.textContent = "Running…";
        fetch(filled(path, op), { headers: { Accept: "application/json", "X-API-Key": "demo" } })
          .then((r) => r.text().then((txt) => ({ r, txt })))
          .then(({ r, txt }) => {
            let shown = txt; try { shown = JSON.stringify(JSON.parse(txt), null, 2); } catch (e) {}
            const lines = shown.split("\n");
            outPre.replaceChildren(el("code", null, (lines.length > 80 ? lines.slice(0, 80).join("\n") + "\n…" : shown)));
            side.querySelectorAll("h3")[1].textContent = `Response, ${r.status}, live`;
          })
          .catch(() => { outPre.replaceChildren(el("code", null, "The request did not reach the API.")); })
          .then(() => { run.disabled = false; run.textContent = "Run it again"; });
      });
      actions.append(run);
    }
    if (method === "get" && authOf(op) !== "Admin token") {
      const a = el("a", "btn small", "Open in the Playground");
      a.href = "/playground/" + (PLAY[path] ? `#${PLAY[path]}` : "");
      actions.append(a);
    }
    if (actions.childNodes.length) side.append(actions);
    const two = el("div", "ref-two");
    body.classList.add("ref-main");
    two.append(body, side);
    d.append(two);
    return d;
  };
  const render = () => {
    const root = document.getElementById("ref-body");
    const toc = document.getElementById("ref-toc");
    document.getElementById("ref-version").textContent = ` This is version ${spec.info.version} (OpenAPI ${spec.openapi}).`;
    const byTag = new Map();
    Object.entries(spec.paths).forEach(([path, methods]) => {
      Object.entries(methods).forEach(([method, op]) => {
        const tag = (op.tags || ["other"])[0];
        if (!byTag.has(tag)) byTag.set(tag, []);
        byTag.get(tag).push([method, path, op]);
      });
    });
    const known = GROUPS.map((g) => g[0]);
    const groups = [...GROUPS, ...[...byTag.keys()].filter((t) => !known.includes(t)).map((t) => [t, t, ""])];
    root.replaceChildren();
    groups.forEach(([tag, title, blurb]) => {
      const ops = byTag.get(tag);
      if (!ops) return;
      const sec = el("section", "ref-group");
      sec.id = `group-${tag}`;
      sec.append(el("h2", null, title));
      if (blurb) sec.append(el("p", null, blurb));
      ops.forEach(([m, p, op]) => sec.append(operation(m, p, op)));
      root.append(sec);
      const li = el("li");
      const a = el("a", null, `${title} (${ops.length})`);
      a.href = `#${sec.id}`;
      li.append(a);
      toc.append(li);
    });
    if (location.hash) {
      const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
      if (target?.tagName === "DETAILS") target.open = true;
      target?.scrollIntoView();
    }
  };
  document.getElementById("ref-filter").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    document.querySelectorAll(".ref-group").forEach((g) => {
      let shown = 0;
      g.querySelectorAll(".ref-op").forEach((op) => {
        const hit = !q || op.dataset.search.includes(q);
        op.hidden = !hit;
        shown += hit;
      });
      g.hidden = shown === 0;
    });
  });
  fetch("/openapi.json")
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then((s) => { spec = s; render(); })
    .catch(() => {
      document.getElementById("ref-state").textContent = "The endpoint list could not be loaded. The same information is in /openapi.json and /llms.txt.";
    });
})();
