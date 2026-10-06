// Deprivation around the ground: one weight per measure drives three views
// at once - the neighbourhood map, the club ranking, and a club's shape.
// Every measure arrives as a 0-100 percentile of England (src/deprivation.py),
// so an index is just a weighted mean, and a club's index is the same
// weighting of its own nine percentiles.
// Expects window.DEPRIVATION_DATA = {
//   domains: [{key, label, weight, desc}], ramp: [13 hexes],
//   points: [[lat, lon, p0..p8]], names, las, authorities,
//   clubs: [{id, name, tier, lat, lon, people, d: [9], b10}]
// }
// The fragment keeps the view: #w=22.5,22.5,...&club=hartlepool-united-fc&solo=3
(function () {
  "use strict";
  var data = window.DEPRIVATION_DATA;
  if (!data) return;
  var hs = window.hashState;
  var D = data.domains, N = D.length;
  var sliders = [], shares = [], solos = [];
  Array.prototype.forEach.call(document.querySelectorAll(".dep-weights input[type=range]"), function (s) { sliders[+s.getAttribute("data-domain")] = s; });
  Array.prototype.forEach.call(document.querySelectorAll(".dep-weights output"), function (o) { shares[+o.getAttribute("data-domain")] = o; });
  Array.prototype.forEach.call(document.querySelectorAll(".dep-solo"), function (b) { solos[+b.getAttribute("data-domain")] = b; });
  var bars = document.getElementById("dep-bars");
  var more = document.querySelector(".dep-more");
  var shape = document.getElementById("dep-shape");
  var nowNote = document.getElementById("dep-now");
  var solo = null, saved = null, order = "most", showAll = false, current = null;
  var SHOW = 15;
  var byId = {};
  data.clubs.forEach(function (c) { byId[c.id] = c; });
  // Ten colours from the thirteen-step ramp, light to dark.
  var COLOURS = [];
  for (var k = 0; k < 10; k++) COLOURS.push(data.ramp[Math.round(k * (data.ramp.length - 1) / 9)]);

  function weights() { return sliders.map(function (s) { return Number(s.value); }); }
  function score(p, w, offset) {
    var t = 0, s = 0;
    for (var i = 0; i < N; i++) { s += w[i] * p[i + offset]; t += w[i]; }
    return t ? s / t : 50;
  }
  function isOfficial(w) { return w.every(function (x, i) { return Math.abs(x - D[i].weight) < 0.01; }); }

  // ── The map ──────────────────────────────────────────────────────────
  var holder = document.getElementById("dep-map");
  var map = null, dots = [], marks = [], values = [], edges = [];
  if (holder && window.L) {
    map = L.map(holder, {scrollWheelZoom: false, preferCanvas: true}).setView([52.6, -1.6], 6);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 13, attribution: "&copy; OpenStreetMap contributors"}).addTo(map);
    var canvas = L.canvas({padding: 0.3});
    data.points.forEach(function (p, j) {
      var m = L.circleMarker([p[0], p[1]], {renderer: canvas, radius: 3.2, stroke: false, fillOpacity: 0.85});
      m.bindTooltip(function () {
        var la = data.authorities[data.las[j]] || "", nm = data.names[j];
        var full = /^\d+$/.test(nm) ? la + " " + nm : nm + (la ? ", " + la : "");
        var w = weights(), worst = -1, wi = 0;
        for (var i = 0; i < N; i++) if (w[i] > 0 && p[i + 2] > worst) { worst = p[i + 2]; wi = i; }
        return "<b>" + full + "</b><br>" + Math.round(values[j]) + " at these weights (50 is England's average)" +
          (worst >= 0 ? "<br>Worst of the measures in use: " + D[wi].label + ", " + worst : "");
      }, {sticky: true});
      m.addTo(map);
      dots.push(m);
    });
    data.clubs.forEach(function (c) {
      // Small, so the neighbourhood colours stay readable around them.
      var m = L.circleMarker([c.lat, c.lon], {radius: 2 + (7 - c.tier) * 0.4, color: "#17202a", weight: 1, fillColor: "#fcfcfb", fillOpacity: 0.8});
      m.bindTooltip(c.name + " (tier " + c.tier + ")");
      m.on("click", function () { pick(c.id, false); });
      m.addTo(map);
      marks.push(m);
    });
  }
  function paintMap(w) {
    if (!map) return;
    values = data.points.map(function (p) { return score(p, w, 2); });
    var sorted = values.slice().sort(function (a, b) { return a - b; });
    edges = [];
    for (var q = 1; q < 10; q++) edges.push(sorted[Math.floor(q * sorted.length / 10)]);
    values.forEach(function (v, j) {
      var b = 0;
      while (b < 9 && v >= edges[b]) b++;
      dots[j].setStyle({fillColor: COLOURS[b]});
    });
  }

  // ── The ranking ──────────────────────────────────────────────────────
  function tiersOn() {
    var on = {};
    Array.prototype.forEach.call(document.querySelectorAll(".dep-tiers .chip"), function (b) {
      if (b.classList.contains("chip-active")) on[b.getAttribute("data-tier")] = true;
    });
    return on;
  }
  function rank(w) {
    var on = tiersOn();
    var list = data.clubs.filter(function (c) { return on[String(c.tier)]; })
      .map(function (c) { return {c: c, v: score(c.d, w, 0)}; });
    list.sort(function (a, b) { return order === "most" ? b.v - a.v : a.v - b.v; });
    while (bars.firstChild) bars.removeChild(bars.firstChild);
    list.slice(0, showAll ? list.length : SHOW).forEach(function (r, i) {
      var li = document.createElement("li");
      li.className = "index-bar dep-bar" + (current === r.c.id ? " is-current" : "");
      li.tabIndex = 0;
      li.innerHTML = '<span class="index-rank">' + (i + 1) + '</span><span class="index-name">' + r.c.name +
        '<span class="index-tier">' + r.c.tier + '</span></span><span class="index-track"><span class="dep-fill" style="width:' +
        r.v.toFixed(1) + '%"></span><span class="index-tick" style="left:50%"></span></span><span class="index-value">' + r.v.toFixed(0) + "</span>";
      li.addEventListener("click", function () { pick(r.c.id, true); });
      li.addEventListener("keydown", function (e) { if (e.key === "Enter") pick(r.c.id, true); });
      bars.appendChild(li);
    });
    if (more) more.textContent = showAll ? "Show the top " + SHOW : "Show all " + list.length;
  }

  // ── A club's shape ───────────────────────────────────────────────────
  function drawShape(w) {
    if (!shape) return;
    var c = current && byId[current];
    if (!c) { shape.innerHTML = '<p class="finance-note">Pick a club from the ranking, the map or the quick picks.</p>'; return; }
    var total = score(c.d, w, 0);
    var html = '<p class="dep-shape-head"><b><a href="../../team/' + c.id + '/index.html">' + c.name + "</a></b> – tier " + c.tier +
      ". At these weights <b>" + total.toFixed(0) + "</b>. " + Math.round(c.b10 * 100) + "% of the " + c.people.toLocaleString("en-GB") +
      " people it draws live in England's most deprived tenth. <a href='../../compare/index.html#a=" + c.id + "'>Compare</a></p>";
    html += '<div class="dep-shape-rows">';
    D.forEach(function (d, i) {
      var v = c.d[i], off = w[i] === 0;
      var left = Math.min(v, 50), width = Math.abs(v - 50);
      html += '<div class="dep-shape-row' + (off ? " is-off" : "") + (solo === i ? " is-solo" : "") + '" title="' + d.desc + '">' +
        '<span class="dep-shape-label">' + d.label + '</span><span class="dep-shape-track"><span class="dep-shape-bar ' +
        (v >= 50 ? "worse" : "better") + '" style="left:' + left.toFixed(1) + "%;width:" + width.toFixed(1) +
        '%"></span><span class="dep-shape-mid"></span></span><span class="dep-shape-value">' + v.toFixed(0) + "</span></div>";
    });
    html += '</div><p class="finance-note">Bars run from England\'s average (the line at 50): right and orange is more deprived than average, left and blue less. Faded rows have no weight at the moment.</p>';
    shape.innerHTML = html;
  }
  function pick(id, fly) {
    current = id;
    if (hs) hs.set("club", id);
    var w = weights();
    drawShape(w);
    rank(w);
    var c = byId[id];
    if (fly && map && c) map.setView([c.lat, c.lon], 10);
  }

  // ── Wiring ───────────────────────────────────────────────────────────
  var pending = false;
  function update() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () {
      pending = false;
      var w = weights(), t = w.reduce(function (a, b) { return a + b; }, 0);
      w.forEach(function (x, i) { if (shares[i]) shares[i].textContent = t ? Math.round(100 * x / t) + "%" : "–"; });
      solos.forEach(function (b, i) { b.setAttribute("aria-pressed", solo === i ? "true" : "false"); b.classList.toggle("chip-active", solo === i); });
      if (nowNote) {
        if (solo !== null) nowNote.textContent = "Showing " + D[solo].label.toLowerCase() + " alone: " + D[solo].desc.toLowerCase() + ". Press Solo again to go back.";
        else if (isOfficial(w)) nowNote.textContent = "Showing the official mix: income and employment count most, then education and health, then crime, housing and surroundings. Child and pensioner poverty start at zero.";
        else if (!t) nowNote.textContent = "Every weight is at zero: everything reads as England's average.";
        else {
          var top = w.map(function (x, i) { return [x, i]; }).filter(function (a) { return a[0] > 0; })
            .sort(function (a, b) { return b[0] - a[0]; }).slice(0, 3).map(function (a) { return D[a[1]].label.toLowerCase() + " " + Math.round(100 * a[0] / t) + "%"; });
          nowNote.textContent = "Your mix: " + top.join(", ") + (w.filter(function (x) { return x > 0; }).length > 3 ? " and the rest." : ".");
        }
      }
      paintMap(w);
      rank(w);
      drawShape(w);
      if (hs) {
        hs.set("w", isOfficial(w) ? null : w.join(","));
        hs.set("solo", solo === null ? null : solo);
      }
    });
  }
  function setWeights(w) { sliders.forEach(function (s, i) { s.value = w[i]; }); }

  sliders.forEach(function (s) {
    s.addEventListener("input", function () { solo = null; saved = null; update(); });
  });
  solos.forEach(function (b, i) {
    b.addEventListener("click", function () {
      if (solo === i) { solo = null; setWeights(saved || D.map(function (d) { return d.weight; })); saved = null; }
      else { if (solo === null) saved = weights(); solo = i; setWeights(D.map(function (_, k) { return k === i ? 50 : 0; })); }
      update();
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll(".dep-presets .chip"), function (b) {
    b.addEventListener("click", function () {
      solo = null; saved = null;
      var p = b.getAttribute("data-preset");
      setWeights(D.map(function (d) { return p === "official" ? d.weight : (d.weight > 0 ? 10 : 0); }));
      update();
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll(".dep-order .chip"), function (b) {
    b.addEventListener("click", function () {
      order = b.getAttribute("data-order");
      Array.prototype.forEach.call(document.querySelectorAll(".dep-order .chip"), function (x) {
        var on = x === b; x.classList.toggle("chip-active", on); x.setAttribute("aria-pressed", on ? "true" : "false");
      });
      rank(weights());
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll(".dep-tiers .chip"), function (b) {
    b.addEventListener("click", function () {
      var on = !b.classList.contains("chip-active");
      b.classList.toggle("chip-active", on); b.setAttribute("aria-pressed", on ? "true" : "false");
      rank(weights());
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll(".dep-featured .chip"), function (b) {
    b.addEventListener("click", function () { pick(b.getAttribute("data-club"), true); });
  });
  if (more) more.addEventListener("click", function () {
    showAll = !showAll; more.setAttribute("aria-expanded", showAll ? "true" : "false"); rank(weights());
  });

  // Restore a shared view, then draw.
  if (hs) {
    var w = hs.get("w");
    if (w) {
      var parts = w.split(",").map(Number);
      if (parts.length === N && parts.every(function (x) { return isFinite(x) && x >= 0 && x <= 50; })) setWeights(parts);
    }
    var s = hs.get("solo");
    if (s !== null && /^\d+$/.test(s) && +s < N) { solo = +s; saved = D.map(function (d) { return d.weight; }); setWeights(D.map(function (_, k) { return k === solo ? 50 : 0; })); }
    var c = hs.get("club");
    if (c && byId[c]) current = c;
  }
  if (!current) {
    var first = document.querySelector(".dep-featured .chip");
    if (first) current = first.getAttribute("data-club");
  }
  update();
})();
