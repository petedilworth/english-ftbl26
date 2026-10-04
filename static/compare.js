// Compare two clubs. The page ships an index of every club
// (compare-index.js); each club's figures live in club/<id>.js and are
// loaded only for the two chosen, and the head-to-head comes from club A's
// own team-page file. #a=<id>&b=<id> in the fragment names the pair, so a
// comparison is a link - the emails and the fixtures page use exactly that.
//
// Club A is always blue and club B orange (the first two slots of the
// site's checked palette), whatever their kits: two red clubs would
// otherwise be one colour. The kits appear as a stripe on each card.
(function () {
  "use strict";
  var IDX = window.COMPARE_INDEX;
  if (!IDX) return;
  window.COMPARE_CLUB = window.COMPARE_CLUB || {};
  var CA = "#2a78d6", CB = "#eb6834";
  var hs = window.hashState;
  var NS = "http://www.w3.org/2000/svg";
  var byId = {}, byName = {};
  IDX.clubs.forEach(function (c) { byId[c.id] = c; byName[c.name.toLowerCase()] = c.id; });
  var inA = document.getElementById("cmp-a"), inB = document.getElementById("cmp-b");
  var body = document.getElementById("cmp-body"), empty = document.getElementById("cmp-empty");
  var map = null, mapLayer = null, current = "";

  // ── helpers ──────────────────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }
  function n0(v) { return Math.round(v).toLocaleString("en-GB"); }
  function pct(v) { return Math.round(v * 100) + "%"; }
  function money(v) { return (v < 0 ? "−" : "") + "£" + (Math.abs(v) >= 1e6 ? (Math.abs(v) / 1e6).toFixed(1) + "m" : n0(Math.abs(v))); }
  function signed(v) { return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v); }
  function ordinal(n) { var s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
  function season(y) { return (y - 1) + "/" + String(y % 100).padStart(2, "0"); }
  function teamHref(id) { return "../team/" + id + "/index.html"; }
  function el(name, attrs, text) {
    var n = document.createElementNS(NS, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }
  var FMT = {
    catchment_now: n0, catchment_peak: n0, capacity: n0,
    income: function (v) { return "£" + n0(v); },
    doorstep: pct, win_rate: pct, wage_share: pct,
    margin: function (v) { return (v < 0 ? "−" : "") + Math.round(Math.abs(v) * 100) + "%"; },
    highest_tier: function (v) { return "Tier " + v; },
    goals_per_game: function (v) { return v.toFixed(2); },
    ppg_now: function (v) { return v.toFixed(2); },
    yo_yo: function (v) { return v.toFixed(2); },
    pyramid_now: function (v) { return ordinal(v); },
    form5: function (v) { return v + " pts"; },
    momentum: signed,
    turnover: money,
    value_index: function (v) { return Math.round(v); },
    hatred_index: function (v) { return Math.round(v); },
    ground_security: function (v) { return v.toFixed(2); }
  };
  function fmt(key, v) { return v == null ? "—" : (FMT[key] || n0)(v); }

  function load(src, check, cb) {
    if (check()) return cb(true);
    var s = document.createElement("script");
    s.src = src;
    s.onload = function () { cb(check()); };
    s.onerror = function () { cb(false); };
    document.head.appendChild(s);
  }
  function loadClub(id, cb) {
    load("club/" + id + ".js", function () { return !!window.COMPARE_CLUB[id]; },
         function () { cb(window.COMPARE_CLUB[id] || null); });
  }

  // ── picker ───────────────────────────────────────────────────────────
  function idFor(input) { return byName[(input.value || "").trim().toLowerCase()] || null; }
  function setPair(a, b) {
    if (hs) { hs.set("a", a); hs.set("b", b); }
    route();
  }
  [inA, inB].forEach(function (inp) {
    inp.addEventListener("change", function () {
      var a = idFor(inA), b = idFor(inB);
      if (a && b && a !== b) setPair(a, b);
    });
  });
  $("cmp-swap").addEventListener("click", function () {
    var a = idFor(inA), b = idFor(inB);
    if (a && b) setPair(b, a);
  });
  $("cmp-random").addEventListener("click", function () {
    var live = IDX.clubs.filter(function (c) { return c.live; });
    var a = live[Math.floor(Math.random() * live.length)];
    var same = live.filter(function (c) { return c.tier === a.tier && c.id !== a.id; });
    var b = same[Math.floor(Math.random() * same.length)];
    if (b) setPair(a.id, b.id);
  });
  $("cmp-derby").addEventListener("click", function () {
    var a = idFor(inA);
    if (!a) return;
    loadClub(a, function (d) { if (d && d.facts.rival_id) setPair(a, d.facts.rival_id); });
  });
  document.getElementById("cmp-picker").addEventListener("submit", function (e) { e.preventDefault(); });
  // The section links scroll without touching the fragment: it holds the pair.
  Array.prototype.forEach.call(document.querySelectorAll(".cmp-jump a"), function (a) {
    a.addEventListener("click", function (e) {
      var t = document.getElementById(a.getAttribute("href").slice(1));
      if (t) { e.preventDefault(); t.scrollIntoView({behavior: "smooth", block: "start"}); }
    });
  });
  $("cmp-copy").addEventListener("click", function () {
    var btn = this, done = function () { btn.textContent = "Link copied"; setTimeout(function () { btn.textContent = "Copy link"; }, 1500); };
    if (navigator.clipboard) navigator.clipboard.writeText(location.href).then(done, function () {});
  });

  // ── header cards ─────────────────────────────────────────────────────
  function card(d, side) {
    var f = d.facts, s = d.season;
    var where = d.live ? (d.division + (s && s.position ? " · " + ordinal(s.position) : ""))
                       : "Last played " + season(d.last);
    var kit = '<span class="cmp-kit" style="background: linear-gradient(90deg,' + (d.colors[0] || "#c8ced6") + ' 50%,' +
              (d.colors[1] || d.colors[0] || "#c8ced6") + ' 50%)"></span>';
    return '<div class="cmp-card cmp-card-' + side + '">' + kit +
      '<h3><a href="' + teamHref(d.id) + '">' + esc(d.name) + '</a></h3>' +
      '<p class="cmp-card-where">' + esc(where) + '</p>' +
      (f.nickname ? '<p>' + esc(f.nickname) + '</p>' : "") +
      '<p>' + esc(f.stadium || "") + (f.capacity ? " · " + n0(f.capacity) : "") + '</p>' +
      (f.founded ? '<p>Founded ' + f.founded + '</p>' : "") + '</div>';
  }
  function head(a, b, meetings) {
    var m = haversine(a.ground, b.ground);
    var mid = '<div class="cmp-vs"><span class="cmp-vs-v">v</span>' +
      (m != null ? '<span>' + (m < 10 ? m.toFixed(1) : Math.round(m)) + ' miles apart</span>' : "") +
      '<span id="cmp-met">' + (meetings == null ? "" : meetings) + '</span></div>';
    $("cmp-head").innerHTML = card(a, "a") + mid + card(b, "b");
    Array.prototype.forEach.call(document.querySelectorAll(".cmp-name-a"), function (n) { n.textContent = a.name; });
    Array.prototype.forEach.call(document.querySelectorAll(".cmp-name-b"), function (n) { n.textContent = b.name; });
  }
  function haversine(p, q) {
    if (!p || !q || p.lat == null || q.lat == null) return null;
    var r = Math.PI / 180, dp = (q.lat - p.lat) * r, dl = (q.lon - p.lon) * r;
    var x = Math.pow(Math.sin(dp / 2), 2) + Math.cos(p.lat * r) * Math.cos(q.lat * r) * Math.pow(Math.sin(dl / 2), 2);
    return 2 * 3958.8 * Math.asin(Math.sqrt(x));
  }

  // ── mirrored bars: the tale of the tape and its cousins ──────────────
  // rows: [{label, section, a: {v, text, size}, b: {...}, better}]
  function mirrored(target, rows) {
    var html = "", sec = null;
    rows.forEach(function (r) {
      if (r.section && r.section !== sec) { sec = r.section; html += '<div class="cmp-sec">' + esc(sec) + '</div>'; }
      var win = null;
      if (r.better && r.a.v != null && r.b.v != null && r.a.v !== r.b.v) {
        win = (r.better === "high") === (r.a.v > r.b.v) ? "a" : "b";
      }
      function side(x, s) {
        var w = x.size == null ? 0 : Math.max(0, Math.min(1, x.size)) * 100;
        var val = '<span class="cmp-val cmp-val-' + s + (win === s ? " is-win" : "") + '"' + (x.title ? ' title="' + esc(x.title) + '"' : "") + '>' + esc(x.text) + '</span>';
        var bar = '<span class="cmp-bar cmp-bar-' + s + '"><span style="width:' + w.toFixed(1) + '%"></span></span>';
        return s === "a" ? val + bar : bar + val;  // figures sit at the outside edges
      }
      html += '<div class="cmp-row">' + side(r.a, "a") +
              '<span class="cmp-label">' + esc(r.label) + (r.better ? "" : ' <span class="cmp-fact" title="A fact, not a contest">◇</span>') + '</span>' +
              side(r.b, "b") + '</div>';
    });
    target.innerHTML = html;
  }
  function tape(a, b) {
    mirrored($("cmp-tape"), IDX.tape.map(function (t) {
      var key = t[0];
      return {section: t[1], label: t[2], better: t[3],
              a: {v: a.stats[key], text: fmt(key, a.stats[key]), size: a.pct[key],
                  title: key === "ground_security" ? a.facts.ground_owner : null},
              b: {v: b.stats[key], text: fmt(key, b.stats[key]), size: b.pct[key],
                  title: key === "ground_security" ? b.facts.ground_owner : null}};
    }));
  }
  function hatred(a, b) {
    var kinds = [["envied", "Envied"], ["resented", "Resented"], ["mocked", "Mocked"], ["despised", "Despised"]];
    var ha = a.hatred || {}, hb = b.hatred || {};
    if (!a.hatred && !b.hatred) { $("cmp-hatred").innerHTML = '<p class="finance-note">Neither club is on the hatred page: it covers clubs with a top-flight season and a short curated list.</p>'; return; }
    mirrored($("cmp-hatred"), kinds.map(function (k) {
      return {label: k[1], better: null,
              a: {v: ha[k[0]], text: ha[k[0]] == null ? "—" : ha[k[0]].toFixed(2), size: ha[k[0]]},
              b: {v: hb[k[0]], text: hb[k[0]] == null ? "—" : hb[k[0]].toFixed(2), size: hb[k[0]]}};
    }));
  }
  function levers(a, b) {
    var la = a.levers || {}, lb = b.levers || {};
    if (!a.levers && !b.levers) { $("cmp-levers").innerHTML = '<p class="finance-note">The value page covers this season\'s tiers 1–7 only.</p>'; return; }
    var groupLabel = {};
    IDX.groups.forEach(function (g) { groupLabel[g.key] = g.label; });
    mirrored($("cmp-levers"), IDX.levers.map(function (lv) {
      var x = la[lv.key], y = lb[lv.key];
      return {section: groupLabel[lv.group], label: lv.label, better: "high",
              a: {v: x, text: x == null ? "—" : x.toFixed(2), size: x},
              b: {v: y, text: y == null ? "—" : y.toFixed(2), size: y}};
    }));
  }

  // ── form ─────────────────────────────────────────────────────────────
  function form(a, b) {
    function row(d, side) {
      if (!d.live || !d.form.length) return '<div class="cmp-form-row"><b class="cmp-form-name cmp-form-' + side + '">' + esc(d.name) + '</b><span class="finance-note">No league matches this season.</span></div>';
      var chips = d.form.slice().reverse().map(function (m) {
        var r = m[4] > m[5] ? "W" : m[4] === m[5] ? "D" : "L";
        return '<span class="cmp-chip cmp-chip-' + r + '" title="' + esc(m[0] + " · " + (m[3] === "H" ? "home to " : "away at ") + m[2] + " · " + m[4] + "–" + m[5]) + '">' + r + '</span>';
      }).join("");
      var s = d.season;
      var line = s ? ordinal(s.position) + " in " + d.division + " · P" + s.played + " · " + s.points + " pts · GD " + signed(s.gd) : "";
      return '<div class="cmp-form-row"><b class="cmp-form-name cmp-form-' + side + '">' + esc(d.name) + '</b>' +
             '<span class="cmp-chips" aria-label="Last ten league results, oldest first">' + chips + '</span>' +
             '<span class="cmp-form-line">' + esc(line) + '</span></div>';
    }
    $("cmp-form").innerHTML = row(a, "a") + row(b, "b") + '<p class="finance-note">Last ten league matches, oldest on the left. Hover a result for the match.</p>';
  }

  // ── head to head ─────────────────────────────────────────────────────
  function h2h(a, b, cb) {
    var box = $("cmp-h2h");
    try { delete window.H2H; } catch (e) { window.H2H = undefined; }
    load("../team/" + a.id + "/h2h-data.js", function () { return !!window.H2H; }, function (ok) {
      var opp = ok && window.H2H.opponents ? window.H2H.opponents[b.id] : null;
      var divs = ok ? window.H2H.divisions : [];
      if (!opp || !opp.matches.length) {
        box.innerHTML = '<p class="finance-note">No league meeting between ' + esc(a.name) + ' and ' + esc(b.name) + ' on record.</p>';
        cb([]); return;
      }
      var ms = opp.matches;  // [season, date, divIdx, H|A, gf, ga] from A's side, newest first
      var t = {w: 0, d: 0, l: 0, gf: 0, ga: 0, hw: 0, hd: 0, hl: 0, aw: 0, ad: 0, al: 0};
      var bestA = null, bestB = null;
      ms.forEach(function (m) {
        var r = m[4] > m[5] ? "w" : m[4] === m[5] ? "d" : "l";
        t[r]++; t.gf += m[4]; t.ga += m[5];
        t[(m[3] === "H" ? "h" : "a") + r]++;
        var margin = m[4] - m[5];
        if (margin > 0 && (!bestA || margin > bestA[4] - bestA[5])) bestA = m;
        if (margin < 0 && (!bestB || -margin > bestB[5] - bestB[4])) bestB = m;
      });
      var n = ms.length;
      function seg(k, c, label) { return t[k] ? '<span style="width:' + (100 * t[k] / n) + '%;background:' + c + '" title="' + label + ': ' + t[k] + '">' + t[k] + '</span>' : ""; }
      function score(m) { return m[3] === "H" ? a.name + " " + m[4] + "–" + m[5] + " " + b.name : b.name + " " + m[5] + "–" + m[4] + " " + a.name; }
      var last = ms.slice(0, 10).map(function (m) {
        return '<tr><td>' + m[1] + '</td><td>' + esc(divs[m[2]] || "") + '</td><td>' + esc(score(m)) + '</td></tr>';
      }).join("");
      box.innerHTML =
        '<div class="cmp-record"><span class="cmp-record-a">' + esc(a.name) + ' ' + t.w + '</span><span class="cmp-record-d">' + t.d + ' drawn</span><span class="cmp-record-b">' + t.l + ' ' + esc(b.name) + '</span></div>' +
        '<div class="cmp-recbar">' + seg("w", CA, a.name + " wins") + seg("d", "#9aa3ab", "Draws") + seg("l", CB, b.name + " wins") + '</div>' +
        '<div class="stat-cards">' +
          '<div class="stat-card"><div class="stat-value">' + n + '</div><div class="stat-label">League meetings</div></div>' +
          '<div class="stat-card"><div class="stat-value">' + t.gf + '–' + t.ga + '</div><div class="stat-label">Goals, ' + esc(a.name) + ' first</div></div>' +
          '<div class="stat-card"><div class="stat-value">' + t.hw + '–' + t.hd + '–' + t.hl + '</div><div class="stat-label">At ' + esc(a.name) + ' (W–D–L)</div></div>' +
          '<div class="stat-card"><div class="stat-value">' + t.al + '–' + t.ad + '–' + t.aw + '</div><div class="stat-label">At ' + esc(b.name) + ' (W–D–L for them)</div></div>' +
          '<div class="stat-card"><div class="stat-value">' + season(ms[n - 1][0]) + '</div><div class="stat-label">First meeting on record</div></div>' +
        '</div>' +
        '<p>' + (bestA ? 'Biggest ' + esc(a.name) + ' win: <b>' + esc(score(bestA)) + '</b>, ' + bestA[1] + '. ' : "") +
               (bestB ? 'Biggest ' + esc(b.name) + ' win: <b>' + esc(score(bestB)) + '</b>, ' + bestB[1] + '.' : "") + '</p>' +
        '<div class="table-scroll"><table class="standings"><tr><th>Date</th><th>Division</th><th>Result</th></tr>' + last + '</table></div>' +
        (n > 10 ? '<p class="finance-note">The ten most recent of ' + n + '. Every meeting is on <a href="' + teamHref(a.id) + '#vs=' + b.id + '">' + esc(a.name) + '\'s page</a>.</p>' : "");
      cb(ms);
    });
  }

  // ── two paths through the pyramid ────────────────────────────────────
  function paths(a, b, meetings) {
    var svg = $("cmp-paths");
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var W = 760, H = 360, L = 44, R = 12, T = 14, Bm = 40;
    var all = a.history.concat(b.history);
    if (!all.length) return;
    var first = Math.min.apply(null, all.map(function (r) { return r[0]; }));
    var last = Math.max.apply(null, all.map(function (r) { return r[0]; }));
    var deepest = Math.max.apply(null, all.map(function (r) { return r[2]; }));
    // Show the tier the lower club reached, whole, so the bands make sense.
    var maxTier = Math.max.apply(null, all.map(function (r) { return r[1]; }));
    var yMax = deepest;
    for (var s = first; s <= last; s++) {
      var off = IDX.offsets[s];
      if (off && off[maxTier] != null) yMax = Math.max(yMax, off[maxTier]);
    }
    function x(sv) { return L + (last === first ? 0.5 : (sv - first) / (last - first)) * (W - L - R); }
    function y(p) { return T + (p - 1) / Math.max(1, yMax - 1) * (H - T - Bm); }
    var colW = (W - L - R) / Math.max(1, last - first);
    for (s = first; s <= last; s++) {
      var o = IDX.offsets[s];
      if (!o) continue;
      for (var tier = 1; tier <= maxTier; tier++) {
        if (o[tier - 1] == null || o[tier] == null) continue;
        svg.appendChild(el("rect", {x: x(s) - colW / 2, width: colW + 0.5, y: y(o[tier - 1] + 1), height: Math.max(0, y(o[tier]) - y(o[tier - 1] + 1)),
                                    fill: tier % 2 ? "#f1f3f5" : "#e7ebef"}));
      }
    }
    for (tier = 1; tier <= maxTier; tier++) {
      var oL = IDX.offsets[last] || IDX.offsets[first];
      if (oL && oL[tier - 1] != null && oL[tier] != null) {
        svg.appendChild(el("text", {x: 4, y: (y(oL[tier - 1] + 1) + y(oL[tier])) / 2 + 3, "font-size": 10, fill: "#6b7683"}, "Tier " + tier));
      }
    }
    for (s = Math.ceil(first / 10) * 10; s <= last; s += 10) {
      svg.appendChild(el("text", {x: x(s), y: H - Bm + 14, "font-size": 10, fill: "#6b7683", "text-anchor": "middle"}, season(s)));
    }
    function line(d, colour) {
      var segs = [], cur = [], prev = null;
      d.history.forEach(function (r) {
        if (prev != null && r[0] !== prev + 1) { segs.push(cur); cur = []; }
        cur.push(r); prev = r[0];
      });
      if (cur.length) segs.push(cur);
      segs.forEach(function (sg) {
        svg.appendChild(el("polyline", {points: sg.map(function (r) { return x(r[0]) + "," + y(r[2]); }).join(" "),
                                        fill: "none", stroke: colour, "stroke-width": 2, "stroke-linejoin": "round"}));
      });
      d.history.forEach(function (r) {
        var c = el("circle", {cx: x(r[0]), cy: y(r[2]), r: 2.5, fill: colour, stroke: "#fcfcfb", "stroke-width": 1});
        c.appendChild(el("title", {}, d.name + ", " + season(r[0]) + ": tier " + r[1] + (r[3] ? ", " + ordinal(r[3]) : "") + " – " + ordinal(r[2]) + " in the pyramid"));
        svg.appendChild(c);
      });
    }
    line(a, CA); line(b, CB);
    var met = {};
    (meetings || []).forEach(function (m) { met[m[0]] = (met[m[0]] || 0) + 1; });
    Object.keys(met).forEach(function (sv) {
      var c = el("circle", {cx: x(+sv), cy: H - Bm + 26, r: 2 + met[sv], fill: "#17202a", opacity: 0.7});
      c.appendChild(el("title", {}, season(+sv) + ": met " + met[sv] + " time" + (met[sv] > 1 ? "s" : "")));
      svg.appendChild(c);
    });
    if (Object.keys(met).length) svg.appendChild(el("text", {x: L, y: H - 2, "font-size": 10, fill: "#6b7683"}, "● seasons they met in the league"));

    // Where one overtook the other, in plain words.
    var bm = {}; b.history.forEach(function (r) { bm[r[0]] = r[2]; });
    var lines = [], ahead = null;
    a.history.forEach(function (r) {
      if (bm[r[0]] == null) return;
      var now = r[2] < bm[r[0]] ? "a" : r[2] > bm[r[0]] ? "b" : ahead;
      if (ahead && now !== ahead) lines.push(season(r[0]) + ": " + (now === "a" ? a.name : b.name) + " went above " + (now === "a" ? b.name : a.name) + ".");
      ahead = now;
    });
    $("cmp-crossings").innerHTML = lines.length
      ? "<p>They swapped places " + lines.length + " time" + (lines.length > 1 ? "s" : "") + ". " + lines.slice(-6).map(esc).join(" ") + (lines.length > 6 ? " (The last six.)" : "") + "</p>"
      : (ahead ? "<p>In every season both are on record, " + esc(ahead === "a" ? a.name : b.name) + " finished higher in the pyramid.</p>" : "");
  }

  // ── seasons in the same division ─────────────────────────────────────
  function together(a, b) {
    var pos = {}; b.history.forEach(function (r) { pos[r[0]] = r[3]; });
    var rows = a.history.filter(function (r) { return b.divisions[r[0]] && b.divisions[r[0]] === a.divisions[r[0]] && pos[r[0]]; });
    if (!rows.length) { $("cmp-same").innerHTML = '<p class="finance-note">Never in the same division on record.</p>'; return; }
    var aw = 0, bw = 0;
    var trs = rows.slice().reverse().map(function (r) {
      var pa = r[3], pb = pos[r[0]];
      if (pa < pb) aw++; else if (pb < pa) bw++;
      return '<tr><td>' + season(r[0]) + '</td><td>' + esc(a.divisions[r[0]]) + '</td><td class="num' + (pa < pb ? " cmp-hi-a" : "") + '">' + ordinal(pa) + '</td><td class="num' + (pb < pa ? " cmp-hi-b" : "") + '">' + ordinal(pb) + '</td></tr>';
    }).join("");
    $("cmp-same").innerHTML = '<p>' + rows.length + ' season' + (rows.length > 1 ? "s" : "") + ' in the same division. ' +
      esc(a.name) + ' finished higher in ' + aw + ', ' + esc(b.name) + ' in ' + bw + '.</p>' +
      '<div class="table-scroll"><table class="standings"><tr><th>Season</th><th>Division</th><th class="num">' + esc(a.name) + '</th><th class="num">' + esc(b.name) + '</th></tr>' + trs + '</table></div>';
  }

  // ── catchment battle ─────────────────────────────────────────────────
  function battle(a, b) {
    var stats = $("cmp-battle-stats"), holder = $("cmp-map");
    var pts = {};
    function add(d, side) {
      d.catchment.forEach(function (p) {
        var k = p[0] + "," + p[1];
        pts[k] = pts[k] || {lat: p[0], lon: p[1], pop: p[2], a: 0, b: 0};
        pts[k][side] = p[3];
      });
    }
    add(a, "a"); add(b, "b");
    var list = Object.keys(pts).map(function (k) { return pts[k]; });
    if (!list.length) {
      stats.innerHTML = '<p class="finance-note">Neither club has a modelled catchment: one or both are no longer playing, or have no ground on record.</p>';
      holder.hidden = true; return;
    }
    holder.hidden = false;
    var pa = 0, pb = 0, both = 0, nBoth = 0;
    list.forEach(function (p) {
      pa += p.pop * p.a; pb += p.pop * p.b;
      if (p.a >= 0.15 && p.b >= 0.15) { both += p.pop; nBoth++; }
    });
    stats.innerHTML = '<div class="stat-cards">' +
      '<div class="stat-card cmp-stat-a"><div class="stat-value">' + (a.catchment.length ? n0(a.stats.catchment_now || pa) : "—") + '</div><div class="stat-label">People ' + esc(a.name) + ' draws</div></div>' +
      '<div class="stat-card cmp-stat-b"><div class="stat-value">' + (b.catchment.length ? n0(b.stats.catchment_now || pb) : "—") + '</div><div class="stat-label">People ' + esc(b.name) + ' draws</div></div>' +
      '<div class="stat-card"><div class="stat-value">' + n0(both) + '</div><div class="stat-label">Living in contested neighbourhoods (' + nBoth + ')</div></div></div>';
    if (!window.L) return;
    if (!map) {
      map = L.map(holder, {scrollWheelZoom: false});
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 12, attribution: "&copy; OpenStreetMap contributors"}).addTo(map);
      mapLayer = L.layerGroup().addTo(map);
    }
    mapLayer.clearLayers();
    list.forEach(function (p) {
      var winA = p.a >= p.b, s = Math.max(p.a, p.b);
      L.circleMarker([p.lat, p.lon], {radius: 2 + 6 * s, weight: p.a >= 0.15 && p.b >= 0.15 ? 1.5 : 0, color: "#17202a",
                                      fillColor: winA ? CA : CB, fillOpacity: 0.25 + 0.65 * s})
        .bindTooltip(n0(p.pop) + " people · " + a.name + " " + pct(p.a) + " · " + b.name + " " + pct(p.b)).addTo(mapLayer);
    });
    [[a, CA], [b, CB]].forEach(function (x) {
      if (x[0].ground.lat != null) L.circleMarker([x[0].ground.lat, x[0].ground.lon], {radius: 7, color: "#17202a", weight: 2, fillColor: x[1], fillOpacity: 1})
        .bindTooltip(x[0].name + ": " + (x[0].facts.stadium || "ground")).addTo(mapLayer);
    });
    map.fitBounds(L.latLngBounds(list.map(function (p) { return [p.lat, p.lon]; })).pad(0.1));
    setTimeout(function () { map.invalidateSize(); }, 50);
  }

  // ── tables ───────────────────────────────────────────────────────────
  function table(target, a, b, rows) {
    $(target).innerHTML = '<tr><th></th><th>' + esc(a.name) + '</th><th>' + esc(b.name) + '</th></tr>' +
      rows.filter(function (r) { return r[1] != null && r[1] !== "" || r[2] != null && r[2] !== ""; }).map(function (r) {
        return '<tr><th scope="row">' + esc(r[0]) + '</th><td>' + (r[3] ? r[1] || "—" : esc(r[1] == null || r[1] === "" ? "—" : r[1])) + '</td><td>' +
               (r[3] ? r[2] || "—" : esc(r[2] == null || r[2] === "" ? "—" : r[2])) + '</td></tr>';
      }).join("");
  }
  function facts(a, b) {
    function rival(d) { return d.facts.rival ? '<a href="#a=' + d.id + '&b=' + d.facts.rival_id + '">' + esc(d.facts.rival) + '</a>' + (d.facts.rival_miles ? " (" + d.facts.rival_miles + " miles)" : "") : null; }
    function rec(d) { var c = d.career; return c.played ? c.played + " played: " + c.won + " won, " + c.drawn + " drawn, " + c.lost + " lost" : null; }
    var fa = a.facts, fb = b.facts;
    table("cmp-facts", a, b, [
      ["Founded", fa.founded, fb.founded], ["Nickname", fa.nickname, fb.nickname],
      ["Ground", fa.stadium, fb.stadium], ["Opened", fa.opened, fb.opened],
      ["Capacity", fa.capacity && n0(fa.capacity), fb.capacity && n0(fb.capacity)],
      ["Who owns the ground", fa.ground_owner, fb.ground_owner],
      ["Owner", fa.owner, fb.owner], ["Ownership", fa.model, fb.model], ["Owner since", fa.owner_since, fb.owner_since],
      ["Natural level", fa.natural_level, fb.natural_level],
      ["Nearest club", rival(a), rival(b), true],
      ["On record", a.first && season(a.first) + " to " + season(a.last), b.first && season(b.first) + " to " + season(b.last)],
      ["League record", rec(a), rec(b)],
      ["Goals", a.career.played ? a.career.gf + " for, " + a.career.ga + " against" : null, b.career.played ? b.career.gf + " for, " + b.career.ga + " against" : null],
      ["Administrations", fa.administrations, fb.administrations], ["Points deductions", fa.deductions, fb.deductions]
    ]);
  }
  function streaks(a, b) {
    function cell(d, k) {
      var s = d.streaks[k];
      if (!s) return null;
      return s.record + (s.season ? " (" + season(s.season) + ")" : "") + (s.current ? "; now " + s.current : "");
    }
    table("cmp-streaks", a, b, Object.keys(IDX.streaks).map(function (k) { return [IDX.streaks[k], cell(a, k), cell(b, k)]; }));
  }
  function accounts(a, b) {
    var ma = a.money || {}, mb = b.money || {};
    if (!a.money && !b.money) { $("cmp-money").innerHTML = '<tr><td class="finance-note">Neither club has accounts on file.</td></tr>'; return; }
    function f(m, k) { return m[k] == null ? null : money(m[k]); }
    table("cmp-money", a, b, [
      ["Year", ma.year && season(ma.year), mb.year && season(mb.year)],
      ["Turnover", f(ma, "turnover"), f(mb, "turnover")], ["Staff costs", f(ma, "staff"), f(mb, "staff")],
      ["Wages as a share", ma.staff && ma.turnover ? pct(ma.staff / ma.turnover) : null, mb.staff && mb.turnover ? pct(mb.staff / mb.turnover) : null],
      ["Profit before tax", f(ma, "profit"), f(mb, "profit")]
    ]);
  }

  // ── routing ──────────────────────────────────────────────────────────
  function route() {
    var a = hs ? hs.get("a") : null, b = hs ? hs.get("b") : null;
    if (a && byId[a]) inA.value = byId[a].name;
    if (b && byId[b]) inB.value = byId[b].name;
    if (!a || !b || !byId[a] || !byId[b] || a === b) {
      body.hidden = true; if (empty) empty.hidden = false; current = "";
      if (a && byId[a] && !b) inB.focus();  // arrived from a club page: A is chosen, B is the question
      return;
    }
    var key = a + "|" + b;
    if (key === current) return;
    current = key;
    loadClub(a, function (da) {
      loadClub(b, function (db) {
        if (current !== key || !da || !db) return;
        body.hidden = false; if (empty) empty.hidden = true;
        document.title = da.name + " v " + db.name + " – compare";
        head(da, db, null);
        tape(da, db); form(da, db); together(da, db); facts(da, db);
        hatred(da, db); levers(da, db); streaks(da, db); accounts(da, db);
        battle(da, db);
        paths(da, db, []);
        h2h(da, db, function (ms) {
          if (current !== key) return;
          var met = $("cmp-met");
          if (met) met.textContent = ms.length ? "met " + ms.length + " times" : "never met in the league";
          paths(da, db, ms);
        });
      });
    });
  }
  window.addEventListener("hashchange", route);
  route();
})();
