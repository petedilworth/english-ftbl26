/*
 * The allocation: a date of birth in, a club out, and a notice saying so.
 *
 * The arithmetic is in allocation-process.js, which is src/allocation.py
 * in another language; the rule and its reasons are written out there.
 * This file is the page around it: the three boxes, the notice, and the
 * things the notice lets a person do.
 *
 * THE DATE NEVER LEAVES THE DEVICE. Nothing here sends it anywhere, and
 * nothing here keeps it: the club is remembered in localStorage so the
 * header can show it, the date is not. What does leave is a request for
 * one season's results - /allocation/data/1987.json - so the host could
 * know the season someone was born in, and the form says so in plain
 * words rather than claiming that nothing is sent at all. A form on another page (the home
 * page) hands its date over in sessionStorage, which the browser drops
 * with the tab, and this page deletes it on reading. It is never put in
 * an address, because addresses get shared, logged and kept in history,
 * and a date of birth is half of what a bank asks for.
 *
 * SO THE SHARED LINK CARRIES THE CLUB, NOT THE DATE. Each club that can
 * be assigned has its own small page, /allocation/<club>/, with its own
 * preview card. Sharing a notice sends that address: the person receiving
 * it sees which club the sender got before they open anything, and never
 * learns when the sender was born.
 *
 * THE VOICE is docs/voice.md: dry, formal, and about the process rather
 * than the person. A date or club listed in content/straight-dates.yml
 * gets the same facts with none of it.
 */
(function () {
  "use strict";

  var P = window.allocationProcess;
  var form = document.getElementById("alloc-form");
  if (!form || !P) return;

  var ROOT = form.getAttribute("data-root") || ".";
  var INDEX_URL = form.getAttribute("data-index");
  var PYRAMID_URL = form.getAttribute("data-pyramid");
  var GO = form.getAttribute("data-go");            // set on the home page: run it over there
  var result = document.getElementById("alloc-result");
  var errorBox = form.querySelector(".alloc-error");
  var fields = {day: form.elements.day, month: form.elements.month, year: form.elements.year};
  var HANDOFF = "ais.dob", STORE = "ais.club";
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                "October", "November", "December"];
  var WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
               "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"];
  var TIMES = ["", "once", "twice"];

  function word(n) { return n >= 0 && n < WORDS.length ? WORDS[n] : String(n); }
  function times(n) { return TIMES[n] || word(n) + " times"; }
  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
  function ordinal(n) { var s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
  function count(n) { return n.toLocaleString("en-GB"); }
  function seasonLabel(y) { return (y - 1) + "/" + String(y % 100).padStart(2, "0"); }
  function theDivision(name) {
    return /^(League|Step|National League (North|South))/.test(name) ? name : "the " + name;
  }
  function longDate(iso) {
    var d = new Date(P.dayNumber(iso) * 86400000);
    return DAYS[d.getUTCDay()] + " " + d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] + " " + d.getUTCFullYear();
  }
  function shortDate(iso) {
    var d = new Date(P.dayNumber(iso) * 86400000);
    return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] + " " + d.getUTCFullYear();
  }
  function hex(c, fallback) { return typeof c === "string" && /^#[0-9a-f]{3,8}$/i.test(c) ? c : fallback; }
  // "Luton Town's" but "Doncaster Rovers'": half the league ends in an s.
  function possessive(name) { return name + (/s$/i.test(name) ? "'" : "'s"); }

  function el(tag, attrs, kids) {
    var node = document.createElement(tag), k;
    for (k in attrs || {}) {
      if (k === "text") node.textContent = attrs[k];
      else if (k === "class") node.className = attrs[k];
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) node.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function (kid) {
      if (kid == null) return;
      node.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
    });
    return node;
  }
  function svg(tag, attrs) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    return node;
  }

  // ── Loading ──────────────────────────────────────────────────────────

  function getJSON(url) {
    return fetch(url).then(function (r) { if (!r.ok) throw new Error(url + " " + r.status); return r.json(); });
  }
  var indexP = null, pyramidP = null;
  function warm() {
    indexP = indexP || getJSON(INDEX_URL);
    pyramidP = pyramidP || (window.pyramidData ? window.pyramidData(PYRAMID_URL) : getJSON(PYRAMID_URL));
    return Promise.all([indexP, pyramidP]);
  }
  // Start fetching when someone reaches for the form, not when they submit.
  if (!GO) form.addEventListener("focusin", warm, {once: true});

  // ── The record, as the notice needs it ───────────────────────────────

  function clubNumbers(pyr) {
    var out = {};
    pyr.clubs.forEach(function (c, i) { if (c[0]) out[c[0]] = i; });
    return out;
  }
  function namesOf(pyr) {
    var out = {};
    pyr.clubs.forEach(function (c) { if (c[0]) out[c[0]] = c[1]; });
    return out;
  }
  // One club's seasons: [{season, tier, rank, div, pos, kind}], oldest first.
  function historyOf(pyr, club) {
    var out = [], W = pyr.row;
    pyr.seasons.forEach(function (flat, offset) {
      for (var i = 0; i < flat.length; i += W) {
        if (flat[i] === club) {
          out.push({season: pyr.first + offset, tier: flat[i + 1], rank: flat[i + 2], div: flat[i + 3],
                    pos: flat[i + 4], kind: flat[i + 5]});
          break;
        }
      }
    });
    return out;
  }
  // Where a row stands in the whole pyramid that season, and how many
  // clubs the top four divisions held.
  function standing(pyr, row) {
    var flat = pyr.seasons[row.season - pyr.first], W = pyr.row, above = 0, league = 0;
    for (var i = 0; i < flat.length; i += W) {
      if (flat[i + 1] < row.tier) above++;
      if (flat[i + 1] <= 4) league++;
    }
    return {place: above + row.rank, league: league};
  }

  // Whether the straight-tone list (content/straight-dates.yml) covers
  // this date or this club: a dated entry applies on its anniversary, to
  // its clubs or to everyone; an undated one to its clubs on every date.
  function isStraight(index, iso, clubId) {
    return (index.straight || []).some(function (e) {
      var dateOk = !e.md || e.md === iso.slice(5);
      var clubOk = !e.clubs || !e.clubs.length || e.clubs.indexOf(clubId) !== -1;
      return dateOk && clubOk;
    });
  }

  // ── The form ─────────────────────────────────────────────────────────

  function fail(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function readDate() {
    var d = Number(fields.day.value), m = Number(fields.month.value), y = Number(fields.year.value);
    if (!fields.day.value || !fields.month.value || fields.year.value.length !== 4 || y < 1900) return null;
    return P.validDate(y, m, d);
  }

  // Two digits and the cursor moves on; backspace in an empty box moves
  // back. A whole date pasted or typed into the first box is taken apart.
  ["day", "month", "year"].forEach(function (name, i, all) {
    var input = fields[name];
    input.addEventListener("input", function () {
      var whole = input.value.match(/^\s*(\d{1,2})[\/.\- ](\d{1,2})[\/.\- ](\d{4})\s*$/);
      if (whole) {
        fields.day.value = whole[1]; fields.month.value = whole[2]; fields.year.value = whole[3];
        fields.year.focus();
        return;
      }
      input.value = input.value.replace(/\D/g, "").slice(0, name === "year" ? 4 : 2);
      errorBox.hidden = true;
      if (name !== "year" && input.value.length === 2 && all[i + 1]) fields[all[i + 1]].focus();
    });
    input.addEventListener("keydown", function (evt) {
      if (evt.key === "Backspace" && !input.value && i > 0) fields[all[i - 1]].focus();
      // Someone typing 14/3/1987 means the slash as "next box". Without
      // this it was thrown away and the 3 and the 1 became the 31st month.
      if (evt.key === "/" || evt.key === "." || evt.key === "-" || evt.key === " ") {
        evt.preventDefault();
        if (input.value && all[i + 1]) fields[all[i + 1]].focus();
      }
    });
  });

  form.addEventListener("submit", function (evt) {
    evt.preventDefault();
    var iso = readDate();
    if (!iso) return fail("That is not a date. The process requires one.");
    if (P.dayNumber(iso) > Math.floor(Date.now() / 86400000)) {
      return fail("That date has not happened yet. The process will wait.");
    }
    errorBox.hidden = true;
    if (GO) {
      // Another page does the work. The date crosses in sessionStorage,
      // never in the address.
      try { sessionStorage.setItem(HANDOFF, iso); } catch (e) { /* private mode: the other page will ask again */ }
      window.location.href = GO;
      return;
    }
    run(iso);
  });

  function run(iso) {
    form.classList.add("is-working");
    result.innerHTML = "";
    var steps = el("ol", {class: "alloc-steps"}, [el("li", {text: "Finding the table for " + longDate(iso) + "."})]);
    result.appendChild(steps);
    var started = Date.now();
    warm().then(function (got) {
      var index = got[0], pyr = got[1];
      var used = P.processDate(index, iso);
      return getJSON(INDEX_URL.replace(/index\.json$/, P.seasonFor(index, used) + ".json")).then(function (data) {
        var a = P.allocate(index, data, iso, namesOf(pyr));
        steps.appendChild(el("li", {text: "Counting " + count(a.day) + " days."}));
        steps.appendChild(el("li", {text: "Dividing by " + a.clubs + "."}));
        // Long enough to read three lines, and no longer: the wait is
        // theatre, and theatre that outstays its welcome is a spinner.
        var wait = reduced ? 0 : Math.max(0, 1100 - (Date.now() - started));
        setTimeout(function () { form.classList.remove("is-working"); show(index, pyr, data, a); }, wait);
      });
    }).catch(function () {
      form.classList.remove("is-working");
      result.innerHTML = "";
      fail("The record could not be loaded. Try again in a moment.");
    });
  }

  // ── The notice ───────────────────────────────────────────────────────

  function show(index, pyr, data, a) {
    var numbers = clubNumbers(pyr), ci = numbers[a.club], info = pyr.clubs[ci];
    var name = info[1], plain = isStraight(index, a.used, a.club);
    var history = historyOf(pyr, ci).filter(function (h) { return h.season >= data.season; });
    var latest = history.length && history[history.length - 1].season === pyr.last ? history[history.length - 1] : null;
    var lastSeen = history.length ? history[history.length - 1] : null;
    var afterSeason = data.complete && P.dayNumber(a.used) >= P.dayNumber(data.last);
    var newborn = data.season === pyr.last;
    var teamUrl = ROOT + "/team/" + a.club + "/index.html";
    var colourA = hex(info[2], "#8a929c"), colourB = hex(info[3], colourA);

    remember({id: a.club, name: name, a: colourA, b: colourB});

    var notice = el("article", {class: "notice" + (plain ? " is-plain" : ""), tabindex: "-1", "aria-label": "Notice of allocation"});
    notice.style.setProperty("--club-a", colourA);
    notice.style.setProperty("--club-b", colourB);
    notice.appendChild(el("div", {class: "notice-kit", "aria-hidden": "true"}, [el("span"), el("span")]));
    var stamp = plain ? null : el("span", {class: "notice-stamp", text: "Allocated"});

    // Who, and on what day.
    var born = a.standIn
      ? "Born " + longDate(a.born) + ", before the record begins. The process has used " + shortDate(a.used) +
        ", the same day in its first season."
      : "Born " + longDate(a.born) + ". Day " + count(a.day) + " of the record.";
    notice.appendChild(el("header", {class: "notice-head"}, [
      el("p", {class: "kicker", text: "Notice of allocation"}), stamp,
      el("p", {class: "notice-born", text: born})
    ]));
    notice.appendChild(el("div", {class: "notice-club"}, [
      el("p", {class: "notice-pre", text: "You have been assigned"}),
      el("h2", {class: "notice-name"}, [el("a", {href: teamUrl, text: name}), "."]),
      plain ? null : el("p", {class: "notice-rule", text: "There is no appeals process."})
    ]));

    // The day in question.
    var then = (afterSeason ? "The season had finished. They were " : "That evening they were ") +
               ordinal(a.position) + " in " + theDivision(a.division) + ", " + ordinal(a.place) + " of the " + a.clubs + ".";
    if (!plain && a.place === 1) then += " It is downhill from there, by definition.";
    if (!plain && a.place === a.clubs) then += " The only way was up, by definition.";
    var number = data.clubs.indexOf(a.club), day = P.matchOn(data, a.used, number), played;
    if (day.match) {
      var m = day.match, opponent = namesOf(pyr)[m.opponent] || m.opponent, margin = m.f - m.a;
      var verb = margin > 0 ? "won" : margin < 0 ? "lost" : "drew";
      played = "They " + verb + " " + Math.max(m.f, m.a) + "–" + Math.min(m.f, m.a) + " " +
               (m.home ? "at home to " : "away to ") + opponent + " that day";
      if (plain) played += ".";
      else if (margin <= -4) played += ", which is noted.";
      else if (margin >= 4) played += ". The occasion was marked.";
      else played += ".";
    } else if (afterSeason && P.dayNumber(a.used) > P.dayNumber(data.last)) {
      played = "Nobody played that day: it was the close season.";
    } else {
      played = day.played ? "They did not play that day." : "No league match was played that day.";
    }
    notice.appendChild(section("The day in question", [el("p", {text: then}), el("p", {text: played})]));

    // Since then.
    if (!newborn && history.length > 1) {
      var ups = 0, downs = 0, topFlight = 0, titles = 0;
      history.forEach(function (h, i) {
        if (h.kind === 6) { if (h.tier === 1) topFlight++; return; }   // in progress: nothing decided
        if (h.tier === 1) topFlight++;
        if (h.kind === 1 && h.tier === 1) { if (!(i === 0 && afterSeason)) titles++; }
        else if (h.kind >= 1 && h.kind <= 3) ups++;
        else if (h.kind === 4 || h.kind === 5) downs++;
      });
      var moved = ups && downs ? "Promoted " + times(ups) + ", relegated " + times(downs) + "."
        : ups ? "Promoted " + times(ups) + " and never relegated."
        : downs ? "Relegated " + times(downs) + " and never promoted."
        : "Neither promoted nor relegated in all that time.";
      var extra = [];
      if (titles) extra.push("Champions of England " + times(titles) + ".");
      if (topFlight && topFlight !== history.length) {
        extra.push("In the top flight for " + word(topFlight) + " season" + (topFlight === 1 ? "" : "s") + ".");
      }
      if (topFlight && topFlight === history.length) extra.push("In the top flight throughout.");
      notice.appendChild(section("Since then", [
        staircase(pyr, history, data.season),
        el("p", {text: moved + (extra.length ? " " + extra.join(" ") : "")})
      ]));
    }

    // As it stands.
    var nowText, verdict = "";
    if (latest) {
      var st = standing(pyr, latest), division = pyr.divisions[latest.div];
      nowText = cap(ordinal(latest.pos)) + " in " + theDivision(division) +
                (latest.tier <= 4 ? ", " + ordinal(st.place) + " of the " + st.league + "." : ", outside the ninety-two.");
      var gap = latest.tier - a.tier, moves = 0;
      history.forEach(function (h) { if (h.kind >= 1 && h.kind <= 5 && !(h.kind === 1 && h.tier === 1)) moves++; });
      // Someone born before the record was not born on the day the
      // process used, so the comparison is with "that day", not theirs.
      var than = a.standIn ? "on that day" : "the day you were born";
      var size = cap(word(Math.abs(gap))) + " division" + (Math.abs(gap) === 1 ? "" : "s");
      if (newborn) verdict = "Nothing has happened yet. It will.";
      else if (gap > 0) verdict = size + " lower than " + than + ". No connection is alleged.";
      else if (gap < 0) verdict = size + " higher than " + than + ". No credit is due.";
      else if (!moves) verdict = "The same division as " + than + ", and every season since.";
      else verdict = "The same division as " + than + ". It took " + word(moves) + " changes of division to get there.";
      if (plain) verdict = gap > 0 ? size + " lower than on that day."
        : gap < 0 ? size + " higher than on that day." : "The same division as on that day.";
    } else if (lastSeen) {
      nowText = (info[4] === 0 ? "The club no longer exists. " : "Not in the record this season. ") + "Last seen " +
                ordinal(lastSeen.pos) + " in " + theDivision(pyr.divisions[lastSeen.div]) + ", " + seasonLabel(lastSeen.season) + ".";
      verdict = plain ? "" : "The allocation stands.";
    } else {
      nowText = "Not in the record this season.";
    }
    notice.appendChild(section("As it stands", [el("p", {text: nowText}), verdict ? el("p", {class: "notice-verdict", text: verdict}) : null]));

    // What can be done about it.
    var outcome = el("p", {class: "notice-outcome", role: "status"});
    var share = el("button", {class: "btn btn-primary", type: "button", text: "Share the notice"});
    share.addEventListener("click", function () { shareNotice(a.club, name, plain, outcome); });
    var actions = [share];
    if (!plain) {
      var appeal = el("button", {class: "btn", type: "button", text: "Lodge an appeal"});
      var appeals = 0;
      appeal.addEventListener("click", function () {
        appeal.disabled = true;
        outcome.textContent = "The appeal is being considered.";
        setTimeout(function () {
          appeals++;
          appeal.disabled = false;
          if (appeals === 1) {
            outcome.textContent = "The appeal has been considered. The allocation stands.";
            stamp.textContent = "Appeal dismissed"; stamp.classList.add("is-dismissed");
            appeal.textContent = "Appeal again";
          } else if (appeals === 2) {
            outcome.textContent = "A second appeal has been received. It has been filed.";
          } else {
            outcome.textContent = "The file is closed.";
            appeal.hidden = true;
          }
        }, reduced ? 0 : 1300);
      });
      actions.push(appeal);
    }
    notice.appendChild(el("div", {class: "notice-actions"}, actions));
    notice.appendChild(outcome);
    notice.appendChild(el("p", {class: "notice-links"}, [
      el("a", {href: teamUrl, text: possessive(name) + " full record →"}), " ",
      el("a", {href: ROOT + "/replay/index.html#c=" + a.club + "&y=" + data.season, text: "Watch it happen →"})
    ]));

    notice.appendChild(leagueThatDay(pyr, data, a, afterSeason));
    notice.appendChild(working(index, a, name, afterSeason));

    result.innerHTML = "";
    result.appendChild(notice);
    // Focus goes to the notice, for a keyboard or a screen reader; the
    // scroll is done separately so it can be smooth.
    notice.focus({preventScroll: true});
    var noticeTop = result.getBoundingClientRect().top + window.pageYOffset - 12;
    window.scrollTo({top: noticeTop, behavior: reduced ? "auto" : "smooth"});
  }

  function section(title, kids) {
    return el("section", {class: "notice-section"}, [el("h3", {text: title})].concat(kids));
  }

  // The club's tiers from the birth season to now: one step a division,
  // a dot where the visitor arrived and a dot where things stand.
  function staircase(pyr, history, from) {
    var W = 320, H = 86, left = 16, right = 8, top = 8, bottom = 18;
    var span = Math.max(1, pyr.last - from), deepest = 3;
    history.forEach(function (h) { deepest = Math.max(deepest, h.tier); });
    function x(s) { return left + (s - from) / span * (W - left - right); }
    function y(t) { return top + (t - 1) / (deepest - 1) * (H - top - bottom); }
    var root = svg("svg", {viewBox: "0 0 " + W + " " + H, class: "notice-stairs", role: "img",
                           "aria-label": "Their division each season from " + seasonLabel(from) + " to " + seasonLabel(pyr.last)});
    for (var t = 1; t <= deepest; t++) {
      root.appendChild(svg("line", {x1: left, y1: y(t), x2: W - right, y2: y(t), class: "stairs-grid"}));
      var label = svg("text", {x: left - 5, y: y(t) + 3, "text-anchor": "end", class: "stairs-label"});
      label.textContent = t;
      root.appendChild(label);
    }
    var d = "", prev = null, half = (W - left - right) / span / 2;
    history.forEach(function (h) {
      var x0 = Math.max(left, x(h.season) - half), x1 = Math.min(W - right, x(h.season) + half);
      d += (prev !== null && prev === h.season - 1 ? "L" : "M") + x0.toFixed(1) + " " + y(h.tier).toFixed(1) +
           "L" + x1.toFixed(1) + " " + y(h.tier).toFixed(1);
      prev = h.season;
    });
    root.appendChild(svg("path", {d: d, class: "stairs-line"}));
    var a = history[0], b = history[history.length - 1];
    root.appendChild(svg("circle", {cx: x(a.season), cy: y(a.tier), r: 3.5, class: "stairs-start"}));
    root.appendChild(svg("circle", {cx: Math.min(W - right, x(b.season)), cy: y(b.tier), r: 3.5, class: "stairs-end"}));
    var l0 = svg("text", {x: left, y: H - 3, class: "stairs-label"}); l0.textContent = seasonLabel(from);
    var l1 = svg("text", {x: W - right, y: H - 3, "text-anchor": "end", class: "stairs-label"}); l1.textContent = seasonLabel(pyr.last);
    root.appendChild(l0); root.appendChild(l1);
    return root;
  }

  // The four tables the place was counted down, the assigned club marked.
  function leagueThatDay(pyr, data, a, afterSeason) {
    var names = namesOf(pyr), place = 0;
    var body = el("div", {class: "notice-tables"});
    a.table.forEach(function (division) {
      var table = el("table", {class: "standings notice-table"});
      table.appendChild(el("tr", {}, [el("th", {text: "#"}), el("th", {text: division.division}),
                                      el("th", {class: "num", text: "P"}), el("th", {class: "num", text: "Pts"})]));
      division.rows.forEach(function (r) {
        place++;
        var id = data.clubs[r.club], mine = id === a.club;
        var cell = el("td", {}, [el("a", {href: ROOT + "/team/" + id + "/index.html", text: names[id] || id})]);
        table.appendChild(el("tr", {class: mine ? "is-mine" : null}, [
          el("td", {class: "num", text: r.position}), cell,
          el("td", {class: "num", text: r.played}), el("td", {class: "num", text: r.points})
        ]));
      });
      body.appendChild(table);
    });
    var note = afterSeason
      ? "The final tables of " + seasonLabel(data.season) + ", as recorded."
      : "Results up to the end of that day, ranked by that season's rules. Points deducted that season are applied when it ends, so a club may sit higher here than it finished.";
    return el("details", {class: "notice-more"}, [
      el("summary", {text: "The league that day"}),
      el("p", {class: "finance-note", text: note}), body
    ]);
  }

  function working(index, a, name, afterSeason) {
    var remainder = a.day % a.clubs;
    return el("details", {class: "notice-more"}, [
      el("summary", {text: "The working"}),
      el("ol", {class: "notice-working"}, [
        el("li", {text: "The record begins on " + shortDate(index.epoch) + ". " + shortDate(a.used) + " is " +
                        count(a.day) + " day" + (a.day === 1 ? "" : "s") + " later."}),
        el("li", {text: a.clubs + " clubs were in the top four divisions. " + count(a.day) + " divided by " + a.clubs +
                        " leaves " + remainder + "."}),
        el("li", {text: "Counting from nought at the top of the table, " + remainder + " is " + ordinal(a.place) +
                        " place. " + (afterSeason ? "In the final table it was " : "That evening it was ") + name + "."}),
        el("li", {text: "Everyone born that day gets the same club. The date did not leave this device."})
      ])
    ]);
  }

  // ── Sharing, and remembering ─────────────────────────────────────────

  function shareNotice(clubId, name, plain, outcome) {
    // The club's own page: its preview card names the club, and the
    // address says nothing about the date.
    var url = new URL(ROOT + "/allocation/" + clubId + "/", window.location.href).href;
    var text = "I have been assigned " + name + "." + (plain ? "" : " There is no appeals process.");
    if (navigator.share) {
      navigator.share({title: "Notice of allocation", text: text, url: url}).catch(function () { /* closed the sheet */ });
      return;
    }
    var line = text + " " + url;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(line).then(function () { outcome.textContent = "Copied. Paste it where it will be seen."; },
                                                function () { outcome.textContent = line; });
    } else {
      outcome.textContent = line;
    }
  }

  function remember(club) {
    try { localStorage.setItem(STORE, JSON.stringify(club)); } catch (e) { /* private mode */ }
    if (window.applyYourClub) window.applyYourClub();
  }

  // ── On arrival ───────────────────────────────────────────────────────

  if (!GO) {
    var handed = null;
    try { handed = sessionStorage.getItem(HANDOFF); sessionStorage.removeItem(HANDOFF); } catch (e) { handed = null; }
    if (handed && /^\d{4}-\d{2}-\d{2}$/.test(handed)) {
      fields.day.value = Number(handed.slice(8)); fields.month.value = Number(handed.slice(5, 7)); fields.year.value = handed.slice(0, 4);
      run(handed);
    } else {
      onFile();
    }
  }

  // Someone who has been here before: the club is on file, the date is
  // not, so the notice cannot be shown again without it. Say which club,
  // and where it stands.
  function onFile() {
    var club = null;
    try { club = JSON.parse(localStorage.getItem(STORE) || "null"); } catch (e) { club = null; }
    if (!club || !/^[a-z0-9-]{1,80}$/.test(club.id || "")) return;
    warm().then(function (got) {
      var pyr = got[1], ci = clubNumbers(pyr)[club.id];
      if (ci === undefined || result.firstChild) return;
      var history = historyOf(pyr, ci), last = history[history.length - 1];
      var where = last && last.season === pyr.last
        ? "As it stands: " + ordinal(last.pos) + " in " + theDivision(pyr.divisions[last.div]) + "."
        : "Not in the record this season.";
      result.appendChild(el("p", {class: "alloc-onfile"}, [
        "On file for this device: ",
        el("a", {href: ROOT + "/team/" + club.id + "/index.html", text: pyr.clubs[ci][1]}),
        ". " + where + " Give the date again to see the notice."
      ]));
    }).catch(function () { /* the form still works */ });
  }
})();
