// Income around the ground: the money map. Every ONS neighbourhood as a
// canvas dot coloured on one blue ramp - by its own income, or by the
// average income of the club that draws most of it - with the grounds on
// top. Click a ground and only its catchment stays lit.
// Expects window.INCOME_DATA = {
//   points: [[lat, lon, income, pop, clubIdx, ciLo, ciHi]], edges: [..12 decile cuts..],
//   ramp: [..13 hexes..], clubs: [{id, name, tier, lat, lon, mean, sd, gap, people}],
//   names: [msoa name, or its number alone when it starts with the authority],
//   las: [authority index], authorities: [name]
// }
(function () {
  "use strict";
  var data = window.INCOME_DATA;
  var holder = document.getElementById("income-map");
  if (!data || !holder || !window.L) return;
  var panel = document.getElementById("income-club");
  var layer = "area", picked = null;

  function n0(v) { return Math.round(v).toLocaleString("en-GB"); }
  function colour(income) {
    var i = 0;
    while (i < data.edges.length && income > data.edges[i]) i++;
    return data.ramp[i];
  }
  var map = L.map(holder, {scrollWheelZoom: false, preferCanvas: true}).setView([52.6, -1.6], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 13, attribution: "&copy; OpenStreetMap contributors"}).addTo(map);
  var canvas = L.canvas({padding: 0.3});
  var dots = [];
  var dotLayer = L.layerGroup().addTo(map);
  data.points.forEach(function (p, j) {
    var m = L.circleMarker([p[0], p[1]], {renderer: canvas, radius: 3.2, stroke: false, fillColor: colour(p[2]), fillOpacity: 0.85});
    m.bindTooltip(function () {
      var club = p[4] >= 0 ? data.clubs[p[4]] : null;
      var la = data.authorities[data.las[j]] || "", nm = data.names[j];
      var full = /^\d+$/.test(nm) ? la + " " + nm : nm + (la ? ", " + la : "");
      return "<b>" + full + "</b>" + "<br>£" + n0(p[2]) + " (95% range £" + n0(p[5]) + "–£" + n0(p[6]) + ")<br>" + n0(p[3]) + " people" +
             (club ? "<br>Drawn mostly to " + club.name : "");
    }, {sticky: true});
    m.addTo(dotLayer);
    dots.push(m);
  });

  function paint() {
    data.points.forEach(function (p, j) {
      var club = p[4] >= 0 ? data.clubs[p[4]] : null;
      var on = !picked || p[4] === picked;
      var fill, op;
      if (layer === "area") { fill = colour(p[2]); op = on ? 0.85 : 0.08; }
      else if (layer === "club") { fill = club ? colour(club.mean) : "#c8ced6"; op = on ? (club ? 0.8 : 0.3) : 0.08; }
      else { fill = "#c8ced6"; op = picked ? (on ? 0.6 : 0.05) : 0.0; }
      dots[j].setStyle({fillColor: fill, fillOpacity: op});
    });
  }

  // Grounds: a marker per club, bigger the higher the tier, in ink so the
  // ramp keeps the only colour meaning on the map.
  var markers = L.layerGroup().addTo(map);
  data.clubs.forEach(function (c, i) {
    var m = L.circleMarker([c.lat, c.lon], {radius: 9 - c.tier, color: "#17202a", weight: 1.5, fillColor: "#fcfcfb", fillOpacity: 0.95});
    m.bindTooltip(c.name + " (tier " + c.tier + "): £" + n0(c.mean));
    m.on("click", function () { pick(picked === i ? null : i); });
    m.addTo(markers);
  });

  function pick(i) {
    picked = i;
    paint();
    if (!panel) return;
    if (i == null) { panel.hidden = true; return; }
    var c = data.clubs[i];
    var sumPop = 0;
    data.points.forEach(function (p) { if (p[4] === i) sumPop += p[3]; });
    panel.innerHTML = "<p><b><a href='../../team/" + c.id + "/index.html'>" + c.name + "</a></b> – tier " + c.tier +
      ". Average income of the people it draws: <b>£" + n0(c.mean) + "</b>; spread £" + n0(c.sd) +
      "; richest tenth to poorest tenth £" + n0(c.gap) + " apart. " + n0(c.people) + " people in reach; the lit dots are the " +
      n0(sumPop) + " people in neighbourhoods it draws more of than any other club. " +
      "<a href='../../compare/index.html#a=" + c.id + "'>Compare with another club</a>.</p>";
    panel.hidden = false;
    if (window.hashState) window.hashState.set("club", c.id);
  }

  Array.prototype.forEach.call(document.querySelectorAll(".income-layers .chip"), function (btn) {
    btn.addEventListener("click", function () {
      layer = btn.getAttribute("data-layer");
      Array.prototype.forEach.call(document.querySelectorAll(".income-layers .chip"), function (b) {
        var on = b === btn; b.classList.toggle("chip-active", on); b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      var legend = document.getElementById("income-legend");
      if (legend) legend.style.visibility = layer === "people" ? "hidden" : "visible";
      paint();
      if (window.hashState) window.hashState.set("layer", layer === "area" ? null : layer);
    });
  });
  map.on("click", function (e) { if (e.originalEvent.target === map.getContainer() || e.originalEvent.target.tagName === "CANVAS") { if (picked != null) pick(null); } });

  if (window.hashState) {
    var want = window.hashState.get("club");
    var idx = want ? data.clubs.findIndex(function (c) { return c.id === want; }) : -1;
    var l = window.hashState.get("layer");
    if (l === "club" || l === "people") {
      var btn = document.querySelector(".income-layers .chip[data-layer=" + l + "]");
      if (btn) btn.click();
    }
    if (idx >= 0) { pick(idx); map.setView([data.clubs[idx].lat, data.clubs[idx].lon], 10); }
  }
  paint();
})();
