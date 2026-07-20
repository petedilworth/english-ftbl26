// Groundhop Map: Leaflet markers with a season slider, story filters,
// and postcode distances (postcodes.io, free and keyless).
// Expects window.MAP_DATA = {
//   years: [...], clubs: [{id, name, stadium, lat, lon, color, tier,
//     defunct, fallen, yoyo, everpresent, tiers: {"1994": 1, ...}}]
// }
(function () {
  var data = window.MAP_DATA;
  if (!data || typeof L === "undefined") return;

  var TIER_COLORS = {1: "#5e35b1", 2: "#1e88e5", 3: "#43a047", 4: "#fb8c00", 5: "#e53935"};
  var GHOST = "#9aa3ab";

  var map = L.map("map", {scrollWheelZoom: false}).setView([52.8, -1.7], 6);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 17,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(map);

  var slider = document.getElementById("year-slider");
  var yearLabel = document.getElementById("year-label");
  var activeFilter = "all";
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

  function refresh() {
    var year = String(slider.value);
    yearLabel.textContent = seasonLabel(Number(year));
    data.clubs.forEach(function (club) {
      var marker = markers[club.id];
      var tier = club.tiers[year];
      var visible = passesFilter(club);
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

  Array.prototype.forEach.call(document.querySelectorAll(".map-chips .chip"), function (btn) {
    btn.addEventListener("click", function () {
      activeFilter = btn.getAttribute("data-filter");
      Array.prototype.forEach.call(document.querySelectorAll(".map-chips .chip"), function (b) {
        b.classList.toggle("chip-active", b === btn);
      });
      refresh();
    });
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
