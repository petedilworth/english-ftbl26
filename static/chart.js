// Interactive multi-club trajectory chart. Vanilla SVG, no dependencies.
// Serves both the global chart page and the per-theme charts.
//
// Expects window.CHART_DATA = {
//   years: [1994, ...],
//   maxPos: 112,
//   tierFloors: {"1994": [22, 46, 70, 92], ...},  // cumulative clubs per tier boundary
//   clubs: [{id, name, color, series: [[year, overallPos, event], ...],
//            events: [{season_end_year, label, text}, ...]  // optional
//          }, ...]
//     event is "promoted", "relegated", or null
//   preselect: ["club-id", ...]   // optional; drawn on load
//   hasFilter: true               // optional; false hides the search box wiring
// }
(function () {
  var data = window.CHART_DATA;
  if (!data) return;

  var UP = "#1a7f3c", DOWN = "#b3261e", STORY = "#8a3ffc";

  var svg = document.getElementById("trajectory-chart");
  var picker = document.getElementById("club-picker");
  var filter = document.getElementById("club-filter");
  var hint = document.getElementById("chart-hint");
  var detail = document.getElementById("chart-detail");
  if (!svg) return;
  var NS = "http://www.w3.org/2000/svg";

  var W = 720, H = 420, PAD = {top: 12, right: 14, bottom: 28, left: 38};
  // Keep the viewBox authoritative, so geometry lives in one place.
  var box = (svg.getAttribute("viewBox") || "").split(/\s+/);
  if (box.length === 4) { W = Number(box[2]) || W; H = Number(box[3]) || H; }

  var years = data.years;
  var minYear = years[0], maxYear = years[years.length - 1];
  var selected = {};
  (data.preselect || []).forEach(function (id) { selected[id] = true; });

  function x(year) {
    return PAD.left + (year - minYear) / Math.max(1, maxYear - minYear) * (W - PAD.left - PAD.right);
  }
  function y(pos) {
    return PAD.top + (pos - 1) / Math.max(1, data.maxPos - 1) * (H - PAD.top - PAD.bottom);
  }

  function el(name, attrs, text) {
    var node = document.createElementNS(NS, name);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    if (text) node.textContent = text;
    return node;
  }

  function seasonLabel(year) {
    return (year - 1) + "/" + String(year).slice(-2).padStart(2, "0");
  }

  function drawBase(layer) {
    // Tier boundary step-lines (where each tier ends, per season)
    var boundaryCount = 0;
    for (var yr in data.tierFloors) boundaryCount = Math.max(boundaryCount, data.tierFloors[yr].length);
    for (var b = 0; b < boundaryCount; b++) {
      var d = "";
      for (var i = 0; i < years.length; i++) {
        var floors = data.tierFloors[String(years[i])] || [];
        if (b >= floors.length) continue;
        var yy = y(floors[b] + 0.5);
        d += (d ? " L" : "M") + x(years[i]).toFixed(1) + " " + yy.toFixed(1);
      }
      if (d) layer.appendChild(el("path", {d: d, fill: "none", stroke: "#e4e8ec", "stroke-width": 1}));
    }
    // Axes labels
    for (var yr2 = Math.ceil(minYear / 4) * 4; yr2 <= maxYear; yr2 += 4) {
      layer.appendChild(el("text", {x: x(yr2), y: H - 8, "font-size": 10,
        fill: "#6b7683", "text-anchor": "middle"}, String(yr2)));
    }
    var posTicks = [1, 20, 44, 68, 92];
    posTicks.forEach(function (p) {
      if (p <= data.maxPos) {
        layer.appendChild(el("text", {x: PAD.left - 6, y: y(p) + 3, "font-size": 10,
          fill: "#6b7683", "text-anchor": "end"}, String(p)));
      }
    });
  }

  function showDetail(club, event) {
    if (!detail) return;
    detail.innerHTML = "";
    var chip = document.createElement("span");
    chip.className = "color-chip";
    chip.style.background = club.color;
    var head = document.createElement("strong");
    head.textContent = club.name + " — " + event.label + ", " + seasonLabel(event.season_end_year);
    var body = document.createElement("p");
    body.textContent = event.text;
    detail.appendChild(chip);
    detail.appendChild(head);
    detail.appendChild(body);
    detail.hidden = false;
  }

  function draw() {
    svg.innerHTML = "";
    // Three layers, so club lines can never paint over another club's dots.
    var baseLayer = el("g", {});
    var lineLayer = el("g", {});
    var dotLayer = el("g", {});
    svg.appendChild(baseLayer);
    svg.appendChild(lineLayer);
    svg.appendChild(dotLayer);

    drawBase(baseLayer);

    var any = false;
    data.clubs.forEach(function (club) {
      if (!selected[club.id]) return;
      any = true;

      var d = "", prevYear = null, posByYear = {};
      club.series.forEach(function (pt) {
        var cmd = (prevYear !== null && pt[0] - prevYear === 1) ? " L" : (d ? " M" : "M");
        d += cmd + x(pt[0]).toFixed(1) + " " + y(pt[1]).toFixed(1);
        prevYear = pt[0];
        posByYear[pt[0]] = pt[1];
      });
      lineLayer.appendChild(el("path", {d: d, fill: "none", stroke: club.color,
        "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round"}));

      club.series.forEach(function (pt) {
        if (pt[2] === "promoted" || pt[2] === "relegated") {
          dotLayer.appendChild(el("circle", {cx: x(pt[0]), cy: y(pt[1]), r: 3.5,
            fill: pt[2] === "promoted" ? UP : DOWN, stroke: "#fff", "stroke-width": 1}));
        }
      });

      // Theme event markers. An event whose season falls outside this club's
      // plotted range has no position to sit at, so it gets no dot - the
      // narrative below the chart carries it instead.
      (club.events || []).forEach(function (event) {
        var pos = posByYear[event.season_end_year];
        if (!pos) return;
        // fill:none would leave the ring's interior transparent to hit-testing,
        // so clicks would fall through to the club line underneath. Filling it
        // with "none" is the look we want, so pointer-events carries the hit.
        var marker = el("circle", {
          cx: x(event.season_end_year), cy: y(pos), r: 6,
          fill: "none", stroke: STORY, "stroke-width": 2,
          "pointer-events": "all",
          "class": "event-dot", tabindex: "0", role: "button"
        });
        marker.style.cursor = "pointer";
        marker.appendChild(el("title", {}, club.name + " — " + event.label));
        function open() { showDetail(club, event); }
        marker.addEventListener("click", open);
        marker.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
        });
        dotLayer.appendChild(marker);
      });

      var last = club.series[club.series.length - 1];
      dotLayer.appendChild(el("circle", {cx: x(last[0]), cy: y(last[1]), r: 3, fill: club.color}));
    });

    if (hint) hint.style.display = any ? "none" : "";
  }

  function buildPicker() {
    if (!picker) return;
    data.clubs.forEach(function (club) {
      var label = document.createElement("label");
      label.className = "club-check";
      label.setAttribute("data-name", club.name.toLowerCase());
      var box = document.createElement("input");
      box.type = "checkbox";
      box.checked = !!selected[club.id];
      box.addEventListener("change", function () {
        selected[club.id] = box.checked;
        draw();
      });
      var chip = document.createElement("span");
      chip.className = "color-chip";
      chip.style.background = club.color;
      label.appendChild(box);
      label.appendChild(chip);
      label.appendChild(document.createTextNode(club.name));
      picker.appendChild(label);
    });
  }

  if (filter && picker) {
    filter.addEventListener("input", function () {
      var q = filter.value.toLowerCase().trim();
      Array.prototype.forEach.call(picker.children, function (labelEl) {
        labelEl.style.display =
          !q || labelEl.getAttribute("data-name").indexOf(q) !== -1 ? "" : "none";
      });
    });
  }

  buildPicker();
  draw();
})();
