// Renders the searchable plugin card grid on the home page.
(() => {
  const PAGE = 60;
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

  async function init(root) {
    const base = new URL(root.dataset.src, location.href);
    const data = await (await fetch(base)).json();
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
    const more = el("button", { class: "md-button", type: "button" }, "Show more");

    for (const input of [search, role, scope, sort]) input.value = params.get(input.name) ?? input.value;
    hide.checked = params.get("hide") === "1";

    let shown = PAGE;
    let matches = [];

    const draw = () => {
      grid.replaceChildren(...matches.slice(0, shown).map(card));
      more.hidden = shown >= matches.length;
    };

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
      shown = PAGE;
      draw();

      const state = new URLSearchParams();
      for (const input of [search, role, scope]) if (input.value) state.set(input.name, input.value);
      if (sort.value !== "downloads") state.set("sort", sort.value);
      if (hide.checked) state.set("hide", "1");
      history.replaceState(null, "", state.size ? `?${state}` : location.pathname);
    };

    let timer;
    search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(update, 120); });
    for (const input of [role, scope, sort, hide]) input.addEventListener("change", update);
    more.addEventListener("click", () => { shown += PAGE; draw(); });

    root.replaceChildren(
      el("div", { class: "catalog-controls" }, search, role, scope, sort,
        el("label", { class: "catalog-toggle" }, hide, " Hide deprecated & stale")),
      count, grid, el("div", { class: "catalog-more" }, more));
    update();
  }

  // Material's instant navigation swaps pages without reloading scripts.
  document$.subscribe(() => {
    const root = document.getElementById("catalog");
    if (root) init(root);
  });
})();
