// The most disliked clubs: a scatter that switches kind, click-for-detail,
// and a map of where each club is the intruder on another club's doorstep.
// Expects window.HATRED_DATA = {
//   kinds: [{key, label}], defaultKind, clubs: [{id, name, tier, success,
//   envied, resented, mocked, despised, titles, topFour, topFlight,
//   lastTitle, since, nearMisses, wagePct, neighbours, people, events}],
//   plot: {w, h, padL, padR, padT, padB}, map: {points: [[lat, lon, pop,
//   intruder, share]], legend: [{club_id, name, people}]}
// }
(function () {
  var data = window.HATRED_DATA;
  if (!data) return;
  var NS = "http://www.w3.org/2000/svg";
  var svg = document.getElementById("hatred-scatter");
  var detail = document.getElementById("hatred-detail");
  var P = data.plot;
  var kind = data.defaultKind;

  function el(name, attrs, text) {
    var n = document.createElementNS(NS, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text) n.textContent = text;
    return n;
  }
  function fmt(v) { return Math.round(v * 10) / 10; }

  function draw() {
    if (!svg) return;
    Array.prototype.slice.call(svg.querySelectorAll(".hatred-dot, .hatred-label")).forEach(function (n) { n.remove(); });
    var xs = data.clubs.map(function (c) { return c.success; });
    var ys = data.clubs.map(function (c) { return c[kind]; });
    var xMax = Math.max.apply(null, xs.concat([1])), yMax = Math.max.apply(null, ys.concat([1]));
    var plotW = P.w - P.padL - P.padR, plotH = P.h - P.padT - P.padB;
    var label = document.getElementById("hatred-y-label");
    if (label) label.textContent = (data.kinds.filter(function (k) { return k.key === kind; })[0] || {}).label + " →";
    var ranked = data.clubs.slice().sort(function (a, b) { return b[kind] - a[kind]; }).slice(0, 3);
    data.clubs.forEach(function (c) {
      var cx = P.padL + (c.success / xMax) * plotW;
      var cy = P.h - P.padB - (c[kind] / yMax) * plotH;
      var dot = el("circle", {cx: cx, cy: cy, r: 5, fill: "#2a78d6", stroke: "#fcfcfb", "stroke-width": 1.5,
                              "class": "hatred-dot", "data-club": c.id, tabindex: 0, role: "button"});
      dot.appendChild(el("title", {}, c.name + " — " + kind + " " + fmt(c[kind]) + ", success " + fmt(c.success)));
      dot.addEventListener("click", function () { show(c); });
      dot.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); show(c); } });
      svg.appendChild(dot);
      if (ranked.indexOf(c) >= 0) {
        svg.appendChild(el("text", {x: cx + 8, y: cy + 4, "font-size": 11, "font-weight": 600, fill: "#17202a", "class": "hatred-label"}, c.name));
      }
    });
  }

  function show(c) {
    if (!detail) return;
    var lines = [];
    lines.push("<b>" + c.name + "</b> — envied " + fmt(c.envied) + " · resented " + fmt(c.resented) +
               " · mocked " + fmt(c.mocked) + " · despised " + fmt(c.despised));
    lines.push(c.titles + " title" + (c.titles === 1 ? "" : "s") + ", " + c.topFour + " top-four finish" + (c.topFour === 1 ? "" : "es") +
               ", " + c.topFlight + " top-flight season" + (c.topFlight === 1 ? "" : "s") + ".");
    if (c.lastTitle) lines.push("Last title " + (c.lastTitle - 1) + "/" + String(c.lastTitle % 100).padStart(2, "0") +
                                ": " + c.since + " top-flight seasons since, " + c.nearMisses + " of them top four.");
    else if (c.topFlight) lines.push("No title on record: " + c.since + " top-flight seasons, " + c.nearMisses + " of them top four.");
    if (c.wagePct != null) lines.push("Wage bill in the " + Math.round(c.wagePct * 100) + "th percentile of its division.");
    lines.push("Exposure: " + c.neighbours + " clubs within fifteen miles, " + c.people.toLocaleString() + " people in reach.");
    (c.events || []).forEach(function (e) { lines.push("<i>" + e.kind + ", " + e.year + "</i> (weight " + e.weight + "): " + e.what); });
    detail.innerHTML = lines.map(function (l) { return "<p>" + l + "</p>"; }).join("");
    detail.hidden = false;
  }

  Array.prototype.forEach.call(document.querySelectorAll(".hatred-kind-chips .chip"), function (btn) {
    btn.addEventListener("click", function () {
      kind = btn.getAttribute("data-kind");
      Array.prototype.forEach.call(document.querySelectorAll(".hatred-kind-chips .chip"), function (b) {
        var on = b === btn; b.classList.toggle("chip-active", on); b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      draw();
    });
  });
  draw();

  // The map: one intruder at a time, in one colour, so a reader is never
  // asked to tell eight hues apart.
  var holder = document.getElementById("hatred-map");
  if (!holder || !window.L || !data.map || !data.map.points.length) return;
  var map = L.map(holder, {scrollWheelZoom: false}).setView([52.8, -1.5], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 12, attribution: "&copy; OpenStreetMap contributors"
  }).addTo(map);
  var layer = L.layerGroup().addTo(map);
  function showIntruder(idx) {
    layer.clearLayers();
    var pts = data.map.points.filter(function (p) { return p[3] === idx; });
    pts.forEach(function (p) {
      L.circleMarker([p[0], p[1]], {radius: 3 + 5 * p[4], color: "#fcfcfb", weight: 1, fillColor: "#2a78d6", fillOpacity: 0.85})
        .bindTooltip(Math.round(p[4] * 100) + "% of " + p[2].toLocaleString() + " people").addTo(layer);
    });
    if (pts.length) map.fitBounds(L.latLngBounds(pts.map(function (p) { return [p[0], p[1]]; })).pad(0.3));
  }
  Array.prototype.forEach.call(document.querySelectorAll(".hatred-map-chips .chip"), function (btn) {
    btn.addEventListener("click", function () {
      Array.prototype.forEach.call(document.querySelectorAll(".hatred-map-chips .chip"), function (b) {
        var on = b === btn; b.classList.toggle("chip-active", on); b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      showIntruder(Number(btn.getAttribute("data-intruder")));
    });
  });
  showIntruder(0);
})();
