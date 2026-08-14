// Insights scatter chart (stadium capacity / revenue / wages / wage-ratio /
// profit / net-debt vs. league position). Vanilla SVG, no dependencies.
//
// Expects window.INSIGHT_SCATTER_DATA = {
//   scale: "linear"|"log"|"signed", formatKind: "count"|"money"|"percent",
//   noun, maxPos, boundaries: [...], benchmarkValue, benchmarkLabel,
//   seasonLabel,
//   points: [{id, name, color, tier, divisionName, position, overallPos,
//             value, valueLabel, tooltip}, ...]
// }
//
// The server renders a complete "all tiers" chart with no JS required; this
// file replaces that markup on load with an identical redraw (one code path
// for the first paint and every later tier-filter change), then wires up
// click-for-detail and the tier-filter chips.
(function () {
  var data = window.INSIGHT_SCATTER_DATA;
  if (!data) return;

  var svg = document.getElementById("insight-scatter-svg");
  var detail = document.getElementById("scatter-detail");
  if (!svg) return;
  var NS = "http://www.w3.org/2000/svg";

  // Keep the viewBox authoritative, matching chart.js's convention.
  var W = 760, H = 380, PAD = {top: 16, right: 20, bottom: 36, left: 64};
  var box = (svg.getAttribute("viewBox") || "").split(/\s+/);
  if (box.length === 4) { W = Number(box[2]) || W; H = Number(box[3]) || H; }
  var plotH = H - PAD.top - PAD.bottom;

  var activeTier = "all";

  function el(name, attrs, text) {
    var node = document.createElementNS(NS, name);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    if (text) node.textContent = text;
    return node;
  }

  // Palette lives in style.css (--tier-1 .. --tier-5), read once so the
  // tier-chip dots can't drift out of step with the plotted points.
  function tierColor(tier) {
    return getComputedStyle(document.documentElement).getPropertyValue("--tier-" + tier).trim();
  }
  (function colorTierChips() {
    Array.prototype.forEach.call(document.querySelectorAll(".scatter-tier-chips .chip[data-tier]"), function (btn) {
      var tier = btn.getAttribute("data-tier");
      var dot = btn.querySelector(".chip-dot");
      if (dot && tier !== "all") dot.style.background = tierColor(tier);
    });
  })();

  // Port of SiteBuilder._fmt_money / the capacity and wage-ratio lambdas in
  // METRICS (site_build.py) - keep in sync with those.
  var FORMATTERS = {
    money: function (v) {
      var sign = v < 0 ? "−" : "";
      var a = Math.abs(v);
      if (a >= 1000000) return sign + "£" + (a / 1000000).toFixed(1) + "m";
      if (a >= 1000) return sign + "£" + Math.round(a / 1000) + "k";
      return sign + "£" + Math.round(a).toLocaleString("en-GB");
    },
    count: function (v) { return Math.trunc(v).toLocaleString("en-GB"); },
    percent: function (v) { return Math.round(v) + "%"; }
  };
  var fmt = FORMATTERS[data.formatKind] || String;

  // Port of SiteBuilder._y_axis (site_build.py) - same padding rule per
  // scale, plus an inverse() to place the intermediate tick labels.
  function yAxis(values, scale) {
    var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);

    if (scale === "log") {
      var loL = Math.log10(lo), hiL = Math.log10(hi);
      var padLog = Math.max(0.05, (hiL - loL) * 0.08);
      loL -= padLog; hiL += padLog;
      var spanLog = Math.max(1e-9, hiL - loL);
      return {
        frac: function (v) { return (Math.log10(v) - loL) / spanLog; },
        inverse: function (t) { return Math.pow(10, loL + t * spanLog); },
        lo: Math.pow(10, loL), hi: Math.pow(10, hiL), zeroFrac: null
      };
    }

    if (scale === "signed") {
      lo = Math.min(lo, 0); hi = Math.max(hi, 0);
      var padSigned = Math.max(1, (hi - lo) * 0.08);
      lo -= padSigned; hi += padSigned;
      var spanSigned = Math.max(1e-9, hi - lo);
      var fracSigned = function (v) { return (v - lo) / spanSigned; };
      return {
        frac: fracSigned, inverse: function (t) { return lo + t * spanSigned; },
        lo: lo, hi: hi, zeroFrac: fracSigned(0)
      };
    }

    // Linear, clamped at zero when every value is already non-negative.
    var padLinear = Math.max(1, Math.round((hi - lo) * 0.08));
    lo = lo >= 0 ? Math.max(0, lo - padLinear) : lo - padLinear;
    hi += padLinear;
    var spanLinear = Math.max(1e-9, hi - lo);
    return {
      frac: function (v) { return (v - lo) / spanLinear; },
      inverse: function (t) { return lo + t * spanLinear; },
      lo: lo, hi: hi, zeroFrac: null
    };
  }

  function visiblePoints() {
    if (activeTier === "all") return data.points;
    return data.points.filter(function (p) { return String(p.tier) === activeTier; });
  }

  // "All tiers" keeps each point's real overallPos (spanning [1, maxPos]),
  // so the tier-boundary dashed lines stay meaningful. A single tier
  // dense-ranks just the visible points 1..N, closing the gaps the other
  // tiers left behind - this is what makes the x-axis "dynamically adjust".
  function xLayout(visible) {
    if (activeTier === "all") {
      return {
        rankOf: function (p) { return p.overallPos; },
        spanX: Math.max(1, data.maxPos - 1),
        xMin: 1, xMax: data.maxPos,
        boundaries: data.boundaries
      };
    }
    var rank = {};
    visible.forEach(function (p, i) { rank[p.id] = i + 1; });
    return {
      rankOf: function (p) { return rank[p.id]; },
      spanX: Math.max(1, visible.length - 1),
      xMin: 1, xMax: visible.length,
      boundaries: []
    };
  }

  // Plain HTML elements, not the SVG-namespace el() helper above - this
  // panel lives outside the <svg>, and an SVG-namespace <strong>/<p> is an
  // unrecognised foreign element with no intrinsic box model, which
  // collapses to almost nothing.
  function showDetail(p) {
    if (!detail) return;
    detail.innerHTML = "";
    var chip = document.createElement("span");
    chip.className = "color-chip";
    chip.style.background = p.color;
    var head = document.createElement("strong");
    head.textContent = p.name + " — " + p.valueLabel + " " + data.noun;
    var body = document.createElement("p");
    body.textContent = p.tooltip;
    detail.appendChild(chip);
    detail.appendChild(head);
    detail.appendChild(body);
    detail.hidden = false;
  }

  function redraw() {
    var visible = visiblePoints();
    svg.innerHTML = "";
    if (!visible.length) return;

    var layout = xLayout(visible);
    var axis = yAxis(visible.map(function (p) { return p.value; }), data.scale);

    function x(pos) {
      return PAD.left + (pos - 1) / layout.spanX * (W - PAD.left - PAD.right);
    }
    function y(v) { return PAD.top + (1 - axis.frac(v)) * plotH; }

    var g = el("g", {});
    svg.appendChild(g);

    layout.boundaries.forEach(function (b) {
      var bx = x(b + 0.5);
      g.appendChild(el("line", {
        x1: bx, y1: PAD.top, x2: bx, y2: H - PAD.bottom,
        stroke: "#e4e8ec", "stroke-width": 1, "stroke-dasharray": "4 4"
      }));
    });

    if (axis.zeroFrac !== null) {
      var zy = y(axis.inverse(axis.zeroFrac));
      g.appendChild(el("line", {
        x1: 64, y1: zy, x2: W - 20, y2: zy, stroke: "#c8ced6", "stroke-width": 1
      }));
      g.appendChild(el("text", {
        x: 60, y: zy + 3, "font-size": 10, fill: "#6b7683", "text-anchor": "end"
      }, "0"));
    }

    if (data.benchmarkValue != null && data.benchmarkValue >= axis.lo && data.benchmarkValue <= axis.hi) {
      var by = y(data.benchmarkValue);
      g.appendChild(el("line", {
        x1: 64, y1: by, x2: W - 20, y2: by, stroke: "#b3261e",
        "stroke-width": 1, "stroke-dasharray": "3 3", opacity: "0.6"
      }));
      g.appendChild(el("text", {
        x: W - 22, y: by - 4, "font-size": 9, fill: "#b3261e", "text-anchor": "end"
      }, data.benchmarkLabel));
    }

    g.appendChild(el("text", {
      x: 60, y: PAD.top + 4, "font-size": 10, fill: "#6b7683", "text-anchor": "end",
      "class": "axis-label-edge"
    }, fmt(axis.hi)));
    g.appendChild(el("text", {
      x: 60, y: H - PAD.bottom, "font-size": 10, fill: "#6b7683", "text-anchor": "end",
      "class": "axis-label-edge"
    }, fmt(axis.lo)));
    [0.25, 0.5, 0.75].forEach(function (t) {
      var ty = PAD.top + (1 - t) * plotH;
      g.appendChild(el("text", {
        x: 60, y: ty + 3, "font-size": 10, fill: "#6b7683", "text-anchor": "end",
        "class": "axis-label-tick"
      }, fmt(axis.inverse(t))));
    });

    var axisY = H - PAD.bottom + 16;
    g.appendChild(el("text", {
      x: 64, y: axisY, "font-size": 10, fill: "#6b7683", "text-anchor": "start"
    }, String(layout.xMin)));
    g.appendChild(el("text", {
      x: W - 20, y: axisY, "font-size": 10, fill: "#6b7683", "text-anchor": "end"
    }, String(layout.xMax)));
    g.appendChild(el("text", {
      x: W / 2, y: axisY, "font-size": 10, fill: "#6b7683", "text-anchor": "middle"
    }, "Overall league position" + (data.seasonLabel ? ", " + data.seasonLabel : "")));

    visible.forEach(function (p) {
      var c = el("circle", {
        cx: x(layout.rankOf(p)).toFixed(1), cy: y(p.value).toFixed(1), r: 5,
        stroke: "#ffffff", "stroke-width": 1, "pointer-events": "all",
        tabindex: "0", role: "button", "class": "scatter-dot", "data-club": p.id
      });
      c.style.fill = "var(--tier-" + p.tier + ")";
      c.appendChild(el("title", {}, p.tooltip));
      function open() { showDetail(p); }
      c.addEventListener("click", open);
      c.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
      });
      g.appendChild(c);
    });
  }

  var chips = document.querySelectorAll(".scatter-tier-chips .chip");
  Array.prototype.forEach.call(chips, function (btn) {
    btn.addEventListener("click", function () {
      Array.prototype.forEach.call(chips, function (b) {
        b.classList.toggle("chip-active", b === btn);
      });
      activeTier = btn.getAttribute("data-tier");
      if (detail) detail.hidden = true;  // may reference a now-hidden point
      redraw();
    });
  });

  redraw();
})();
