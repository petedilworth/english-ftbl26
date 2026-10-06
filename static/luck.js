// Luck: the points-against-expected-points scatter, and the measure tabs
// for the season tables. Everything else on the page is server-rendered.
// Expects window.LUCK_DATA = {clubs: [{id, name}], root,
//   rows: [[season, tier, clubIdx, played, pts, xOdds|null, xShots|null]]}
// View state lives in the hash: #s=2025&t=1&m=o
(function () {
  "use strict";
  var data = window.LUCK_DATA;
  var svg = document.getElementById("luck-scatter");
  var NS = "http://www.w3.org/2000/svg";
  var W = 760, H = 520, L = 52, R = 16, T = 16, B = 44;
  var ORANGE = "#eb6834", BLUE = "#2a78d6", INK = "#17202a", MUTED = "#6b7683", GRID = "#e4e8ec";
  var hs = window.hashState;

  // The season tables: odds or shots.
  Array.prototype.forEach.call(document.querySelectorAll(".luck-tabs .chip"), function (btn) {
    btn.addEventListener("click", function () {
      var tab = btn.getAttribute("data-tab");
      Array.prototype.forEach.call(document.querySelectorAll(".luck-tabs .chip"), function (b) {
        var on = b === btn; b.classList.toggle("chip-active", on); b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      Array.prototype.forEach.call(document.querySelectorAll(".luck-tab"), function (el) {
        if (el.getAttribute("data-tab") === tab) el.removeAttribute("hidden"); else el.setAttribute("hidden", "");
      });
    });
  });

  if (!svg || !data) return;
  var seasonSel = document.getElementById("luck-season");
  var tip = document.getElementById("luck-tip");
  var note = document.getElementById("luck-note");
  var state = {
    s: Number((hs && hs.get("s")) || seasonSel.value),
    t: Number((hs && hs.get("t")) || 1),
    m: (hs && hs.get("m")) || "o"
  };
  if (!/^[osb]$/.test(state.m)) state.m = "o";
  if (seasonSel.querySelector('option[value="' + state.s + '"]')) seasonSel.value = String(state.s);
  else state.s = Number(seasonSel.value);

  function season(y) { return (y - 1) + "/" + String(y % 100).padStart(2, "0"); }
  function fmt(v) { return v === null ? "–" : v.toFixed(1); }
  function signed(v) { return (v > 0 ? "+" : "") + v.toFixed(1); }
  function el(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(e);
    return e;
  }
  function text(x, y, str, attrs, parent) {
    var t = el("text", Object.assign({x: x, y: y, "font-size": 11, fill: MUTED}, attrs || {}), parent);
    t.textContent = str;
    return t;
  }

  function pick(group, attr, value) {
    Array.prototype.forEach.call(document.querySelectorAll(".luck-controls [" + attr + "]"), function (b) {
      var on = b.getAttribute(attr) === String(value);
      b.classList.toggle("chip-active", on); b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function draw() {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    pick("tier", "data-tier", state.t);
    pick("measure", "data-measure", state.m);
    if (hs) { hs.set("s", state.s); hs.set("t", state.t); hs.set("m", state.m); }

    var rows = data.rows.filter(function (r) { return r[0] === state.s && r[1] === state.t; });
    var col = state.m === "s" ? 6 : 5;
    var usable = rows.filter(function (r) {
      return state.m === "b" ? (r[5] !== null && r[6] !== null) : r[col] !== null;
    });
    if (!usable.length) {
      text(W / 2, H / 2, rows.length ? "No " + (state.m === "o" ? "odds" : "shots on target") + " for this division in " + season(state.s) + "."
        : "No matches with data for tier " + state.t + " in " + season(state.s) + ".",
        {"text-anchor": "middle", "font-size": 14});
      return;
    }
    var xs = [], ys = [];
    usable.forEach(function (r) {
      ys.push(r[4]);
      if (state.m !== "s") xs.push(r[5]);
      if (state.m !== "o") xs.push(r[6]);
    });
    var lo = Math.floor(Math.min.apply(null, xs.concat(ys)) / 5) * 5;
    var hi = Math.ceil(Math.max.apply(null, xs.concat(ys)) / 5) * 5;
    if (hi - lo < 10) hi = lo + 10;
    function sx(v) { return L + (v - lo) / (hi - lo) * (W - L - R); }
    function sy(v) { return H - B - (v - lo) / (hi - lo) * (H - T - B); }

    var step = hi - lo > 60 ? 10 : 5;
    for (var v = lo; v <= hi; v += step) {
      el("line", {x1: sx(v), y1: T, x2: sx(v), y2: H - B, stroke: GRID}, svg);
      el("line", {x1: L, y1: sy(v), x2: W - R, y2: sy(v), stroke: GRID}, svg);
      text(sx(v), H - B + 16, String(v), {"text-anchor": "middle"}, svg);
      text(L - 6, sy(v) + 4, String(v), {"text-anchor": "end"}, svg);
    }
    el("line", {x1: sx(lo), y1: sy(lo), x2: sx(hi), y2: sy(hi), stroke: INK, "stroke-width": 1.2, "stroke-dasharray": "5 4"}, svg);
    text(sx(hi) - 4, sy(hi) + 28, "as expected", {"text-anchor": "end", fill: INK}, svg);
    text((L + W - R) / 2, H - 8, state.m === "b" ? "Expected points (filled: odds, ring: shots)" : "Expected points, from the " + (state.m === "o" ? "odds" : "shots on target"),
      {"text-anchor": "middle", fill: INK}, svg);
    var yl = text(14, (T + H - B) / 2, "Points", {"text-anchor": "middle", fill: INK, transform: "rotate(-90 14 " + ((T + H - B) / 2) + ")"}, svg);
    yl.setAttribute("font-size", 11);

    var maxLuck = 1;
    usable.forEach(function (r) { maxLuck = Math.max(maxLuck, Math.abs(r[4] - r[state.m === "s" ? 6 : 5])); });
    var ranked = usable.slice().sort(function (a, b) {
      var c = state.m === "s" ? 6 : 5;
      return (b[4] - b[c]) - (a[4] - a[c]);
    });
    var label = {};
    ranked.slice(0, 3).concat(ranked.slice(-3)).forEach(function (r) { label[r[2]] = true; });

    usable.forEach(function (r) {
      var club = data.clubs[r[2]];
      var g = el("a", {href: data.root + "/team/" + club.id + "/index.html", "class": "luck-dot"}, svg);
      var y = sy(r[4]);
      if (state.m === "b") {
        el("line", {x1: sx(r[5]), y1: y, x2: sx(r[6]), y2: y, stroke: MUTED, "stroke-width": 1.5, "stroke-opacity": 0.6}, g);
        el("circle", {cx: sx(r[5]), cy: y, r: 5, fill: BLUE}, g);
        el("circle", {cx: sx(r[6]), cy: y, r: 5, fill: "#fcfcfb", stroke: ORANGE, "stroke-width": 2}, g);
      } else {
        var luck = r[4] - r[col];
        el("circle", {cx: sx(r[col]), cy: y, r: 6, fill: luck >= 0 ? ORANGE : BLUE,
          "fill-opacity": 0.35 + 0.6 * Math.min(1, Math.abs(luck) / maxLuck), stroke: "#fcfcfb", "stroke-width": 1}, g);
      }
      if (label[r[2]]) {
        var x = state.m === "b" ? Math.max(sx(r[5]), sx(r[6])) : sx(r[col]);
        var left = state.m === "b" ? Math.min(sx(r[5]), sx(r[6])) : x;
        // Near the right edge the name goes on the left of the dot.
        if (x > W - 140) text(left - 8, y + 4, club.name, {fill: INK, "font-size": 11, "text-anchor": "end"}, g);
        else text(x + 8, y + 4, club.name, {fill: INK, "font-size": 11}, g);
      }
      g.addEventListener("mouseenter", function () { show(r, club); });
      g.addEventListener("focus", function () { show(r, club); });
      g.addEventListener("mouseleave", hide);
      g.addEventListener("blur", hide);
    });
    if (note) note.textContent = state.m === "b"
      ? "Filled dot: expected points from the odds. Ring: from the shots on target. A long line is a season the two read differently."
      : "Orange: luckier than expected. Blue: unluckier. The further from the line, the stronger the colour.";
  }

  function show(r, club) {
    var lines = ["<b>" + club.name + "</b>", season(r[0]) + ", tier " + r[1] + ", " + r[3] + " played",
      "Points " + r[4]];
    if (r[5] !== null) lines.push("Expected (odds) " + fmt(r[5]) + " · luck " + signed(r[4] - r[5]));
    if (r[6] !== null) lines.push("Expected (shots) " + fmt(r[6]) + " · luck " + signed(r[4] - r[6]));
    tip.innerHTML = lines.join("<br>");
    tip.removeAttribute("hidden");
  }
  function hide() { tip.setAttribute("hidden", ""); }

  svg.addEventListener("mousemove", function (evt) {
    var box = svg.parentNode.getBoundingClientRect();
    var x = evt.clientX - box.left + 12, y = evt.clientY - box.top + 12;
    if (x > box.width - 220) x -= 240;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  });

  seasonSel.addEventListener("change", function () { state.s = Number(seasonSel.value); draw(); });
  Array.prototype.forEach.call(document.querySelectorAll(".luck-controls [data-tier]"), function (b) {
    b.addEventListener("click", function () { state.t = Number(b.getAttribute("data-tier")); draw(); });
  });
  Array.prototype.forEach.call(document.querySelectorAll(".luck-controls [data-measure]"), function (b) {
    b.addEventListener("click", function () { state.m = b.getAttribute("data-measure"); draw(); });
  });
  draw();
})();
