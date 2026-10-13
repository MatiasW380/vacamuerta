/* Argentina Invest Monitor — gráficos compartidos (SVG a mano, sin dependencias).
   Uso: const C = AIMCharts(() => lang, () => T[lang]);  C.lineChart(host, rows, key, color, unit, digits, height) */
window.AIMCharts = function (getLang, getT) {
  const locale = () => (getLang() === "es" ? "es-AR" : "en-US");
  const fmt = (n, d = 0) => n == null ? "–" : new Intl.NumberFormat(locale(), { minimumFractionDigits: d, maximumFractionDigits: d }).format(n);
  // Variaciones interanuales extremas: casi siempre parten de una base chica; se marcan con una nota.
  const OUTLIER = 200;
  const pct = n => n == null ? "–" : (n > 0 ? "+" : n < 0 ? "−" : "") + fmt(Math.abs(n), 1) + "%";
  const monthName = (p, long = true) => {
    const [y, m] = p.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, 15)).toLocaleDateString(locale(), { month: long ? "long" : "short", year: "numeric", timeZone: "UTC" });
  };
  const axisLabel = v => v >= 1000 ? fmt(v / 1000, v % 1000 ? 1 : 0) + "k" : fmt(v, v % 1 ? 1 : 0);
  const periodLabel = p => p.length === 4 ? p : p.length === 10
    ? new Date(p + "T12:00:00Z").toLocaleDateString(locale(), { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
    : monthName(p);
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const svgEl = (tag, attrs = {}) => { const e = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };

  function niceTicks(max, n = 4) {
    const raw = max / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map(s => s * mag).find(s => s >= raw);
    const out = []; for (let v = 0; v <= max + step * 0.001; v += step) out.push(v);
    if (out[out.length - 1] < max) out.push(out[out.length - 1] + step);
    return out;
  }

  // Year labels on a time axis: only at January (or the first point), at least 46px apart.
  function yearTicks(svg, periods, x, yPos) {
    let lastX = -Infinity;
    if (periods[0] && periods[0].length === 10) {   // daily dates: a tick at each new month
      periods.forEach((p, i) => {
        if (i && p.slice(0, 7) === periods[i - 1].slice(0, 7)) return;
        const px = x(i);
        if (px - lastX < 54 || (i === 0 && periods.length > 40)) { if (i === 0) lastX = px - 30; return; }
        const [y, m] = p.split("-").map(Number);
        const lab = svgEl("text", { x: px, y: yPos, "text-anchor": "middle" });
        lab.textContent = new Date(Date.UTC(y, m - 1, 15)).toLocaleDateString(locale(), { month: "short", year: m === 1 ? "numeric" : undefined, timeZone: "UTC" });
        svg.append(lab); lastX = px;
      });
      return;
    }
    periods.forEach((p, i) => {
      if (!(p.endsWith("-01") || i === 0)) return;
      const px = x(i), nextJan = periods.findIndex((q, j) => j > i && q.endsWith("-01"));
      if (i === 0 && !p.endsWith("-01") && nextJan > 0 && x(nextJan) - px < 46) return;
      if (px - lastX < 46) return;
      const lab = svgEl("text", { x: px, y: yPos, "text-anchor": i === 0 ? "start" : "middle" });
      lab.textContent = p.slice(0, 4); svg.append(lab); lastX = px;
    });
  }

  // Line chart with crosshair tooltip.
  function lineChart(host, rows, key, color, unit, digits, height) {
    host.innerHTML = "";
    const W = host.clientWidth || 800, H = height, m = { t: 8, r: 12, b: 28, l: 56 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const ticks = niceTicks(Math.max(...rows.map(r => r[key])));
    const yMax = ticks[ticks.length - 1];
    const x = i => m.l + (rows.length === 1 ? iw / 2 : (i / (rows.length - 1)) * iw);
    const y = v => m.t + ih - (v / yMax) * ih;
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": host.dataset.label || "" });

    for (const t of ticks) {
      svg.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), stroke: "var(--grid)", "stroke-width": t === 0 ? 1.25 : 1 }));
      const lab = svgEl("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end" });
      lab.textContent = axisLabel(t);
      svg.append(lab);
    }
    yearTicks(svg, rows.map(r => r.period), x, H - 8);

    const d = rows.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(r[key]).toFixed(1)}`).join("");
    svg.append(svgEl("path", { d: d + `L${x(rows.length - 1)},${y(0)}L${x(0)},${y(0)}Z`, fill: color, "fill-opacity": 0.08 }));
    svg.append(svgEl("path", { d, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const last = rows.length - 1;
    svg.append(svgEl("circle", { cx: x(last), cy: y(rows[last][key]), r: 4.5, fill: color, stroke: "var(--bg)", "stroke-width": 2 }));

    const hair = svgEl("line", { y1: m.t, y2: m.t + ih, stroke: "var(--ink-3)", "stroke-width": 1, opacity: 0 });
    const dot = svgEl("circle", { r: 4.5, fill: color, stroke: "var(--bg)", "stroke-width": 2, opacity: 0 });
    svg.append(hair, dot);
    const hit = svgEl("rect", { x: m.l, y: 0, width: iw, height: H, fill: "transparent", tabindex: 0 });
    svg.append(hit);
    host.append(svg);

    const tip = document.createElement("div"); tip.className = "tip"; host.append(tip);
    let cur = last;
    const show = i => {
      cur = Math.max(0, Math.min(last, i));
      const r = rows[cur], px = x(cur), py = y(r[key]);
      hair.setAttribute("x1", px); hair.setAttribute("x2", px); hair.setAttribute("opacity", 0.6);
      dot.setAttribute("cx", px); dot.setAttribute("cy", py); dot.setAttribute("opacity", 1);
      tip.innerHTML = "";
      const v = document.createElement("strong"); v.textContent = `${fmt(r[key], digits)} ${unit}`;
      const k = document.createElement("span"); k.className = "key"; k.style.background = color;
      const p = document.createElement("div"); p.textContent = periodLabel(r.period);
      tip.append(k, v, p);
      const scale = host.clientWidth / W;
      const left = px * scale, tw = tip.offsetWidth;
      tip.style.left = Math.min(Math.max(0, left - tw / 2), host.clientWidth - tw) + "px";
      tip.style.top = Math.max(0, py * scale - tip.offsetHeight - 14) + "px";
      tip.style.opacity = 1;
    };
    const hide = () => { hair.setAttribute("opacity", 0); dot.setAttribute("opacity", 0); tip.style.opacity = 0; };
    hit.addEventListener("pointermove", e => {
      const b = svg.getBoundingClientRect(), sx = (e.clientX - b.left) * (W / b.width);
      show(Math.round(((sx - m.l) / iw) * last));
    });
    hit.addEventListener("pointerleave", hide);
    hit.addEventListener("focus", () => show(cur));
    hit.addEventListener("blur", hide);
    hit.addEventListener("keydown", e => {
      if (e.key === "ArrowLeft") { show(cur - 1); e.preventDefault(); }
      if (e.key === "ArrowRight") { show(cur + 1); e.preventDefault(); }
    });
  }

  // Horizontal bars with per-bar tooltip and direct value labels.
  // Monthly columns (new wells) with per-bar tooltip.
  function columnChart(host, rows, key, unit, label) {
    host.innerHTML = "";
    const W = host.clientWidth || 500, H = 260, m = { t: 8, r: 8, b: 28, l: 40 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const ticks = niceTicks(Math.max(1, ...rows.map(r => r[key])));
    const yMax = ticks[ticks.length - 1];
    const step = iw / rows.length, bw = Math.max(2, step - 2);
    const y = v => m.t + ih - (v / yMax) * ih;
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label || "" });
    for (const t of ticks) {
      svg.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), stroke: "var(--grid)" }));
      const lab = svgEl("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end" }); lab.textContent = fmt(t); svg.append(lab);
    }
    const tip = document.createElement("div"); tip.className = "tip";
    rows.forEach((r, i) => {
      const x0 = m.l + i * step + 1, v = r[key], top = y(v), h = y(0) - top;
      if (r.period.endsWith("-01") || (r.period.length === 4 && (rows.length - 1 - i) % Math.ceil(30 / step) === 0)) {
        const lab = svgEl("text", { x: x0, y: H - 8 }); lab.textContent = r.period.slice(0, 4); svg.append(lab);
      }
      const g = svgEl("g", { tabindex: 0 });
      const rad = Math.min(3, bw / 2, h);
      g.append(svgEl("rect", { x: x0 - 1, y: m.t, width: step, height: ih, fill: "transparent" }));
      if (h > 0) g.append(svgEl("path", { d: `M${x0},${y(0)}V${top + rad}a${rad},${rad} 0 0 1 ${rad},${-rad}h${bw - 2 * rad}a${rad},${rad} 0 0 1 ${rad},${rad}V${y(0)}z`, fill: "var(--oil)" }));
      const show = () => {
        tip.innerHTML = "";
        const s1 = document.createElement("strong"); s1.textContent = `${fmt(v)} ${unit}`;
        const d = document.createElement("div"); d.textContent = r.label || periodLabel(r.period);
        tip.append(s1, d);
        const sc = host.clientWidth / W;
        tip.style.left = Math.min(Math.max(0, x0 * sc - tip.offsetWidth / 2), host.clientWidth - tip.offsetWidth) + "px";
        tip.style.top = Math.max(0, top * sc - tip.offsetHeight - 10) + "px";
        tip.style.opacity = 1;
      };
      const hide = () => { tip.style.opacity = 0; };
      g.addEventListener("pointerenter", show); g.addEventListener("pointerleave", hide);
      g.addEventListener("focus", show); g.addEventListener("blur", hide);
      svg.append(g);
    });
    host.append(svg, tip);
  }

  // Columnas por encima y por debajo de cero (superávit / déficit).
  function divergingColumns(host, labels, vals, unit, label) {
    host.innerHTML = "";
    const W = host.clientWidth || 700, H = 280, m = { t: 14, r: 8, b: 28, l: 52 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const hi = Math.max(0, ...vals), lo = Math.min(0, ...vals);
    const tk = niceTicks(Math.max(hi, -lo)), top = tk[tk.length - 1];
    const ymax = hi > 0 ? top : 0, ymin = lo < 0 ? -top : 0;
    const y = v => m.t + (ymax - v) / (ymax - ymin) * ih;
    const step = iw / labels.length, bw = Math.max(3, Math.min(34, step * 0.7));
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label || "" });
    const ticks = [...tk.filter(v => v <= ymax), ...tk.filter(v => v > 0 && -v >= ymin).map(v => -v)];
    for (const v of ticks) {
      svg.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: v === 0 ? "var(--ink-3)" : "var(--grid)" }));
      const lab = svgEl("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" }); lab.textContent = (v < 0 ? "−" : "") + axisLabel(Math.abs(v)); svg.append(lab);
    }
    const tip = document.createElement("div"); tip.className = "tip";
    const every = Math.ceil(36 / step);
    labels.forEach((lb, i) => {
      const v = vals[i], cx = m.l + i * step + step / 2;
      const g = svgEl("g", { tabindex: 0 });
      g.append(svgEl("rect", { x: m.l + i * step, y: m.t, width: step, height: ih, fill: "transparent" }));
      g.append(svgEl("rect", { x: cx - bw / 2, y: Math.min(y(v), y(0)), width: bw, height: Math.max(1, Math.abs(y(v) - y(0))), rx: 1.5, fill: v >= 0 ? "var(--up)" : "var(--down)" }));
      if ((labels.length - 1 - i) % every === 0) { const xl = svgEl("text", { x: cx, y: H - 8, "text-anchor": "middle" }); xl.textContent = step < 30 ? "’" + lb.slice(2) : lb; svg.append(xl); }
      const show = () => {
        tip.innerHTML = "";
        const s1 = document.createElement("strong"); s1.textContent = `${v < 0 ? "−" : "+"}${fmt(Math.abs(v))} ${unit}`;
        const d = document.createElement("div"); d.textContent = lb; tip.append(s1, d);
        const sc = host.clientWidth / W;
        tip.style.left = Math.min(Math.max(0, cx * sc - tip.offsetWidth / 2), host.clientWidth - tip.offsetWidth) + "px";
        tip.style.top = Math.max(0, Math.min(y(v), y(0)) * sc - tip.offsetHeight - 10) + "px";
        tip.style.opacity = 1;
      };
      const hide = () => { tip.style.opacity = 0; };
      g.addEventListener("pointerenter", show); g.addEventListener("pointerleave", hide);
      g.addEventListener("focus", show); g.addEventListener("blur", hide);
      svg.append(g);
    });
    host.append(svg, tip);
  }

  // Yearly stacked columns with a tooltip listing every segment.
  function stackedColumns(host, labels, series, unit, label) {
    host.innerHTML = "";
    const W = host.clientWidth || 600, H = 260, m = { t: 18, r: 8, b: 28, l: 48 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const tots = labels.map((_, i) => series.reduce((a, s) => a + s.values[i], 0));
    const ticks = niceTicks(Math.max(1, ...tots)), yMax = ticks[ticks.length - 1];
    const step = iw / labels.length, bw = Math.min(56, step * 0.68);
    const y = v => m.t + ih - (v / yMax) * ih;
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label || "" });
    for (const tk of ticks) {
      svg.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(tk), y2: y(tk), stroke: "var(--grid)" }));
      const lab = svgEl("text", { x: m.l - 8, y: y(tk) + 4, "text-anchor": "end" }); lab.textContent = axisLabel(tk, ticks); svg.append(lab);
    }
    const tip = document.createElement("div"); tip.className = "tip";
    labels.forEach((lb, i) => {
      const cx = m.l + i * step + step / 2, x0 = cx - bw / 2;
      const g = svgEl("g", { tabindex: 0 });
      g.append(svgEl("rect", { x: m.l + i * step, y: m.t, width: step, height: ih, fill: "transparent" }));
      let acc = 0;
      series.forEach(s => {
        const v = s.values[i]; if (!v) return;
        const top = y(acc + v), bot = y(acc);
        g.append(svgEl("rect", { x: x0, y: top + 0.5, width: bw, height: Math.max(0, bot - top - 1), fill: s.color }));
        acc += v;
      });
      const every = Math.ceil(34 / step);
      if ((labels.length - 1 - i) % every === 0) { const xl = svgEl("text", { x: cx, y: H - 8, "text-anchor": "middle" }); xl.textContent = step < 34 && lb.length === 4 ? "’" + lb.slice(2) : lb; svg.append(xl); }
      if (tots[i] && step >= 38) { const tl = svgEl("text", { x: cx, y: y(tots[i]) - 5, "text-anchor": "middle", style: "fill:var(--ink-2);font-size:11px" }); tl.textContent = fmt(tots[i]); g.append(tl); }
      const show = () => {
        tip.innerHTML = "";
        const h = document.createElement("strong"); h.textContent = `${lb}: ${fmt(tots[i])} ${unit}`; tip.append(h);
        series.forEach(s => { if (s.values[i]) { const d = document.createElement("div"); d.textContent = `${s.name}: ${fmt(s.values[i])}`; tip.append(d); } });
        const sc = host.clientWidth / W;
        tip.style.left = Math.min(Math.max(0, cx * sc - tip.offsetWidth / 2), host.clientWidth - tip.offsetWidth) + "px";
        tip.style.top = Math.max(0, y(tots[i]) * sc - tip.offsetHeight - 12) + "px";
        tip.style.opacity = 1;
      };
      const hide = () => { tip.style.opacity = 0; };
      g.addEventListener("pointerenter", show); g.addEventListener("pointerleave", hide);
      g.addEventListener("focus", show); g.addEventListener("blur", hide);
      svg.append(g);
    });
    host.append(svg, tip);
  }

  // Several series on one axis, crosshair tooltip listing all of them, end labels.
  function multiLine(host, periods, names, series, colors) {
    host.innerHTML = "";
    const W = host.clientWidth || 900, H = window.innerWidth > 700 ? 340 : 280;
    const m = { t: 10, r: window.innerWidth > 700 ? 150 : 12, b: 28, l: 56 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const ticks = niceTicks(Math.max(...names.flatMap(n => series[n])));
    const yMax = ticks[ticks.length - 1], last = periods.length - 1;
    const x = i => m.l + (i / last) * iw, y = v => m.t + ih - (v / yMax) * ih;
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": (getT().histTitle || "") });
    for (const t of ticks) {
      svg.append(svgEl("line", { x1: m.l, x2: m.l + iw, y1: y(t), y2: y(t), stroke: "var(--grid)" }));
      const lab = svgEl("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end" });
      lab.textContent = axisLabel(t); svg.append(lab);
    }
    yearTicks(svg, periods, x, H - 8);
    // End labels, nudged apart so they never overlap.
    const ends = names.map((n, k) => ({ n, k, y: y(series[n][last]) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 15) ends[i].y = ends[i - 1].y + 15;
    names.forEach((n, k) => {
      const d = series[n].map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
      svg.append(svgEl("path", { d, fill: "none", stroke: colors[k], "stroke-width": 2, "stroke-linejoin": "round" }));
      svg.append(svgEl("circle", { cx: x(last), cy: y(series[n][last]), r: 4, fill: colors[k], stroke: "var(--bg)", "stroke-width": 2 }));
    });
    if (m.r > 100) ends.forEach(e => {
      const lab = svgEl("text", { x: x(last) + 10, y: e.y + 4, style: "fill:var(--ink-2);font-size:13px" });
      lab.textContent = e.n; svg.append(lab);
    });
    const hair = svgEl("line", { y1: m.t, y2: m.t + ih, stroke: "var(--ink-3)", opacity: 0 });
    svg.append(hair);
    const hit = svgEl("rect", { x: m.l, y: 0, width: iw, height: H, fill: "transparent", tabindex: 0 });
    svg.append(hit); host.append(svg);
    const tip = document.createElement("div"); tip.className = "tip"; host.append(tip);
    let cur = last;
    const show = i => {
      cur = Math.max(0, Math.min(last, i));
      hair.setAttribute("x1", x(cur)); hair.setAttribute("x2", x(cur)); hair.setAttribute("opacity", 0.6);
      tip.innerHTML = "";
      const head = document.createElement("div"); head.textContent = monthName(periods[cur]); head.style.marginBottom = "4px"; tip.append(head);
      names.map((n, k) => ({ n, k, v: series[n][cur] })).sort((a, b) => b.v - a.v).forEach(r => {
        const row = document.createElement("div");
        const key = document.createElement("span"); key.className = "key"; key.style.background = colors[r.k];
        const v = document.createElement("strong"); v.textContent = fmt(r.v) + " ";
        row.append(key, v, document.createTextNode(r.n)); tip.append(row);
      });
      const sc = host.clientWidth / W, left = x(cur) * sc;
      tip.style.left = (left + tip.offsetWidth + 16 > host.clientWidth ? left - tip.offsetWidth - 12 : left + 12) + "px";
      tip.style.top = "8px"; tip.style.opacity = 1;
    };
    const hide = () => { hair.setAttribute("opacity", 0); tip.style.opacity = 0; };
    hit.addEventListener("pointermove", e => { const b = svg.getBoundingClientRect(); show(Math.round((((e.clientX - b.left) * (W / b.width)) - m.l) / iw * last)); });
    hit.addEventListener("pointerleave", hide);
    hit.addEventListener("focus", () => show(cur)); hit.addEventListener("blur", hide);
    hit.addEventListener("keydown", e => { if (e.key === "ArrowLeft") { show(cur - 1); e.preventDefault(); } if (e.key === "ArrowRight") { show(cur + 1); e.preventDefault(); } });
  }

  // Listed operators: our production data + TradingView quotes widget.
  const LISTED = [
    { name: "YPF", tickers: "NYSE: YPF, BYMA: YPFD", tv: [["YPF", "NYSE:YPF|12M"], ["YPFD", "BCBA:YPFD|12M"]] },
    { name: "Vista", tickers: "NYSE: VIST, BMV: VISTA", tv: [["VIST", "NYSE:VIST|12M"]] },
    { name: "Pampa Energía", tickers: "NYSE: PAM, BYMA: PAMP", tv: [["PAM", "NYSE:PAM|12M"], ["PAMP", "BCBA:PAMP|12M"]] },
  ];
  let quotesKey = "";

  // Barras horizontales genéricas: rows = [{name, v, sub?}], valor con unidad y tooltip.
  function hbar(host, rows, opts = {}) {
    host.innerHTML = "";
    const W = host.clientWidth || 500, row = opts.row || 30, m = { t: 4, r: 70, b: 4, l: opts.labelWidth || 150 };
    const H = m.t + m.b + rows.length * row, iw = W - m.l - m.r;
    const max = Math.max(...rows.map(o => o.v), 1);
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "" });
    const tip = document.createElement("div"); tip.className = "tip";
    rows.forEach((o, i) => {
      const yy = m.t + i * row, w = Math.max(2, (o.v / max) * iw);
      const g = svgEl("g", { tabindex: 0 });
      const name = svgEl("text", { x: m.l - 10, y: yy + row / 2 + 4, "text-anchor": "end", style: "fill:var(--ink-2);font-size:13px" });
      name.textContent = o.name.length > 24 ? o.name.slice(0, 23) + "…" : o.name;
      const r = Math.min(4, w / 2);
      const bar = svgEl("path", { d: `M${m.l},${yy + 6}h${w - r}a${r},${r} 0 0 1 ${r},${r}v${row - 12 - 2 * r}a${r},${r} 0 0 1 ${-r},${r}h${-(w - r)}z`, fill: o.color || opts.color || "var(--brand)", "fill-opacity": o.muted ? 0.45 : 1 });
      const val = svgEl("text", { x: m.l + w + 8, y: yy + row / 2 + 4, style: "fill:var(--ink-2);font-size:12px" });
      val.textContent = opts.valueLabel ? opts.valueLabel(o) : fmt(o.v, opts.digits || 0);
      g.append(svgEl("rect", { x: 0, y: yy, width: W, height: row, fill: "transparent" }), name, bar, val);
      const show = () => {
        tip.innerHTML = "";
        const v = document.createElement("strong"); v.textContent = `${fmt(o.v, opts.digits || 0)} ${opts.unit || ""}`;
        const n = document.createElement("div"); n.textContent = o.name; tip.append(v, n);
        if (o.sub) { const s = document.createElement("div"); s.textContent = o.sub; tip.append(s); }
        const sc = host.clientWidth / W;
        tip.style.left = Math.min((m.l + w) * sc - 20, host.clientWidth - tip.offsetWidth) + "px";
        tip.style.top = (yy * sc - tip.offsetHeight + 4) + "px";
        tip.style.opacity = 1;
      };
      const hide = () => { tip.style.opacity = 0; };
      g.addEventListener("pointerenter", show); g.addEventListener("pointerleave", hide);
      g.addEventListener("focus", show); g.addEventListener("blur", hide);
      svg.append(g);
    });
    host.append(svg, tip);
  }

  return { locale, fmt, pct, monthName, axisLabel, periodLabel, esc, svgEl, niceTicks, yearTicks, lineChart, columnChart, divergingColumns, stackedColumns, multiLine, hbar };
};
