// Renders the searchable plugin card grid on the home page.
(() => {
  const PAGE = 60;
  // Start rendering the next page this many pixels before the user reaches the end.
  const MARGIN = 800;
  const SORTS = {
    downloads: (a, b) => b.dl - a.dl,
    updated: (a, b) => b.u.localeCompare(a.u),
    name: (a, b) => a.n.localeCompare(b.n),
  };

  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    node.append(...children.filter((c) => c != null));
    return node;
  };

  const select = (name, label, options) =>
    el("select", { name, "aria-label": label },
      ...options.map(([value, text]) => el("option", { value }, text)));

  const card = (p) =>
    el("a", { class: "catalog-card" + (p.dep || p.st ? " catalog-card--flagged" : ""), href: p.p },
      el("div", { class: "catalog-card__head" },
        el("span", { class: "catalog-card__name" }, p.n),
        el("span", { class: "catalog-card__version" }, p.v)),
      el("p", { class: "catalog-card__desc" }, p.d || "No description."),
      el("div", { class: "catalog-card__meta" },
        el("span", { class: "catalog-chip" }, p.rl),
        p.dep ? el("span", { class: "catalog-chip catalog-chip--danger" }, "deprecated") : null,
        !p.dep && p.st ? el("span", { class: "catalog-chip catalog-chip--warn" }, "stale") : null,
        el("span", { class: "catalog-card__stat", title: "Weekly downloads" }, `⬇ ${p.dl.toLocaleString()}`),
        el("span", { class: "catalog-card__stat", title: "Last release" }, p.u)));

  const spinner = () => el("div", { class: "catalog-spinner", role: "status", "aria-label": "Loading" });

  async function loadData(root) {
    root.replaceChildren(spinner());
    try {
      const resp = await fetch(new URL(root.dataset.src, location.href));
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return await resp.json();
    } catch (err) {
      console.error("catalog: failed to load data", err);
      const retry = el("button", { class: "md-button", type: "button", onclick: () => init(root) }, "Retry");
      root.replaceChildren(el("p", { class: "catalog-error" }, "Couldn't load the catalog."), retry);
      return null;
    }
  }

  async function init(root) {
    const data = await loadData(root);
    if (!data) return;
    const params = new URLSearchParams(location.search);

    const uniq = (key, label) =>
      [...new Map(data.map((p) => [p[key], p[label ?? key]])).entries()].sort((a, b) => a[1].localeCompare(b[1]));

    const search = el("input", { type: "search", name: "q", placeholder: `Search ${data.length} plugins…`, "aria-label": "Search" });
    const role = select("role", "Role", [["", "All roles"], ...uniq("r", "rl")]);
    const scope = select("scope", "Scope", [["", "All scopes"], ...uniq("s")]);
    const sort = select("sort", "Sort", [["downloads", "Most downloaded"], ["updated", "Recently updated"], ["name", "Name"]]);
    const hide = el("input", { type: "checkbox", name: "hide" });
    const count = el("p", { class: "catalog-count" });
    const grid = el("div", { class: "catalog-grid" });
    const loader = spinner();
    const more = el("button", { class: "md-button", type: "button" }, "Show more");
    const sentinel = el("div", { class: "catalog-sentinel", "aria-hidden": "true" });

    for (const input of [search, role, scope, sort]) input.value = params.get(input.name) ?? input.value;
    hide.checked = params.get("hide") === "1";

    let matches = [];
    let shown = 0;
    let loading = false;
    let failed = false;
    // Without IntersectionObserver, "Show more" is the only way to page.
    const auto = "IntersectionObserver" in window;

    const renderPage = () =>
      new Promise((resolve, reject) =>
        requestAnimationFrame(() => {
          try {
            grid.append(...matches.slice(shown, shown + PAGE).map(card));
            shown = Math.min(shown + PAGE, matches.length);
            resolve();
          } catch (err) {
            reject(err);
          }
        }));

    const nearBottom = () => sentinel.getBoundingClientRect().top < innerHeight + MARGIN;

    const refresh = () => {
      const done = shown >= matches.length;
      loader.hidden = !loading;
      more.hidden = done || loading || (auto && !failed);
      sentinel.hidden = done;
    };

    const loadMore = async () => {
      if (loading || shown >= matches.length) return;
      loading = true;
      refresh();
      try {
        await renderPage();
        failed = false;
      } catch (err) {
        console.error("catalog: failed to load next page", err);
        failed = true;
      }
      loading = false;
      refresh();
      // The observer only fires on changes, so keep going while the sentinel is still on screen.
      if (auto && !failed && nearBottom()) loadMore();
    };

    if (auto) {
      new IntersectionObserver(
        (entries) => { if (!failed && entries.some((e) => e.isIntersecting)) loadMore(); },
        { rootMargin: `0px 0px ${MARGIN}px 0px` },
      ).observe(sentinel);
    }
    more.addEventListener("click", () => { failed = false; loadMore(); });

    const update = () => {
      const terms = search.value.toLowerCase().split(/\s+/).filter(Boolean);
      matches = data
        .filter((p) => !role.value || p.r === role.value)
        .filter((p) => !scope.value || p.s === scope.value)
        .filter((p) => !hide.checked || !(p.dep || p.st))
        .filter((p) => {
          const hay = `${p.n} ${p.d} ${p.k.join(" ")}`.toLowerCase();
          return terms.every((t) => hay.includes(t));
        })
        // Flagged packages stay listed but sink to the bottom.
        .sort((a, b) => (a.dep || a.st) - (b.dep || b.st) || SORTS[sort.value](a, b));
      count.textContent = `${matches.length} plugin${matches.length === 1 ? "" : "s"}`;
      grid.replaceChildren();
      shown = 0;
      failed = false;
      loadMore();

      const state = new URLSearchParams();
      for (const input of [search, role, scope]) if (input.value) state.set(input.name, input.value);
      if (sort.value !== "downloads") state.set("sort", sort.value);
      if (hide.checked) state.set("hide", "1");
      history.replaceState(null, "", state.size ? `?${state}` : location.pathname);
    };

    let timer;
    search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(update, 120); });
    for (const input of [role, scope, sort, hide]) input.addEventListener("change", update);

    root.replaceChildren(
      el("div", { class: "catalog-controls" }, search, role, scope, sort,
        el("label", { class: "catalog-toggle" }, hide, " Hide deprecated & stale")),
      count, grid, sentinel, el("div", { class: "catalog-more" }, loader, more));
    update();
  }

  // Material's instant navigation swaps pages without reloading scripts.
  document$.subscribe(() => {
    const root = document.getElementById("catalog");
    if (root) init(root);
  });
})();
