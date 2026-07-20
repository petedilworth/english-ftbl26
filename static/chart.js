// Interactive multi-club trajectory chart. Vanilla SVG, no dependencies.
// Expects window.CHART_DATA = {
//   years: [1994, ...],
//   maxPos: 112,
//   tierFloors: {"1994": [22, 46, 70, 92], ...},  // cumulative clubs per tier boundary
//   clubs: [{id, name, color, series: [[year, overallPos], ...]}, ...]
// }
(function () {
  var data = window.CHART_DATA;
  if (!data) return;

  var svg = document.getElementById("trajectory-chart");
  var picker = document.getElementById("club-picker");
  var filter = document.getElementById("club-filter");
  var hint = document.getElementById("chart-hint");
  var NS = "http://www.w3.org/2000/svg";

  var W = 720, H = 420, PAD = {top: 12, right: 14, bottom: 28, left: 38};
  var years = data.years;
  var minYear = years[0], maxYear = years[years.length - 1];
  var selected = {};

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

  function drawBase() {
    svg.innerHTML = "";
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
      if (d) svg.appendChild(el("path", {d: d, fill: "none", stroke: "#d9dee3", "stroke-width": 1}));
    }
    // Axes labels
    for (var yr2 = Math.ceil(minYear / 4) * 4; yr2 <= maxYear; yr2 += 4) {
      svg.appendChild(el("text", {x: x(yr2), y: H - 8, "font-size": 10,
        fill: "#6b7683", "text-anchor": "middle"}, String(yr2)));
    }
    var posTicks = [1, 20, 44, 68, 92];
    posTicks.forEach(function (p) {
      if (p <= data.maxPos) {
        svg.appendChild(el("text", {x: PAD.left - 6, y: y(p) + 3, "font-size": 10,
          fill: "#6b7683", "text-anchor": "end"}, String(p)));
      }
    });
  }

  function drawLines() {
    drawBase();
    var any = false;
    data.clubs.forEach(function (club) {
      if (!selected[club.id]) return;
      any = true;
      var d = "", prevYear = null;
      club.series.forEach(function (pt) {
        var cmd = (prevYear !== null && pt[0] - prevYear === 1) ? " L" : (d ? " M" : "M");
        d += cmd + x(pt[0]).toFixed(1) + " " + y(pt[1]).toFixed(1);
        prevYear = pt[0];
      });
      svg.appendChild(el("path", {d: d, fill: "none", stroke: club.color,
        "stroke-width": 2, "stroke-linejoin": "round"}));
      var last = club.series[club.series.length - 1];
      svg.appendChild(el("circle", {cx: x(last[0]), cy: y(last[1]), r: 3, fill: club.color}));
    });
    hint.style.display = any ? "none" : "";
  }

  function buildPicker() {
    data.clubs.forEach(function (club) {
      var label = document.createElement("label");
      label.className = "club-check";
      label.setAttribute("data-name", club.name.toLowerCase());
      var box = document.createElement("input");
      box.type = "checkbox";
      box.addEventListener("change", function () {
        selected[club.id] = box.checked;
        drawLines();
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

  filter.addEventListener("input", function () {
    var q = filter.value.toLowerCase().trim();
    Array.prototype.forEach.call(picker.children, function (labelEl) {
      labelEl.style.display =
        !q || labelEl.getAttribute("data-name").indexOf(q) !== -1 ? "" : "none";
    });
  });

  buildPicker();
  drawLines();
})();
