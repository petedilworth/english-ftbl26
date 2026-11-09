/*
 * The allocation's arithmetic, and nothing else: no page, no network.
 *
 * This is src/allocation.py again, in the language the browser runs. The
 * rule and its reasons are written out there; the two are held together
 * by tests/test_allocation.py, which runs this file under Node against
 * the Python for the same dates and fails if they disagree about a single
 * club. It is a separate file from the page's script so that it can be
 * loaded by that test without a page to load it into.
 *
 * Dates are ISO strings, "1987-03-14", in and out. They are turned into
 * whole days since 1970 in UTC and never into local time: a date of birth
 * has no time zone, and a visitor in Vancouver must get the same club as
 * one in Burnley.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.allocationProcess = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function dayNumber(iso) {
    var p = String(iso).slice(0, 10).split("-");
    return Math.round(Date.UTC(Number(p[0]), Number(p[1]) - 1, Number(p[2])) / 86400000);
  }

  function isoOf(day) {
    return new Date(day * 86400000).toISOString().slice(0, 10);
  }

  // A real calendar date, or null: 31 June and 29 February 1987 are not.
  function validDate(year, month, day) {
    if (!(year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= 31)) return null;
    var d = new Date(Date.UTC(year, month - 1, day));
    d.setUTCFullYear(year);   // two-digit years are not the 1900s
    if (d.getUTCMonth() !== month - 1 || d.getUTCDate() !== day) return null;
    return d.toISOString().slice(0, 10);
  }

  // The season a date belongs to: the last one that had started by then.
  function seasonFor(index, iso) {
    var day = dayNumber(iso), found = null;
    for (var i = 0; i < index.seasons.length; i++) {
      if (dayNumber(index.seasons[i][1]) <= day) found = index.seasons[i][0]; else break;
    }
    return found;
  }

  // For a birth before the record: the same day of the year in its first
  // season. 29 February has no such day in 1959 and takes the 28th.
  function standIn(index, iso) {
    var epoch = dayNumber(index.epoch), p = iso.split("-");
    var month = Number(p[1]), startYear = Number(index.epoch.slice(0, 4));
    for (var year = startYear; year <= startYear + 1; year++) {
      var day = Number(p[2]), candidate = null;
      while (day > 0 && !(candidate = validDate(year, month, day))) day--;
      if (candidate && dayNumber(candidate) >= epoch) return candidate;
    }
    return index.epoch;
  }

  // The date the process uses: the birth date, held inside the record.
  function processDate(index, born) {
    if (dayNumber(born) < dayNumber(index.epoch)) return standIn(index, born);
    return dayNumber(born) > dayNumber(index.latest) ? index.latest : born;
  }

  function sortKey(code, r) {
    if (code === "ga") return [r.points, r.gf / (r.ga || 1), r.gf];
    if (code === "gs") return [r.points, r.gf, r.gf - r.ga];
    return [r.points, r.gf - r.ga, r.gf];
  }

  // The top four divisions as they stood at the end of `iso`:
  // [{tier, division, final, rows: [{club, position, played, ...}]}].
  // `names` maps a club id to its name, for the order of clubs the rules
  // cannot separate.
  function table(data, iso, names) {
    names = names || {};
    var day = dayNumber(iso) - dayNumber(data.first);
    var useFinal = !!(data.complete && data.final && dayNumber(iso) >= dayNumber(data.last));
    var n = data.clubs.length, stats = [], tierOf = [], i, t;
    for (i = 0; i < n; i++) stats.push({club: i, played: 0, won: 0, drawn: 0, lost: 0, gf: 0, ga: 0, points: 0});
    for (t = 0; t < data.sizes.length; t++) for (i = 0; i < data.sizes[t]; i++) tierOf.push(t);

    if (useFinal) {
      for (i = 0; i < n; i++) {
        var f = data.final[i];
        stats[i].played = f[0]; stats[i].won = f[1]; stats[i].drawn = f[2]; stats[i].lost = f[3];
        stats[i].gf = f[4]; stats[i].ga = f[5]; stats[i].points = f[6];
      }
    } else {
      var m = data.m;
      for (var k = 0; k < m.length; k += 5) {
        if (m[k] > day) break;   // matches are in date order
        var home = m[k + 1], away = m[k + 2], hg = m[k + 3], ag = m[k + 4];
        var rule = data.rules[tierOf[home]], h = stats[home], a = stats[away];
        h.played++; a.played++;
        h.gf += hg; h.ga += ag; a.gf += ag; a.ga += hg;
        if (hg > ag) { h.won++; a.lost++; h.points += rule[0]; }
        else if (hg < ag) { a.won++; h.lost++; a.points += rule[1]; }
        else { h.drawn++; a.drawn++; h.points += rule[2]; a.points += rule[2]; }
      }
    }

    function nameOf(r) { var id = data.clubs[r.club]; return names[id] || id; }
    var out = [], start = 0;
    for (t = 0; t < data.sizes.length; t++) {
      var members = stats.slice(start, start + data.sizes[t]);
      if (!useFinal) {
        var code = data.rules[t][3];
        // Name order first, then a stable sort on the ranking, exactly as
        // the Python does it: clubs the rules cannot separate stay
        // alphabetical. Plain comparison, not localeCompare, for the same
        // reason - two machines must not disagree about an ampersand.
        members.sort(function (x, y) { var p = nameOf(x), q = nameOf(y); return p < q ? -1 : p > q ? 1 : 0; });
        members.sort(function (x, y) {
          var p = sortKey(code, x), q = sortKey(code, y);
          for (var j = 0; j < p.length; j++) if (p[j] !== q[j]) return q[j] - p[j];
          return 0;
        });
      }
      members.forEach(function (r, j) { r.position = j + 1; });
      out.push({tier: data.tiers[t], division: data.divisions[t], final: useFinal, rows: members});
      start += data.sizes[t];
    }
    return out;
  }

  // The club for a date of birth, with the working. `data` is the season
  // file for processDate(index, born).
  function allocate(index, data, born, names) {
    var used = processDate(index, born);
    var divisions = table(data, used, names), order = [];
    divisions.forEach(function (d) { d.rows.forEach(function (r) { order.push([d, r]); }); });
    var day = dayNumber(used) - dayNumber(index.epoch);
    var place = day % order.length;
    var division = order[place][0], row = order[place][1];
    return {
      born: born, used: used, standIn: used !== born && dayNumber(born) < dayNumber(index.epoch),
      day: day, clubs: order.length, place: place + 1,
      club: data.clubs[row.club], tier: division.tier, division: division.division,
      position: row.position, row: row, table: divisions
    };
  }

  // What the club did on the day itself, if it played: {home, opponent, f, a}.
  function matchOn(data, iso, clubNumber) {
    var day = dayNumber(iso) - dayNumber(data.first), m = data.m, played = 0, mine = null;
    for (var k = 0; k < m.length; k += 5) {
      if (m[k] > day) break;
      if (m[k] !== day) continue;
      played++;
      if (m[k + 1] === clubNumber) mine = {home: true, opponent: data.clubs[m[k + 2]], f: m[k + 3], a: m[k + 4]};
      if (m[k + 2] === clubNumber) mine = {home: false, opponent: data.clubs[m[k + 1]], f: m[k + 4], a: m[k + 3]};
    }
    return {played: played, match: mine};
  }

  return {
    dayNumber: dayNumber, isoOf: isoOf, validDate: validDate, seasonFor: seasonFor, standIn: standIn,
    processDate: processDate, table: table, allocate: allocate, matchOn: matchOn
  };
});
