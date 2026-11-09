/*
 * The Replay: every club in the record as a bead in its kit colours, moved
 * through every season it has a row for.
 *
 * WHAT IS ON THE CANVAS. A band per tier, top flight first. Inside a band
 * the clubs sit in table order, first place on the left, twenty-four to a
 * row; a tier several divisions wide is laid out on its rank across the
 * whole tier, as the Matrix does. Between two seasons every bead travels
 * from its old place to its new one, so a promotion is a bead leaving the
 * left end of one band for the right end of the band above, and the three
 * that pass it going down are the price.
 *
 * WHY A CANVAS. Two hundred and seventy elements animating at once is
 * what a canvas is for, and a phone has to play this smoothly or it is
 * not worth having. The cost is that nothing drawn here exists for a
 * screen reader, so the controls are real buttons, the season and the
 * caption are real text, and the Matrix page is the same record as a
 * table - the page says so.
 *
 * Expects data/pyramid.json as src/pyramid.py writes it:
 *   {first, last, live, row, kinds, tiers, bands, since, divisions,
 *    clubs: [[id, name, colourA, colourB, tierNow]], seasons: [[flat rows]]}
 * with each row being club, tier, rank, division, position, kind.
 *
 * FOLLOWING A CLUB. Tap a bead and the rest fade. The club's whole record
 * is then drawn as a line above the slider - up is up, one step a tier -
 * so the slider becomes a map of that club's life and the falls can be
 * found without sitting through the plateaus. It was first drawn on the
 * pyramid itself, joining every place the club had stood; league position
 * moves sideways every season, and the result was a cat's cradle.
 *
 * THE OPENING. The page shows the present day, then winds back to the
 * first season before it plays: the full pyramid is the picture worth
 * opening on, and 1958/59 is four rows of it.
 *
 * Markup, all optional data attributes on .replay:
 *   data-src      where pyramid.json is
 *   data-follow   a club id to follow from the start
 *   data-from     the season (by the year it ended) to start at
 *   data-hash     keep the followed club and the season in the URL
 *   data-loop     start again a few seconds after reaching the present
 *   data-yours    follow the club the allocation assigned this visitor,
 *                 if it has assigned one and nothing else was asked for
 */
(function () {
  "use strict";

  var COLS = 24;            // the widest single division
  var HOLD = 0.32;          // share of each season spent standing still
  var SPEEDS = [2.2, 4.4, 1.1];   // seasons a second: normal, fast, slow
  var SPEED_LABELS = ["1×", "2×", "½×"];
  var KIND_WORDS = ["", ", champions", ", promoted", ", promoted through the play-offs",
                    ", relegated", ", relegated through the play-offs", " so far"];

  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function seasonLabel(y) { return (y - 1) + "/" + String(y % 100).padStart(2, "0"); }
  function ordinal(n) { var s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
  function theDivision(name) {
    // "the Premier League" but bare "League One", as the rest of the site says it.
    return /^(League|Step|National League (North|South))/.test(name) ? name : "the " + name;
  }
  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  function ease(x) { return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; }
  function hex(c, fallback) { return typeof c === "string" && /^#[0-9a-f]{3,8}$/i.test(c) ? c : fallback; }

  // ── The record, turned into places on a grid ─────────────────────────

  function prepare(data) {
    var W = data.row, n = data.seasons.length;
    // How many rows each tier's band needs, from its fullest season, so a
    // band never changes height while the years run.
    var most = {};
    data.seasons.forEach(function (flat) {
      var count = {};
      for (var i = 0; i < flat.length; i += W) count[flat[i + 1]] = (count[flat[i + 1]] || 0) + 1;
      Object.keys(count).forEach(function (t) { most[t] = Math.max(most[t] || 0, count[t]); });
    });
    var bands = data.tiers.map(function (t) {
      return {tier: t, rows: Math.max(1, Math.ceil((most[t] || 1) / COLS)), since: data.since[String(t)]};
    });
    var bandOf = {};
    bands.forEach(function (b, i) { bandOf[b.tier] = i; });

    // slots[season][club] = {tier, band, row, col, rank, div, pos, kind}
    var slots = [], tops = [];
    data.seasons.forEach(function (flat) {
      var byTier = {}, i;
      for (i = 0; i < flat.length; i += W) (byTier[flat[i + 1]] = byTier[flat[i + 1]] || []).push(i);
      var here = {}, top = null;
      Object.keys(byTier).forEach(function (t) {
        var list = byTier[t];   // already in rank order: the file is written that way
        list.forEach(function (at, k) {
          var row = Math.floor(k / COLS);
          var inRow = Math.min(COLS, list.length - row * COLS);
          here[flat[at]] = {
            tier: Number(t), band: bandOf[t], row: row, col: (COLS - inRow) / 2 + (k % COLS),
            rank: flat[at + 2], div: flat[at + 3], pos: flat[at + 4], kind: flat[at + 5]
          };
          if (Number(t) === data.tiers[0] && k === 0) top = flat[at];
        });
      });
      slots.push(here);
      tops.push(top);
    });
    return {n: n, bands: bands, slots: slots, tops: tops};
  }

  function bandName(data, tier, season) {
    var changes = data.bands[String(tier)] || [], name = "";
    for (var i = 0; i < changes.length; i++) if (changes[i][0] <= season) name = changes[i][1];
    return name;
  }

  // ── One replay ───────────────────────────────────────────────────────

  function Replay(root, data) {
    var prep = prepare(data);
    var canvas = root.querySelector(".replay-canvas");
    var ctx = canvas.getContext("2d");
    var elSeason = root.querySelector(".replay-year");
    var elCaption = root.querySelector(".replay-caption");
    var elPlay = root.querySelector(".replay-play");
    var elScrub = root.querySelector(".replay-scrub");
    var elSpeed = root.querySelector(".replay-speed");
    var elFind = root.querySelector(".replay-find");
    var elList = root.querySelector(".replay-clubs");
    var elClear = root.querySelector(".replay-clear");
    var elLink = root.querySelector(".replay-club-link");
    var strip = root.querySelector(".replay-strip");
    var sctx = strip ? strip.getContext("2d") : null;
    var elHint = root.querySelector(".replay-hint");
    var useHash = root.hasAttribute("data-hash") && window.hashState;
    var loop = root.hasAttribute("data-loop");
    var pageRoot = root.getAttribute("data-root") || ".";

    var css = getComputedStyle(document.documentElement);
    function token(name, fallback) { return (css.getPropertyValue(name) || "").trim() || fallback; }
    var INK = token("--ink", "#15181c"), MUTED = token("--muted", "#5d6672"), PAPER = token("--bg", "#fbf9f4"),
        LINE = token("--line", "#e6e1d6"), UP = token("--up", "#1a7f3c"), DOWN = token("--down", "#b3261e"),
        SANS = token("--sans", "sans-serif");

    var byId = {}, byName = {};
    data.clubs.forEach(function (c, i) { if (c[0]) byId[c[0]] = i; byName[c[1].toLowerCase()] = i; });

    var geo = null;          // pixel geometry, rebuilt on resize
    var t = 0;               // the playhead: season index, fractional while moving
    var playing = false, speed = 0, follow = -1, hover = -1;
    var last = 0, raf = 0, shown = -1, touched = false, autoPaused = false, loopTimer = 0;
    var visible = true;      // on screen enough to be worth animating; kept by the observer below
    var intro = null;        // {from, to, start}: the wind back from the present, before it plays
    var explicit = root.hasAttribute("data-from") || root.hasAttribute("data-follow");

    // Where to begin: an address in the URL beats the markup's defaults.
    var fromSeason = Number(root.getAttribute("data-from")) || data.first;
    var startFollow = root.getAttribute("data-follow");
    if (useHash) {
      if (window.hashState.get("c")) { startFollow = window.hashState.get("c"); explicit = true; }
      if (window.hashState.get("y")) { fromSeason = Number(window.hashState.get("y")) || fromSeason; explicit = true; }
    }
    var startIndex = clamp(fromSeason - data.first, 0, prep.n - 1);
    t = startIndex;
    if (!startFollow && root.hasAttribute("data-yours")) {
      // The allocation page keeps the club it assigned (never the date).
      // Shared storage is not trusted: the id has to be one of ours.
      try {
        var yours = JSON.parse(localStorage.getItem("ais.club") || "null");
        if (yours && byId[yours.id] !== undefined) startFollow = yours.id;
      } catch (e) { /* private mode, or not JSON */ }
    }
    if (startFollow && byId[startFollow] !== undefined) follow = byId[startFollow];

    if (elList) {
      data.clubs.map(function (c) { return c[1]; }).sort().forEach(function (name) {
        var o = document.createElement("option"); o.value = name; elList.appendChild(o);
      });
    }
    if (elScrub) { elScrub.min = 0; elScrub.max = prep.n - 1; elScrub.step = 1; elScrub.value = Math.round(t); }

    // ── Geometry ───────────────────────────────────────────────────────

    function measure() {
      var width = Math.max(240, Math.floor(canvas.clientWidth || root.clientWidth || 320));
      var pad = 4;
      var pitch = Math.min(26, (width - 2 * pad) / COLS);
      var pitchY = pitch * 1.06;
      var label = 15, gap = Math.max(5, pitch * 0.42);
      var left = (width - COLS * pitch) / 2;
      var y = 2, tops = [];
      prep.bands.forEach(function (b) {
        tops.push(y);
        y += label + b.rows * pitchY + gap;
      });
      geo = {width: width, height: Math.ceil(y), pitch: pitch, pitchY: pitchY, label: label, left: left,
             tops: tops, r: pitch * 0.39};
      var dpr = Math.min(window.devicePixelRatio || 1, 3);
      canvas.width = Math.round(geo.width * dpr);
      canvas.height = Math.round(geo.height * dpr);
      canvas.style.height = geo.height + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (strip) {
        geo.stripW = Math.max(60, Math.floor(strip.clientWidth));
        geo.stripH = Math.max(20, Math.floor(strip.clientHeight));
        strip.width = Math.round(geo.stripW * dpr);
        strip.height = Math.round(geo.stripH * dpr);
        sctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
    }

    function place(slot) {
      return {
        x: geo.left + (slot.col + 0.5) * geo.pitch,
        y: geo.tops[slot.band] + geo.label + (slot.row + 0.5) * geo.pitchY
      };
    }

    // Where a club is at the playhead: between its place in the season
    // just gone and its place in the one arriving. A club with no row on
    // one side fades in from below, or out downwards - the bottom of the
    // record is where clubs come from and go to.
    function at(club, i0, i1, move) {
      var a = prep.slots[i0][club], b = prep.slots[i1][club];
      if (!a && !b) return null;
      var pa = a && place(a), pb = b && place(b), drop = geo.pitch * 1.4;
      if (a && b) return {x: pa.x + (pb.x - pa.x) * move, y: pa.y + (pb.y - pa.y) * move, alpha: 1,
                          dir: b.tier < a.tier ? 1 : b.tier > a.tier ? -1 : 0};
      if (a) return {x: pa.x, y: pa.y + drop * move, alpha: 1 - move, dir: 0};
      return {x: pb.x, y: pb.y + drop * (1 - move), alpha: move, dir: 0};
    }

    // ── Drawing ────────────────────────────────────────────────────────

    function bead(x, y, r, a, b, alpha) {
      ctx.globalAlpha = alpha;
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = a; ctx.fill();
      if (b && b !== a) {
        ctx.beginPath(); ctx.arc(x, y, r, -Math.PI / 2, Math.PI / 2);
        ctx.fillStyle = b; ctx.fill();
      }
      // The outline is what keeps a white kit visible on paper.
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.lineWidth = 1; ctx.strokeStyle = "rgba(21,24,28,0.38)"; ctx.stroke();
      ctx.globalAlpha = 1;
    }

    function labelAt(x, y, text, strong) {
      ctx.font = (strong ? "700 " : "600 ") + (strong ? 13 : 12) + "px " + SANS;
      var w = ctx.measureText(text).width, gapX = geo.r * 2 + 6;
      var right = x + gapX + w < geo.width - 2;
      var tx = right ? x + gapX : x - gapX - w;
      tx = clamp(tx, 2, geo.width - w - 2);
      var ty = y + 4;
      // If there is no room beside the bead, sit above it.
      if (!right && x - gapX - w < 2) { tx = clamp(x - w / 2, 2, geo.width - w - 2); ty = y - geo.r * 2 - 6; }
      ctx.lineJoin = "round"; ctx.lineWidth = 4; ctx.strokeStyle = PAPER; ctx.strokeText(text, tx, ty);
      ctx.fillStyle = INK; ctx.fillText(text, tx, ty);
    }

    function draw() {
      if (!geo) measure();
      var i0 = Math.floor(clamp(t, 0, prep.n - 1)), i1 = Math.min(i0 + 1, prep.n - 1);
      var frac = t - i0;
      // Winding back there is no standing still: the seasons run together.
      var move = i1 === i0 ? 0 : intro ? frac : ease(clamp((frac - HOLD) / (1 - HOLD), 0, 1));
      var index = move < 0.5 ? i0 : i1;
      var season = data.first + index;

      ctx.clearRect(0, 0, geo.width, geo.height);

      // Bands: a rule, the tier's name that season, and a plain statement
      // where there is nothing to draw.
      ctx.textBaseline = "alphabetic";
      prep.bands.forEach(function (b, k) {
        var top = geo.tops[k];
        ctx.fillStyle = LINE;
        ctx.fillRect(geo.left, top + geo.label - 4, COLS * geo.pitch, 1);
        var name = bandName(data, b.tier, Math.max(season, b.since));
        ctx.font = "600 9.5px " + SANS;
        ctx.fillStyle = MUTED;
        var text = name.toUpperCase();
        if (ctx.letterSpacing !== undefined) ctx.letterSpacing = "0.8px";
        ctx.fillText(text, geo.left, top + geo.label - 8);
        if (ctx.letterSpacing !== undefined) ctx.letterSpacing = "0px";
        var empty = true, here = prep.slots[index];
        for (var c in here) if (here[c].band === k) { empty = false; break; }
        if (empty) {
          ctx.font = "italic 11px " + SANS;
          ctx.fillStyle = MUTED;
          var note = season < b.since ? "The record reaches this level from " + seasonLabel(b.since) + "."
                                      : "No table in the record this season.";
          ctx.fillText(note, geo.left, top + geo.label + geo.pitchY * 0.5 + 4);
        }
      });

      var dim = follow >= 0 ? 0.34 : 1;
      var movers = [], c, p, club;
      var seen = {};
      [i0, i1].forEach(function (i) { for (var k in prep.slots[i]) seen[k] = 1; });
      for (c in seen) {
        club = Number(c);
        if (club === follow) continue;
        p = at(club, i0, i1, move);
        if (!p) continue;
        if (p.dir && move > 0 && move < 1) { movers.push([club, p]); continue; }
        bead(p.x, p.y, geo.r, hex(data.clubs[club][2], "#b8bec6"), hex(data.clubs[club][3], null), p.alpha * dim);
      }
      // Clubs changing tier are drawn over the rest, ringed green or red
      // while they travel: the traffic between the bands is the story.
      movers.forEach(function (m) {
        var q = m[1], k = data.clubs[m[0]];
        bead(q.x, q.y, geo.r, hex(k[2], "#b8bec6"), hex(k[3], null), dim);
        ctx.globalAlpha = dim * Math.sin(Math.PI * move);
        ctx.beginPath(); ctx.arc(q.x, q.y, geo.r + 2.5, 0, Math.PI * 2);
        ctx.lineWidth = 2; ctx.strokeStyle = q.dir > 0 ? UP : DOWN; ctx.stroke();
        ctx.globalAlpha = 1;
      });

      if (follow >= 0) {
        var info = data.clubs[follow], colour = hex(info[2], INK);
        p = at(follow, i0, i1, move);
        if (p) {
          ctx.beginPath(); ctx.arc(p.x, p.y, geo.r * 1.75 + 3, 0, Math.PI * 2);
          ctx.fillStyle = PAPER; ctx.globalAlpha = p.alpha; ctx.fill(); ctx.globalAlpha = 1;
          bead(p.x, p.y, geo.r * 1.75, colour, hex(info[3], null), Math.max(0.15, p.alpha));
          ctx.beginPath(); ctx.arc(p.x, p.y, geo.r * 1.75 + 2.5, 0, Math.PI * 2);
          ctx.lineWidth = 1.5; ctx.strokeStyle = INK; ctx.globalAlpha = Math.max(0.15, p.alpha); ctx.stroke();
          ctx.globalAlpha = 1;
          labelAt(p.x, p.y, info[1], true);
        }
      }
      if (hover >= 0 && hover !== follow) {
        var hs = prep.slots[index][hover];
        if (hs) { var hp = place(hs); labelAt(hp.x, hp.y, data.clubs[hover][1] + " · " + ordinal(hs.pos), false); }
      }

      drawStrip(i0, i1, move);
      if (index !== shown) { shown = index; describe(index); }
    }

    // The followed club's record above the slider: a step for every tier,
    // the seasons already played in ink and the rest in grey, so the line
    // and the slider's thumb say the same thing.
    function drawStrip(i0, i1, move) {
      if (!sctx) return;
      var w = geo.stripW, h = geo.stripH;
      sctx.clearRect(0, 0, w, h);
      if (follow < 0) return;
      var inset = 10;   // roughly half a slider thumb: its travel stops short of the track's ends
      // Top of the strip is the top flight; the bottom is as far down as
      // this club has been, and never less than two tiers below the top,
      // so a club that has only ever moved one division still shows a step.
      var top = prep.bands[0].tier, deepest = top + 2;
      for (var k = 0; k < prep.n; k++) {
        if (prep.slots[k][follow]) deepest = Math.max(deepest, prep.slots[k][follow].tier);
      }
      function sx(i) { return inset + (prep.n > 1 ? i / (prep.n - 1) : 0) * (w - 2 * inset); }
      function sy(tier) { return 4 + (tier - top) / Math.max(1, deepest - top) * (h - 8); }
      var half = (w - 2 * inset) / Math.max(1, prep.n - 1) / 2;
      var now = sx(i0 + (i1 - i0) * move);
      function trace(limit, style, width) {
        sctx.save();
        sctx.beginPath(); sctx.rect(limit[0], 0, limit[1] - limit[0], h); sctx.clip();
        sctx.beginPath();
        var pen = false;
        for (var i = 0; i < prep.n; i++) {
          var sl = prep.slots[i][follow];
          if (!sl) { pen = false; continue; }
          var x0 = sx(i) - half, x1 = sx(i) + half, y = sy(sl.tier);
          if (pen) sctx.lineTo(x0, y); else sctx.moveTo(x0, y);
          sctx.lineTo(x1, y);
          pen = true;
        }
        sctx.lineWidth = width; sctx.lineJoin = "round"; sctx.strokeStyle = style; sctx.stroke();
        sctx.restore();
      }
      trace([now, w], "rgba(93,102,114,0.45)", 1.5);
      trace([0, now], INK, 2.25);
      var a = prep.slots[i0][follow], b = prep.slots[i1][follow];
      var tierNow = a && b ? a.tier + (b.tier - a.tier) * move : (a || b) ? (a || b).tier : null;
      if (tierNow != null) {
        sctx.beginPath(); sctx.arc(now, sy(tierNow), 4, 0, Math.PI * 2);
        sctx.fillStyle = token("--spot", "#d4401f"); sctx.fill();
        sctx.lineWidth = 1.5; sctx.strokeStyle = PAPER; sctx.stroke();
      }
    }

    // The season and the sentence under it, as text a person can select
    // and a screen reader can find.
    function describe(index) {
      var season = data.first + index;
      if (elSeason) elSeason.textContent = seasonLabel(season);
      if (elScrub && !elScrub.matches(":active")) elScrub.value = index;
      var text = "";
      if (follow >= 0) {
        var name = data.clubs[follow][1], s = prep.slots[index][follow];
        if (s) {
          text = name + ": " + ordinal(s.pos) + " in " + theDivision(data.divisions[s.div]) + KIND_WORDS[s.kind] + ".";
        } else {
          var before = true;
          for (var i = 0; i < index; i++) if (prep.slots[i][follow]) { before = false; break; }
          text = name + ": " + (before ? "not yet in the record." : "outside the record this season.");
        }
      } else if (prep.tops[index] != null) {
        var live = data.live && index === prep.n - 1;
        text = (live ? "Top of the table so far: " : "Champions: ") + data.clubs[prep.tops[index]][1] + ".";
      }
      if (elCaption) elCaption.textContent = text;
      canvas.setAttribute("aria-label", "The pyramid in " + seasonLabel(season) + ". " + text);
    }

    // ── Time ───────────────────────────────────────────────────────────

    function frame(now) {
      raf = 0;
      if (!playing) return;
      var dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      if (intro) {
        var done = clamp((now - intro.start) / 1400, 0, 1);
        t = intro.from + (intro.to - intro.from) * ease(done);
        if (done >= 1) { intro = null; t = startIndex; }
        draw();
        raf = requestAnimationFrame(frame);
        return;
      }
      t += dt * SPEEDS[speed];
      if (t >= prep.n - 1) {
        t = prep.n - 1; draw(); setPlaying(false);
        // Again, but only for someone still looking; otherwise when they come back.
        if (loop && !touched) loopTimer = setTimeout(function () { if (visible) setPlaying(true); else autoPaused = true; }, 6000);
        return;
      }
      draw();
      raf = requestAnimationFrame(frame);
    }

    function setPlaying(on) {
      clearTimeout(loopTimer);
      // Play pressed at the end: wind back to where it began, then run.
      if (on && !intro && t >= prep.n - 1) {
        if (startIndex >= prep.n - 1) startIndex = 0;
        if (reduced) t = startIndex;
        else intro = {from: prep.n - 1, to: startIndex, start: performance.now()};
      }
      playing = on;
      root.classList.toggle("is-playing", on);
      if (elPlay) {
        elPlay.setAttribute("aria-label", on ? "Pause" : (t >= prep.n - 1 ? "Play again" : "Play"));
        elPlay.setAttribute("aria-pressed", on ? "true" : "false");
      }
      if (on && !raf) { last = performance.now(); raf = requestAnimationFrame(frame); }
      if (!on) { intro = null; t = Math.round(t); draw(); remember(); }
    }

    function remember() {
      // Only once someone has touched it: opening the page should not
      // rewrite its own address.
      if (!useHash || !touched) return;
      window.hashState.set("c", follow >= 0 && data.clubs[follow][0] ? data.clubs[follow][0] : null);
      window.hashState.set("y", data.first + Math.round(t));
    }

    function setFollow(club) {
      follow = club;
      shown = -1;
      root.classList.toggle("is-following", follow >= 0);
      if (elClear) elClear.hidden = follow < 0;
      if (elHint) elHint.hidden = follow >= 0;
      if (elLink) {
        var id = follow >= 0 ? data.clubs[follow][0] : null;
        elLink.hidden = !id;
        if (id) {
          var named = data.clubs[follow][1];
          elLink.href = pageRoot + "/team/" + id + "/index.html";
          elLink.textContent = named + (/s$/i.test(named) ? "'" : "'s") + " full record →";
        }
      }
      if (elFind && follow >= 0) elFind.value = data.clubs[follow][1];
      if (elFind && follow < 0) elFind.value = "";
      draw();
      if (!playing) remember();
    }

    // ── Controls ───────────────────────────────────────────────────────

    function nearest(evt) {
      var box = canvas.getBoundingClientRect();
      var x = evt.clientX - box.left, y = evt.clientY - box.top;
      var here = prep.slots[Math.round(clamp(t, 0, prep.n - 1))], best = -1, bestD = Math.pow(geo.pitch * 0.9, 2);
      for (var c in here) {
        var p = place(here[c]), d = (p.x - x) * (p.x - x) + (p.y - y) * (p.y - y);
        if (d < bestD) { bestD = d; best = Number(c); }
      }
      return best;
    }

    canvas.addEventListener("click", function (evt) {
      touched = true;
      var club = nearest(evt);
      if (club < 0) return;
      setFollow(club === follow ? -1 : club);
    });
    canvas.addEventListener("mousemove", function (evt) {
      var club = nearest(evt);
      canvas.style.cursor = club >= 0 ? "pointer" : "default";
      if (club !== hover) { hover = club; if (!playing) draw(); }
    });
    canvas.addEventListener("mouseleave", function () { if (hover >= 0) { hover = -1; if (!playing) draw(); } });

    if (elPlay) elPlay.addEventListener("click", function () { touched = true; setPlaying(!playing); });
    if (elScrub) elScrub.addEventListener("input", function () {
      touched = true;
      if (playing) setPlaying(false);
      t = Number(elScrub.value); draw(); remember();
    });
    if (elSpeed) elSpeed.addEventListener("click", function () {
      speed = (speed + 1) % SPEEDS.length;
      elSpeed.textContent = SPEED_LABELS[speed];
      elSpeed.setAttribute("aria-label", "Speed: " + SPEED_LABELS[speed]);
    });
    if (elFind) {
      var pick = function () {
        var club = byName[elFind.value.trim().toLowerCase()];
        if (club !== undefined) { touched = true; setFollow(club); elFind.blur(); }
      };
      elFind.addEventListener("change", pick);
      elFind.addEventListener("input", pick);
    }
    if (elClear) elClear.addEventListener("click", function () { setFollow(-1); });
    // Journeys offered beside the replay: a club, and the season to start from.
    Array.prototype.forEach.call(document.querySelectorAll("[data-replay-club]"), function (el) {
      if (el.getAttribute("data-replay-for") && el.getAttribute("data-replay-for") !== root.id) return;
      el.addEventListener("click", function (evt) {
        var club = byId[el.getAttribute("data-replay-club")];
        if (club === undefined) return;
        evt.preventDefault();
        touched = true;
        setPlaying(false);
        startIndex = clamp((Number(el.getAttribute("data-replay-from")) || data.first) - data.first, 0, prep.n - 1);
        t = startIndex;
        setFollow(club);
        root.scrollIntoView({behavior: reduced ? "auto" : "smooth", block: "start"});
        if (!reduced) setPlaying(true);
      });
    });
    root.addEventListener("keydown", function (evt) {
      if (evt.target === elFind) return;
      if (evt.key === "ArrowLeft" || evt.key === "ArrowRight") {
        if (evt.target === elScrub) return;   // the slider already does this
        touched = true; setPlaying(false);
        t = clamp(Math.round(t) + (evt.key === "ArrowRight" ? 1 : -1), 0, prep.n - 1); draw(); remember();
        evt.preventDefault();
      }
    });

    var resizeTimer = 0;
    window.addEventListener("resize", function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () { geo = null; draw(); }, 80);
    });
    // The headline face arrives after first paint and changes nothing on
    // the canvas, but a late layout shift can change its width.
    if (window.ResizeObserver) new ResizeObserver(function () {
      if (geo && Math.abs((canvas.clientWidth || 0) - geo.width) > 1) { geo = null; draw(); }
    }).observe(canvas);

    // Play when it scrolls into view, stop when it leaves: an animation
    // nobody is looking at is a battery cost and nothing else. Someone who
    // has asked for less motion gets the present day, standing still, and
    // every control.
    var opened = false;
    if (!explicit) t = prep.n - 1;   // open on the present day: the full pyramid
    setFollow(follow);
    if (reduced) {
      draw();
    } else if (window.IntersectionObserver) {
      visible = false;
      new IntersectionObserver(function (entries) {
        visible = entries[0].isIntersecting && entries[0].intersectionRatio >= 0.4;
        if (!visible) {
          if (playing) { autoPaused = true; setPlaying(false); }
          return;
        }
        if (playing) return;
        if (!opened && !touched) {
          opened = true;
          // A link to the present day is a link to a picture, not a film.
          if (explicit && startIndex >= prep.n - 1) return;
          // The wind back happens in setPlaying; the pause before it is so
          // the full pyramid is seen standing still first.
          setTimeout(function () {
            if (touched) return;
            if (visible) setPlaying(true); else autoPaused = true;
          }, explicit ? 0 : 700);
        } else if (autoPaused) {
          autoPaused = false;
          setPlaying(true);
        }
      }, {threshold: [0, 0.4, 0.8]}).observe(root);
    } else {
      setPlaying(true);
    }
    // For anything outside that needs to drive it: the README's animation
    // is made by seeking through the seasons one frame at a time.
    root.replay = {
      follow: function (id) { setFollow(id && byId[id] !== undefined ? byId[id] : -1); },
      seek: function (v) { touched = true; clearTimeout(loopTimer); intro = null; playing = false;
                           root.classList.remove("is-playing"); t = clamp(v, 0, prep.n - 1); draw(); },
      seasons: prep.n
    };
  }

  // One fetch, however many replays are on the page.
  var cache = {};
  function load(src) {
    if (!cache[src]) cache[src] = fetch(src).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
    return cache[src];
  }
  window.pyramidData = load;

  Array.prototype.forEach.call(document.querySelectorAll(".replay"), function (root) {
    load(root.getAttribute("data-src")).then(function (data) {
      new Replay(root, data);
    }).catch(function (err) {
      // The page says so in words (.is-broken); the reason goes where a
      // person fixing it will look.
      root.classList.add("is-broken");
      if (window.console) console.warn("Replay not started:", err);
    });
  });
})();
