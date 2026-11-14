/* Developer pages (GH #20): code tabs, copy buttons, this host in the samples, the "on this page"
   highlight and the live plan limits. */
(() => {
  const base = location.origin;
  const fmt = (n) => (n == null ? "custom" : Number(n).toLocaleString("en-US"));

  // Samples say {{BASE}} in the markup; show this deployment's address instead.
  document.querySelectorAll(".code pre code").forEach((code) => {
    if (code.textContent.includes("{{BASE}}")) code.innerHTML = code.innerHTML.replaceAll("{{BASE}}", base);
  });

  // Tabs: one block, several languages. Arrow keys move between tabs.
  document.querySelectorAll("[data-tabs]").forEach((block, b) => {
    const tabs = [...block.querySelectorAll('[role="tab"]')];
    const panes = [...block.querySelectorAll('[role="tabpanel"]')];
    const pick = (i, focus) => {
      tabs.forEach((t, j) => { t.setAttribute("aria-selected", String(i === j)); t.tabIndex = i === j ? 0 : -1; });
      panes.forEach((p, j) => { p.hidden = i !== j; });
      if (focus) tabs[i].focus();
    };
    tabs.forEach((t, i) => {
      t.id = `tab-${b}-${i}`;
      panes[i].id = `pane-${b}-${i}`;
      t.setAttribute("aria-controls", panes[i].id);
      panes[i].setAttribute("aria-labelledby", t.id);
      panes[i].tabIndex = 0;
      t.addEventListener("click", () => pick(i));
      t.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight") pick((i + 1) % tabs.length, true);
        if (e.key === "ArrowLeft") pick((i - 1 + tabs.length) % tabs.length, true);
      });
    });
    pick(0);
  });

  // Copy the visible sample.
  document.querySelectorAll(".code").forEach((block) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "copy";
    btn.textContent = "Copy";
    btn.addEventListener("click", async () => {
      const pre = [...block.querySelectorAll("pre")].find((p) => !p.hidden);
      try {
        await navigator.clipboard.writeText(pre.innerText.trim());
        btn.textContent = "Copied";
      } catch {
        btn.textContent = "Select and copy";
      }
      setTimeout(() => { btn.textContent = "Copy"; }, 1600);
    });
    block.append(btn);
  });

  // "On this page": mark the section being read.
  const links = new Map(
    [...document.querySelectorAll('.doc-toc a[href^="#"]')].map((a) => [a.getAttribute("href").slice(1), a]),
  );
  if (links.size && "IntersectionObserver" in window) {
    const seen = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        links.forEach((a) => a.removeAttribute("aria-current"));
        links.get(e.target.id)?.setAttribute("aria-current", "true");
      });
    }, { rootMargin: "-30% 0px -60% 0px" });
    links.forEach((_, id) => { const s = document.getElementById(id); if (s) seen.observe(s); });
  }

  // Plan limits, live from the public endpoint.
  const table = document.querySelector("#plans-table tbody");
  if (table) {
    fetch("/v1/public/plans").then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then((body) => {
      body.data.forEach((p) => {
        const tr = document.createElement("tr");
        [p.label, fmt(p.rate_limit_per_minute), fmt(p.monthly_request_quota), fmt(p.max_watches)].forEach((v) => {
          const td = document.createElement("td");
          td.textContent = v;
          tr.append(td);
        });
        table.append(tr);
      });
      document.getElementById("plans-note").textContent = `Export requests return up to ${fmt(body.max_export_rows)} rows. Prices are on the home page.`;
    }).catch(() => {
      document.getElementById("plans-note").textContent = "Plan limits could not be loaded just now; they are on the home page under Pricing.";
    });
  }
})();
