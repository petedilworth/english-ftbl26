/*
 * The head-to-head section on a club page: click an opponent, get every
 * match between the two.
 *
 * WHY THE MATCHES ARE NOT IN THE HTML, AND NOT LOADED WITH IT EITHER.
 * Arsenal have played 2,719 league matches against 58 clubs, about 90 KB
 * as JSON, and Hereford United have met 166 clubs. A page whose HTML is
 * 51 KB should not carry that for every reader when most will never open
 * an opponent. So the sibling h2h-data.js is fetched the first time a row
 * is opened - or on load, when the URL already names an opponent - and
 * the table of opponents above is server-rendered and works with the
 * script switched off.
 *
 * WHY A PANEL AND NOT AN EXPANDED ROW. The table is sortable through
 * static/club-table.js, which reorders every row in the tbody. A detail
 * row inserted between two opponents would be sorted away from the club
 * it belongs to, so the detail lives below the table instead.
 *
 * THE OPENED OPPONENT IS IN THE URL. #vs=tottenham-hotspur-fc opens that
 * record on load, so one club's record against another is a link rather
 * than a set of directions. It shares the fragment with the table's
 * #sort= through static/hash-state.js.
 */
(function () {
  "use strict";

  var table = document.getElementById("h2h-table");
  var panel = document.getElementById("h2h-detail");
  if (!table || !panel) return;

  var clubName = table.getAttribute("data-club-name") || "";
  var src = table.getAttribute("data-src");
  var data = null;
  var loading = null;

  // One script insertion, shared by every open before it lands. A second
  // click while the file is in flight must not start a second fetch.
  function load() {
    if (data) return Promise.resolve(data);
    if (loading) return loading;
    loading = new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = src;
      script.onload = function () {
        data = window.H2H || null;
        if (data) resolve(data); else reject(new Error("no data"));
      };
      script.onerror = function () { reject(new Error("failed to load")); };
      document.head.appendChild(script);
    });
    return loading;
  }

  function el(tag, text, className) {
    var node = document.createElement(tag);
    if (text !== null && text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function seasonLabel(year) {
    return (year - 1) + "/" + String(year % 100).padStart(2, "0");
  }

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // The stored form is ISO, which sorts and does not read. Built by hand
  // rather than with toLocaleDateString so the page says the same thing
  // whatever locale it is opened in.
  function dateLabel(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    if (!m) return iso || "";
    return Number(m[3]) + " " + MONTHS[Number(m[2]) - 1] + " " + m[1];
  }

  function outcome(gf, ga) {
    return gf > ga ? "Won" : gf < ga ? "Lost" : "Drawn";
  }

  function open(opponentId, scroll) {
    table.classList.add("h2h-loading");
    return load().then(function () {
      table.classList.remove("h2h-loading");
      var shown = render(opponentId);
      if (shown && scroll) panel.scrollIntoView({block: "nearest"});
      return shown;
    }, function () {
      table.classList.remove("h2h-loading");
      panel.textContent = "";
      panel.appendChild(el("p", "The match list could not be loaded.", "h2h-detail-record"));
      panel.hidden = false;
      return false;
    });
  }

  function render(opponentId) {
    var entry = data.opponents[opponentId];
    if (!entry) return false;

    panel.textContent = "";
    var head = el("div", null, "h2h-detail-head");
    var title = el("h3", clubName + " v ");
    if (entry.href) {
      var link = el("a", entry.name);
      link.setAttribute("href", entry.href);
      title.appendChild(link);
    } else {
      title.appendChild(document.createTextNode(entry.name));
    }
    head.appendChild(title);

    var w = 0, d = 0, l = 0;
    entry.matches.forEach(function (m) {
      var r = outcome(m[4], m[5]);
      if (r === "Won") w++; else if (r === "Drawn") d++; else l++;
    });
    head.appendChild(el("p", entry.matches.length + " meetings — " +
      w + " won, " + d + " drawn, " + l + " lost", "h2h-detail-record"));

    var close = el("button", "Close", "h2h-close");
    close.setAttribute("type", "button");
    close.addEventListener("click", function () { clear(true); });
    head.appendChild(close);
    panel.appendChild(head);

    var scroll = el("div", null, "table-scroll");
    var t = el("table", null, "standings");
    var thead = el("thead");
    var hrow = el("tr");
    ["Season", "Date", "Division", "Venue", "Score", "Result"].forEach(function (h) {
      hrow.appendChild(el("th", h));
    });
    thead.appendChild(hrow);
    t.appendChild(thead);

    var body = el("tbody");
    entry.matches.forEach(function (m) {
      var row = el("tr");
      row.appendChild(el("td", seasonLabel(m[0])));
      // Tiers 6 and 7 come from results grids that carry every score and
      // no date. Saying so beats an empty cell that reads as an oversight.
      var date = el("td", m[1] ? dateLabel(m[1]) : "not recorded");
      if (!m[1]) date.className = "h2h-undated";
      row.appendChild(date);
      row.appendChild(el("td", data.divisions[m[2]] || ""));
      row.appendChild(el("td", m[3] === "H" ? "Home" : "Away"));
      row.appendChild(el("td", m[4] + "–" + m[5], "num"));
      row.appendChild(el("td", outcome(m[4], m[5]),
        "h2h-" + outcome(m[4], m[5]).toLowerCase()));
      body.appendChild(row);
    });
    t.appendChild(body);
    scroll.appendChild(t);
    panel.appendChild(scroll);
    panel.hidden = false;

    mark(opponentId);
    return true;
  }

  // The row's state is announced as well as coloured: role="button" and
  // aria-expanded come from the server, and this keeps them true.
  function mark(opponentId) {
    Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
      var isOpen = row.getAttribute("data-opponent") === opponentId;
      row.classList.toggle("h2h-open", isOpen);
      row.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });
  }

  function clear(writeHash) {
    panel.hidden = true;
    panel.textContent = "";
    mark(null);
    if (writeHash && window.hashState) window.hashState.set("vs", null);
  }

  // Click and Enter do the same thing: open a closed row, close an open
  // one. They used to differ, and a keyboard user could not close.
  function toggle(row) {
    var id = row.getAttribute("data-opponent");
    if (row.classList.contains("h2h-open")) {
      clear(true);
      return;
    }
    open(id, false).then(function (shown) {
      if (shown && window.hashState) window.hashState.set("vs", id);
    });
  }

  table.addEventListener("click", function (event) {
    var row = event.target.closest ? event.target.closest("tr[data-opponent]") : null;
    if (!row) return;
    // A link in the row is a link: let it navigate.
    if (event.target.closest("a")) return;
    toggle(row);
  });

  table.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    var row = event.target.closest ? event.target.closest("tr[data-opponent]") : null;
    if (!row) return;
    event.preventDefault();
    toggle(row);
  });

  function fromHash(scroll) {
    var id = window.hashState ? window.hashState.get("vs") : null;
    if (!id) {
      clear(false);
      return;
    }
    open(id, scroll);
  }

  fromHash(true);
  window.addEventListener("hashchange", function () { fromHash(false); });
})();
