// Which club to buy: fourteen levers, a weight each, one ranked stacked bar
// per club. Each lever is already a 0-1 percentile (src/value.py); this
// only weights and sorts. A missing lever counts at 0.5 and is drawn
// hatched at the end of the bar, so a guess never looks like a fact.
// Expects window.VALUE_DATA = {
//   groups: [{key, label, color}], levers: [{key, group, label, note}], shown,
//   clubs: [{id, name, tier, fan, flags, l: [0..1 | null per lever], raw: {key: text}}]
// }
// The fragment keeps the view: #w=50,50,... (lever order), money=0, fan=1,
// disc=100 (the tier discount, per cent).
// The tier discount ranks by index minus a share of the average index of
// the club's tier, taken over every club in that tier whatever is shown,
// so hiding a tier never moves another tier's average.
(function () {
  var data = window.VALUE_DATA;
  if (!data) return;
  var list = document.getElementById("index-bars");
  var detail = document.getElementById("value-detail");
  var more = document.querySelector(".index-more");
  var moneyBox = document.querySelector(".value-money");
  var fanBox = document.querySelector(".value-fan");
  var discount = document.getElementById("value-discount");
  var means = {};  // tier -> average index at the current weights, for show()
  var sliders = Array.prototype.slice.call(document.querySelectorAll(".value-groups input[type=range]"));
  var tierChips = Array.prototype.slice.call(document.querySelectorAll(".value-tier-chips .chip"));
  var levers = data.levers;
  // In lever order whatever order the page lays them out in.
  var slot = {};
  levers.forEach(function (lv, i) { slot[lv.key] = i; });
  sliders.sort(function (a, b) { return slot[a.getAttribute("data-lever")] - slot[b.getAttribute("data-lever")]; });
  var colour = {};
  data.groups.forEach(function (g) { colour[g.key] = g.color; });
  var byId = {};
  data.clubs.forEach(function (c) { byId[c.id] = c; });
  var showAll = false;
  var hs = window.hashState;

  function weights() {
    var money = !moneyBox || moneyBox.checked;
    return levers.map(function (lv, i) {
      return lv.group === "money" && !money ? 0 : Number(sliders[i].value);
    });
  }
  function tiersOn() {
    var on = {};
    tierChips.forEach(function (b) { if (b.classList.contains("chip-active")) on[b.getAttribute("data-tier")] = true; });
    return on;
  }
  function visible(c, on) { return on[String(c.tier)] && (c.fan ? fanBox && fanBox.checked : true); }

  function score(w, clubs) {
    var total = w.reduce(function (t, x) { return t + x; }, 0);
    return clubs.map(function (c) {
      var parts = [], missing = 0, idx = 0;
      levers.forEach(function (lv, i) {
        var v = c.l[i], p = total ? 100 * w[i] * (v == null ? 0.5 : v) / total : 0;
        if (v == null) missing += p; else parts.push(p);
        idx += p;
      });
      return {club: c, parts: parts, missing: missing, index: idx};
    }).sort(function (a, b) { return b.index - a.index || a.club.name.localeCompare(b.club.name); });
  }

  function draw() {
    if (!list) return;
    var w = weights();
    var total = w.reduce(function (t, x) { return t + x; }, 0);
    Array.prototype.forEach.call(document.querySelectorAll(".index-weight-share"), function (o) {
      var i = slot[o.getAttribute("data-lever")];
      o.textContent = total ? Math.round(100 * w[i] / total) + "%" : "0%";
    });
    Array.prototype.forEach.call(document.querySelectorAll(".value-group[data-group=money]"), function (g) {
      g.classList.toggle("is-off", !!moneyBox && !moneyBox.checked);
    });
    var on = tiersOn();
    var pool = data.clubs.filter(function (c) { return visible(c, on); });
    var alpha = discount ? Number(discount.value) / 100 : 0;
    var sums = {}, counts = {};
    score(w, data.clubs).forEach(function (r) {
      sums[r.club.tier] = (sums[r.club.tier] || 0) + r.index;
      counts[r.club.tier] = (counts[r.club.tier] || 0) + 1;
    });
    means = {};
    Object.keys(sums).forEach(function (t) { means[t] = sums[t] / counts[t]; });
    var ranked = score(w, pool);
    ranked.forEach(function (r) { r.adj = r.index - alpha * means[r.club.tier]; });
    ranked.sort(function (a, b) { return b.adj - a.adj || a.club.name.localeCompare(b.club.name); });
    var dOut = document.querySelector(".value-discount-share");
    if (dOut) dOut.textContent = Math.round(alpha * 100) + "%";
    var equalRank = {};
    score(levers.map(function (lv) { return lv.group === "money" && moneyBox && !moneyBox.checked ? 0 : 1; }), pool)
      .forEach(function (r, i) { equalRank[r.club.id] = i + 1; });
    var top = Math.max.apply(null, ranked.map(function (r) { return r.index; }).concat([1]));
    var items = {};
    Array.prototype.forEach.call(list.children, function (li) { items[li.getAttribute("data-club")] = li; li.hidden = true; });
    ranked.forEach(function (r, i) {
      var li = items[r.club.id];
      if (!li) return;
      li.querySelector(".index-rank").textContent = i + 1;
      var track = li.querySelector(".index-track");
      track.innerHTML = "";
      // One segment per family: fourteen slivers read as noise on a phone.
      data.groups.forEach(function (g) {
        var sum = 0, bits = [];
        levers.forEach(function (lv, k) {
          var v = r.club.l[k];
          if (lv.group !== g.key || v == null || !w[k]) return;
          sum += 100 * w[k] * v / total;
          bits.push(lv.label + " " + v.toFixed(2));
        });
        if (sum <= 0) return;
        var seg = document.createElement("span");
        seg.className = "index-seg";
        seg.style.width = (100 * sum / top) + "%";
        seg.style.background = colour[g.key];
        seg.title = g.label + ": " + bits.join(", ");
        track.appendChild(seg);
      });
      if (alpha > 0) {
        var tick = document.createElement("span");
        tick.className = "index-tick";
        tick.style.left = (100 * means[r.club.tier] / top) + "%";
        tick.title = "Tier " + r.club.tier + " average: " + Math.round(means[r.club.tier]);
        track.insertBefore(tick, track.firstChild);  // first, so the last segment keeps its rounded end
      }
      if (r.missing > 0) {
        var gap = document.createElement("span");
        gap.className = "index-seg is-missing";
        gap.style.width = (100 * r.missing / top) + "%";
        gap.title = "No data, counted at the middle: " + levers.filter(function (lv, k) {
          return r.club.l[k] == null && w[k];
        }).map(function (lv) { return lv.label; }).join(", ");
        track.appendChild(gap);
      }
      var val = li.querySelector(".index-value");
      if (alpha > 0) {
        var a = Math.round(r.adj);
        val.firstChild.nodeValue = (a > 0 ? "+" : "") + a;
        val.title = "Index " + Math.round(r.index) + " less " + Math.round(alpha * 100) + "% of the tier " +
                    r.club.tier + " average (" + Math.round(means[r.club.tier]) + ")";
      } else {
        val.firstChild.nodeValue = Math.round(r.index);
        val.title = "";
      }
      var move = equalRank[r.club.id] - (i + 1);
      var mv = li.querySelector(".index-move");
      mv.textContent = move > 0 ? " ▲" + move : move < 0 ? " ▼" + (-move) : "";
      mv.title = move ? "Rank " + equalRank[r.club.id] + " at equal weights" : "";
      li.hidden = !showAll && i >= data.shown;
      list.appendChild(li);
    });
    if (more) {
      more.hidden = ranked.length <= data.shown;
      more.textContent = showAll ? "Show the top " + data.shown : "Show all " + ranked.length;
    }
    if (hs) {
      var equal = sliders.every(function (s) { return s.value === sliders[0].value; }) && Number(sliders[0].value) > 0;
      hs.set("w", equal ? null : sliders.map(function (s) { return s.value; }).join(","));
      hs.set("money", moneyBox && !moneyBox.checked ? "0" : null);
      hs.set("fan", fanBox && fanBox.checked ? "1" : null);
      hs.set("disc", alpha > 0 ? String(Math.round(alpha * 100)) : null);
      var off = tierChips.filter(function (b) { return !b.classList.contains("chip-active"); });
      hs.set("tiers", off.length ? tierChips.filter(function (b) { return b.classList.contains("chip-active"); })
        .map(function (b) { return b.getAttribute("data-tier"); }).join(",") : null);
    }
  }

  function show(c) {
    if (!detail) return;
    var lines = ["<b>" + c.name + "</b> – tier " + c.tier + (c.flags.length ? " · " + c.flags.join(", ") : "")];
    var w = weights(), total = w.reduce(function (t, x) { return t + x; }, 0);
    if (total && means[c.tier] != null) {
      var idx = score(w, [c])[0].index, gap = idx - means[c.tier];
      lines.push("Index " + Math.round(idx) + " against a tier " + c.tier + " average of " + Math.round(means[c.tier]) +
                 ": " + Math.abs(Math.round(gap)) + (gap >= 0 ? " above" : " below") + " its division, at these weights.");
    }
    data.groups.forEach(function (g) {
      var bits = [];
      levers.forEach(function (lv, k) {
        if (lv.group !== g.key) return;
        var v = c.l[k];
        bits.push(lv.label + " " + (v == null ? "<i>no data</i>" : v.toFixed(2)) +
                  (c.raw[lv.key] ? " (" + c.raw[lv.key] + ")" : ""));
      });
      lines.push("<b>" + g.label + "</b>: " + bits.join(" · "));
    });
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
  [moneyBox, fanBox].forEach(function (b) { if (b) b.addEventListener("change", draw); });
  if (discount) discount.addEventListener("input", draw);
  tierChips.forEach(function (b) {
    b.addEventListener("click", function () {
      var on = !b.classList.contains("chip-active");
      b.classList.toggle("chip-active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
      draw();
    });
  });
  var reset = document.querySelector(".index-reset");
  if (reset) reset.addEventListener("click", function () {
    sliders.forEach(function (s) { s.value = 50; });
    draw();
  });
  if (more) more.addEventListener("click", function () {
    showAll = !showAll;
    more.setAttribute("aria-expanded", showAll ? "true" : "false");
    draw();
  });

  // A bookmarked view, if the fragment carries one.
  if (hs) {
    var saved = hs.get("w");
    if (saved) {
      var vals = saved.split(",").map(Number);
      if (vals.length === sliders.length && vals.every(function (v) { return v >= 0 && v <= 100; })) {
        sliders.forEach(function (s, i) { s.value = vals[i]; });
      }
    }
    if (moneyBox && hs.get("money") === "0") moneyBox.checked = false;
    if (fanBox && hs.get("fan") === "1") fanBox.checked = true;
    var disc = Number(hs.get("disc"));
    if (discount && disc > 0 && disc <= 100) discount.value = disc;
    var tiers = hs.get("tiers");
    if (tiers) {
      var keep = tiers.split(",");
      tierChips.forEach(function (b) {
        var on = keep.indexOf(b.getAttribute("data-tier")) >= 0;
        b.classList.toggle("chip-active", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }
  }
  draw();
})();
