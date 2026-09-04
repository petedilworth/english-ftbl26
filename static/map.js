// Groundhop Map: Leaflet markers with a season slider, story filters,
// and postcode distances (postcodes.io, free and keyless).
// Expects window.MAP_DATA = {
//   years: [...], clubs: [{id, name, stadium, lat, lon, color, tier,
//     defunct, fallen, yoyo, everpresent, tiers: {"1994": 1, ...}}]
// }
(function () {
  var data = window.MAP_DATA;
  if (!data) return;

  // Palette lives in style.css (--tier-1 .. --tier-5, --tier-out) so the
  // markers, this page's legend and the natural-level bar on team pages
  // can't drift apart. Falls back to the literals if the sheet is missing.
  function tierColor(tier, fallback) {
    var v = getComputedStyle(document.documentElement)
      .getPropertyValue("--tier-" + tier).trim();
    return v || fallback;
  }
  var TIER_COLORS = {
    1: tierColor(1, "#5e35b1"), 2: tierColor(2, "#1e88e5"), 3: tierColor(3, "#43a047"),
    4: tierColor(4, "#fb8c00"), 5: tierColor(5, "#e53935")
  };
  var GHOST = tierColor("out", "#9aa3ab");

  // Legend is built from TIER_COLORS rather than hand-written in the template,
  // so the swatches can't drift out of step with the markers themselves. It
  // runs before the Leaflet check because it needs nothing from Leaflet - if
  // the CDN is unreachable the key should still explain the colour scheme.
  (function buildLegend() {
    var holder = document.getElementById("map-legend");
    if (!holder) return;
    var names = data.tierNames || {};

    function entry(color, label) {
      var item = document.createElement("span");
      item.className = "legend-item";
      var swatch = document.createElement("span");
      swatch.className = "legend-dot";
      swatch.style.background = color;
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(label));
      holder.appendChild(item);
    }

    Object.keys(TIER_COLORS).forEach(function (tier) {
      entry(TIER_COLORS[tier], names[tier] || "Tier " + tier);
    });
    entry(GHOST, "Outside Tiers 1–5 that season, or defunct");
  })();

  // Tier filter chip dots are coloured from the same TIER_COLORS dict, so a
  // colour change can't leave the legend, chips and markers out of step. As
  // with the legend, this needs nothing from Leaflet, so it runs first.
  (function colorTierChips() {
    Array.prototype.forEach.call(document.querySelectorAll(".map-tier-chips .chip[data-tier]"), function (btn) {
      var tier = btn.getAttribute("data-tier");
      var dot = btn.querySelector(".chip-dot");
      if (dot && TIER_COLORS[tier]) dot.style.background = TIER_COLORS[tier];
    });
  })();

  if (typeof L === "undefined") return;

  var map = L.map("map", {scrollWheelZoom: false}).setView([52.8, -1.7], 6);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 17,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(map);

  var slider = document.getElementById("year-slider");
  var yearLabel = document.getElementById("year-label");
  var activeFilter = "all";
  var activeTier = "all";
  var markers = {};

  function seasonLabel(year) {
    var prev = year - 1;
    return prev + "/" + String(year).slice(-2).padStart(2, "0");
  }

  function passesFilter(club) {
    if (activeFilter === "all") return true;
    if (activeFilter === "fallen") return club.fallen;
    if (activeFilter === "yoyo") return club.yoyo;
    if (activeFilter === "defunct") return club.defunct;
    if (activeFilter === "everpresent") return club.everpresent;
    return true;
  }

  // Unlike the story flags above, tier is per-season rather than a fixed
  // club property, so this takes the year the slider is currently on.
  function passesTierFilter(club, year) {
    if (activeTier === "all") return true;
    return String(club.tiers[year]) === activeTier;
  }

  // ── Catchment cells ───────────────────────────────────────────────────
  // The number says Marine keep about three per cent of the people
  // nearest to them. The cells say WHICH people and how much of each,
  // which is the thing a percentage cannot show.
  //
  // Each dot is one of 6,829 ONS areas, placed at the area's
  // population-weighted centre, coloured by the club whose ground is
  // closest to it, and faded by the share that club actually keeps once
  // its neighbours have pulled. A solid patch is a club with its own
  // town; a washed-out one is a club sharing it. Drawn on canvas because
  // seven thousand SVG circles is not something a phone enjoys.
  var cellLayer = null;
  var cellsOn = false;

  function buildCells() {
    if (cellLayer || !data.cells || !data.cells.length) return;
    cellLayer = L.layerGroup();
    var canvas = L.canvas({padding: 0.3});
    data.cells.forEach(function (cell) {
      var club = data.clubs[cell[2]];
      if (!club) return;
      var kept = cell[3];
      L.circleMarker([cell[0], cell[1]], {
        renderer: canvas,
        radius: 3,
        stroke: false,
        fillColor: club.color,
        // Floor the opacity so a heavily contested area is still visible
        // as belonging to someone - invisible would read as "no data",
        // which is the opposite of what a contested cell means.
        fillOpacity: 0.15 + 0.65 * kept
      }).addTo(cellLayer);
    });
  }

  var cellButton = document.getElementById("map-cells");
  if (cellButton) {
    cellButton.addEventListener("click", function () {
      cellsOn = !cellsOn;
      if (cellsOn) {
        buildCells();
        if (cellLayer) cellLayer.addTo(map);
      } else if (cellLayer) {
        map.removeLayer(cellLayer);
      }
      cellButton.classList.toggle("chip-active", cellsOn);
      cellButton.setAttribute("aria-pressed", cellsOn ? "true" : "false");
      var hint = document.getElementById("map-cells-hint");
      if (hint) {
        hint.textContent = cellsOn
          ? "Each dot is a neighbourhood, coloured by its nearest club and faded by the share that club keeps."
          : "";
      }
    });
    if (!data.cells || !data.cells.length) cellButton.disabled = true;
  }

  function refresh() {
    var year = String(slider.value);
    yearLabel.textContent = seasonLabel(Number(year));
    data.clubs.forEach(function (club) {
      var marker = markers[club.id];
      var tier = club.tiers[year];
      var visible = passesFilter(club) && passesTierFilter(club, year);
      if (!visible) {
        marker.setStyle({opacity: 0, fillOpacity: 0});
        marker.closePopup();
        return;
      }
      if (tier) {
        marker.setStyle({
          opacity: 1, fillOpacity: 0.85,
          color: "#ffffff", fillColor: TIER_COLORS[tier] || GHOST, radius: 7
        });
      } else {
        // Not in Tiers 1-5 that season (below the pyramid, folded, or not yet formed)
        marker.setStyle({
          opacity: 1, fillOpacity: 0.4,
          color: "#ffffff", fillColor: GHOST, radius: 5
        });
      }
    });
  }

  data.clubs.forEach(function (club) {
    var marker = L.circleMarker([club.lat, club.lon], {weight: 1});
    var status = club.defunct ? "<em>Club no longer exists</em><br>" : "";
    marker.bindPopup(
      "<strong>" + club.name + "</strong><br>" + club.stadium + "<br>" + status +
      '<a href="../team/' + club.id + '/index.html">Club page →</a>'
    );
    marker.addTo(map);
    markers[club.id] = marker;
  });

  slider.addEventListener("input", refresh);

  // Wires up a single-select chip row: clicking a chip marks it active,
  // clears the others in the same row, and hands its value to onPick. Used
  // for both the story-filter row and the tier-filter row below.
  function wireChipGroup(selector, onPick) {
    var chips = document.querySelectorAll(selector);
    Array.prototype.forEach.call(chips, function (btn) {
      btn.addEventListener("click", function () {
        Array.prototype.forEach.call(chips, function (b) {
          b.classList.toggle("chip-active", b === btn);
        });
        onPick(btn);
        refresh();
      });
    });
  }

  wireChipGroup(".map-chips:not(.map-tier-chips) .chip", function (btn) {
    activeFilter = btn.getAttribute("data-filter");
  });
  wireChipGroup(".map-tier-chips .chip", function (btn) {
    activeTier = btn.getAttribute("data-tier");
  });

  // ── Postcode distances ────────────────────────────────────────────────
  function haversineMiles(lat1, lon1, lat2, lon2) {
    var R = 3958.8, toRad = Math.PI / 180;
    var dLat = (lat2 - lat1) * toRad, dLon = (lon2 - lon1) * toRad;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) *
      Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  document.getElementById("postcode-go").addEventListener("click", function () {
    var pc = document.getElementById("postcode-input").value.trim();
    if (!pc) return;
    fetch("https://api.postcodes.io/postcodes/" + encodeURIComponent(pc))
      .then(function (r) { return r.json(); })
      .then(function (json) {
        if (json.status !== 200) { alert("Postcode not found"); return; }
        var lat = json.result.latitude, lon = json.result.longitude;
        var rows = data.clubs.map(function (club) {
          return {club: club, miles: haversineMiles(lat, lon, club.lat, club.lon)};
        }).sort(function (a, b) { return a.miles - b.miles; });

        var table = document.getElementById("distance-table");
        table.innerHTML = "<tr><th>#</th><th>Club</th><th>Ground</th><th class='num'>Miles</th></tr>" +
          rows.map(function (r, i) {
            return "<tr><td class='num'>" + (i + 1) + "</td>" +
              "<td><a href='../team/" + r.club.id + "/index.html'>" + r.club.name + "</a></td>" +
              "<td>" + r.club.stadium + "</td>" +
              "<td class='num'>" + r.miles.toFixed(1) + "</td></tr>";
          }).join("");
        document.getElementById("postcode-label").textContent = json.result.postcode;
        document.getElementById("distance-panel").hidden = false;
        map.setView([lat, lon], 8);
      })
      .catch(function () { alert("Postcode lookup failed — check your connection"); });
  });

  refresh();
})();
