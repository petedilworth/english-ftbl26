// The most disliked clubs: an overall index with a weight per kind, a
// ranked stacked bar per club, click-for-detail, and a map of where each
// club is the intruder on another club's doorstep.
// Expects window.HATRED_DATA = {
//   kinds: [{key, label, color}], shown, clubs: [{id, name, tier, success,
//   envied, resented, mocked, despised, titles, topFour, topFlight,
//   lastTitle, since, nearMisses, wagePct, neighbours, people, events}],
//   map: {points: [[lat, lon, pop, intruder, share]], legend: [{club_id, name, people}]}
// }
// The weights live in the fragment as #w=50,50,50,50 (in kind order), so a
// weighting can be bookmarked; hash-state.js is used when present.
(function () {
  var data = window.HATRED_DATA;
  if (!data) return;
  var detail = document.getElementById("hatred-detail");
  var list = document.getElementById("index-bars");
  var more = document.querySelector(".index-more");
  var sliders = Array.prototype.slice.call(document.querySelectorAll(".index-weights input[type=range]"));
  var kinds = data.kinds.map(function (k) { return k.key; });
  var showAll = false;

  function fmt(v) { return Math.round(v * 10) / 10; }

  // Each kind over its leader, as in hatred.normalised().
  var tops = {};
  kinds.forEach(function (k) {
    tops[k] = Math.max.apply(null, data.clubs.map(function (c) { return c[k]; }).concat([0]));
  });
  var norm = {};
  data.clubs.forEach(function (c) {
    norm[c.id] = {};
    kinds.forEach(function (k) { norm[c.id][k] = tops[k] ? c[k] / tops[k] : 0; });
  });
  var byId = {};
  data.clubs.forEach(function (c) { byId[c.id] = c; });

  function weights() {
    var w = {};
    sliders.forEach(function (s) { w[s.getAttribute("data-kind")] = Number(s.value); });
    return w;
  }
  function score(w) {
    var total = kinds.reduce(function (t, k) { return t + (w[k] || 0); }, 0);
    return data.clubs.map(function (c) {
      var parts = {};
      kinds.forEach(function (k) { parts[k] = total ? 100 * (w[k] || 0) * norm[c.id][k] / total : 0; });
      var idx = kinds.reduce(function (t, k) { return t + parts[k]; }, 0);
      return {club: c, parts: parts, index: idx};
    }).sort(function (a, b) { return b.index - a.index || a.club.name.localeCompare(b.club.name); });
  }
  var equal = {};
  kinds.forEach(function (k) { equal[k] = 1; });
  var equalRank = {};
  score(equal).forEach(function (r, i) { equalRank[r.club.id] = i + 1; });

  function draw() {
    if (!list) return;
    var w = weights();
    var total = kinds.reduce(function (t, k) { return t + w[k]; }, 0);
    Array.prototype.forEach.call(document.querySelectorAll(".index-weight-share"), function (o) {
      o.textContent = total ? Math.round(100 * w[o.getAttribute("data-kind")] / total) + "%" : "0%";
    });
    var ranked = score(w);
    var top = ranked.length && ranked[0].index > 0 ? ranked[0].index : 1;
    var items = {};
    Array.prototype.forEach.call(list.children, function (li) { items[li.getAttribute("data-club")] = li; });
    ranked.forEach(function (r, i) {
      var li = items[r.club.id];
      if (!li) return;
      li.querySelector(".index-rank").textContent = i + 1;
      var track = li.querySelector(".index-track");
      track.innerHTML = "";
      data.kinds.forEach(function (k) {
        if (r.parts[k.key] <= 0) return;
        var seg = document.createElement("span");
        seg.className = "index-seg";
        seg.style.width = (100 * r.parts[k.key] / top) + "%";
        seg.style.background = k.color;
        seg.title = k.label + ": " + norm[r.club.id][k.key].toFixed(2) + " of the leader, " +
                    fmt(r.parts[k.key]) + " points at this weight";
        track.appendChild(seg);
      });
      li.querySelector(".index-value").firstChild.nodeValue = Math.round(r.index);
      var move = equalRank[r.club.id] - (i + 1);
      var mv = li.querySelector(".index-move");
      mv.textContent = move > 0 ? " ▲" + move : move < 0 ? " ▼" + (-move) : "";
      mv.title = move ? "Rank " + equalRank[r.club.id] + " at equal weights" : "";
      li.hidden = !showAll && i >= data.shown;
      list.appendChild(li);  // re-appending moves it into rank order
    });
    if (window.hashState) {
      var isEqual = kinds.every(function (k) { return w[k] === w[kinds[0]]; }) && w[kinds[0]] > 0;
      window.hashState.set("w", isEqual ? null : kinds.map(function (k) { return w[k]; }).join(","));
    }
  }

  function show(c) {
    if (!detail) return;
    var n = norm[c.id];
    var lines = [];
    lines.push("<b>" + c.name + "</b> – envied " + fmt(c.envied) + " (" + n.envied.toFixed(2) + " of the leader) · resented " +
               fmt(c.resented) + " (" + n.resented.toFixed(2) + ") · mocked " + fmt(c.mocked) + " (" + n.mocked.toFixed(2) +
               ") · despised " + fmt(c.despised) + " (" + n.despised.toFixed(2) + ")");
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

  if (list) {
    list.addEventListener("click", function (e) {
      var li = e.target.closest(".index-bar");
      if (li && byId[li.getAttribute("data-club")]) show(byId[li.getAttribute("data-club")]);
    });
    list.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      var li = e.target.closest(".index-bar");
      if (li && byId[li.getAttribute("data-club")]) { e.preventDefault(); show(byId[li.getAttribute("data-club")]); }
    });
  }
  sliders.forEach(function (s) { s.addEventListener("input", draw); });
  var reset = document.querySelector(".index-reset");
  if (reset) reset.addEventListener("click", function () {
    sliders.forEach(function (s) { s.value = 50; });
    draw();
  });
  if (more) more.addEventListener("click", function () {
    showAll = !showAll;
    more.textContent = showAll ? "Show the top " + data.shown : "Show all " + data.clubs.length;
    more.setAttribute("aria-expanded", showAll ? "true" : "false");
    draw();
  });

  // A bookmarked weighting, if the fragment carries one.
  var saved = window.hashState ? window.hashState.get("w") : null;
  if (saved) {
    var vals = saved.split(",").map(Number);
    if (vals.length === sliders.length && vals.every(function (v) { return v >= 0 && v <= 100; })) {
      sliders.forEach(function (s, i) { s.value = vals[i]; });
    }
  }
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
