// Yo-yo clubs: the seismograph. The traces are server-rendered, one <g>
// per club with its three scores as data attributes; this script only
// reorders them, shows more, draws the hover tooltip from yoyo-data.js,
// and pins a club's moves below the chart. Nothing here is needed to read
// the page with the script switched off.
// Expects window.YOYO_DATA = {first, n, header, rowH, left, colW, divisions: [..],
//   clubs: {id: {name, t: [tier|null], k: "SPR?-", d: [divIdx], p: [pos|null]}}}
(function () {
  "use strict";
  var data = window.YOYO_DATA;
  var svg = document.getElementById("seismograph");
  if (!svg || !data) return;
  var rows = Array.prototype.slice.call(svg.querySelectorAll(".seis-row"));
  var tip = document.getElementById("seis-tip");
  var detail = document.getElementById("seis-detail");
  var more = document.querySelector(".seis-more");
  var showAll = false, key = "run";
  var SHOW = 20;

  function season(y) { return (y - 1) + "/" + String(y % 100).padStart(2, "0"); }
  function ordinal(n) { var s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
  var KIND = {P: "promoted", R: "relegated", S: "stayed", "?": "in progress", "-": ""};

  function layout() {
    var sorted = rows.slice().sort(function (a, b) {
      var d = Number(b.getAttribute("data-" + key)) - Number(a.getAttribute("data-" + key));
      if (d) return d;
      if (key === "run") { d = Number(b.getAttribute("data-run-end")) - Number(a.getAttribute("data-run-end")); if (d) return d; }
      return a.getAttribute("data-club") < b.getAttribute("data-club") ? -1 : 1;
    });
    var shown = 0;
    sorted.forEach(function (g, i) {
      var on = showAll || i < SHOW;
      // An SVG element has no .hidden property: the attribute is what the stylesheet reads.
      if (on) g.removeAttribute("hidden"); else g.setAttribute("hidden", "");
      if (on) { g.setAttribute("transform", "translate(0," + (data.header + shown * data.rowH) + ")"); shown++; }
      svg.appendChild(g);  // document order follows the ranking, for screen readers and tab order
    });
    var h = data.header + shown * data.rowH;
    svg.setAttribute("viewBox", "0 0 " + data.width + " " + h);
    Array.prototype.forEach.call(svg.querySelectorAll(".seis-grid"), function (l) { l.setAttribute("y2", h); });
    if (more) more.textContent = showAll ? "Show the top " + SHOW : "Show all " + rows.length + " traces";
  }

  Array.prototype.forEach.call(document.querySelectorAll(".seis-chips .chip"), function (btn) {
    btn.addEventListener("click", function () {
      key = btn.getAttribute("data-key");
      Array.prototype.forEach.call(document.querySelectorAll(".seis-chips .chip"), function (b) {
        var on = b === btn; b.classList.toggle("chip-active", on); b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      layout();
    });
  });
  if (more) more.addEventListener("click", function () {
    showAll = !showAll; more.setAttribute("aria-expanded", showAll ? "true" : "false"); layout();
  });

  // Hover: which season is under the pointer, from its x in SVG units.
  function seasonAt(evt) {
    var pt = svg.createSVGPoint(); pt.x = evt.clientX; pt.y = evt.clientY;
    var p = pt.matrixTransform(svg.getScreenCTM().inverse());
    var i = Math.round((p.x - data.left) / data.colW);
    return i >= 0 && i < data.n ? i : null;
  }
  rows.forEach(function (g) {
    var id = g.getAttribute("data-club"), c = data.clubs[id];
    if (!c) return;
    g.addEventListener("mousemove", function (evt) {
      var i = seasonAt(evt);
      if (i == null || c.t[i] == null) { tip.hidden = true; return; }
      var what = KIND[c.k[i]];
      tip.innerHTML = "<b>" + c.name + "</b> " + season(data.first + i) + "<br>" + data.divisions[c.d[i]] +
                      (c.p[i] ? ", " + ordinal(c.p[i]) : "") + (what && what !== "stayed" ? " – " + what : "");
      tip.hidden = false;
      var holder = svg.parentNode.getBoundingClientRect();
      tip.style.left = Math.min(evt.clientX - holder.left + 12, holder.width - 220) + "px";
      tip.style.top = (evt.clientY - holder.top + 12) + "px";
    });
    g.addEventListener("mouseleave", function () { tip.hidden = true; });
    g.addEventListener("click", function (evt) {
      if (evt.target.closest("a")) return;  // the name is a link to the club page
      pin(id);
    });
  });

  function pin(id) {
    var c = data.clubs[id];
    if (!c || !detail) return;
    var moves = [];
    for (var i = 0; i < data.n; i++) {
      if (c.k[i] === "P" || c.k[i] === "R") {
        moves.push({s: data.first + i, k: c.k[i], div: data.divisions[c.d[i]], pos: c.p[i]});
      }
    }
    var html = "<p><b>" + c.name + "</b>: " + moves.length + " move" + (moves.length === 1 ? "" : "s") + " on record.</p>";
    if (moves.length) {
      html += '<div class="yoyo-moves">' + moves.map(function (m) {
        return '<span class="yoyo-move yoyo-move-' + m.k + '" title="' + season(m.s) + ": " + m.div + (m.pos ? ", " + ordinal(m.pos) : "") + '">' +
               (m.k === "P" ? "▲" : "▼") + " " + season(m.s) + "</span>";
      }).join("") + "</div>";
    }
    detail.innerHTML = html;
    detail.hidden = false;
  }

  layout();
  // On a phone the chart scrolls sideways: open it at the recent end,
  // where the live runs are, not at 1958/59.
  var holder = svg.parentNode;
  if (holder.scrollWidth > holder.clientWidth) holder.scrollLeft = holder.scrollWidth;
})();
