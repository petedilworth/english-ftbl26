/*
 * Click a heading to sort the table by it; click again to reverse.
 *
 * The one rule worth stating: A BLANK IS NOT A ZERO. Most columns here
 * are only partly filled - ground ownership is known for eighty clubs of
 * three hundred - and a blank means nobody has recorded it. Sorting them
 * as zero would put every unresearched club at the top of "smallest
 * capacity" and make the table lie about which grounds are small. Rows
 * with no value go last in both directions.
 *
 * Values are read from data-sort rather than from the cell text, so the
 * script never has to turn "£1.2m" or "38%" back into a number.
 */
(function () {
  "use strict";

  function sortValue(row, index) {
    var cell = row.cells[index];
    if (!cell) return null;
    var raw = cell.getAttribute("data-sort");
    if (raw === null || raw === "") return null;
    var asNumber = Number(raw);
    return Number.isNaN(asNumber) ? raw.toLowerCase() : asNumber;
  }

  function compare(a, b, index, descending) {
    var left = sortValue(a, index);
    var right = sortValue(b, index);

    // Missing last, whichever way the column is pointing.
    if (left === null && right === null) return 0;
    if (left === null) return 1;
    if (right === null) return -1;

    var order = left < right ? -1 : left > right ? 1 : 0;
    return descending ? -order : order;
  }

  // The sort lives in the URL so a finding can be sent to someone.
  //
  // Seventy-four columns and no way to say "look at this": the order was
  // held only in the DOM, so the interesting view - clubs by contested
  // share, say - died with the tab it was found in. The hash is
  // #sort=<column-key>,<asc|desc>, using the data-key the server already
  // puts on every header rather than a column index, so a link keeps
  // working when a column is added or moved.
  var tables = [];

  function readHash() {
    var m = /(?:^|[#&])sort=([^&,]+),(asc|desc)/.exec(window.location.hash || "");
    return m ? {key: decodeURIComponent(m[1]), descending: m[2] === "desc"} : null;
  }

  function writeHash(key, descending) {
    var next = "#sort=" + encodeURIComponent(key) + "," + (descending ? "desc" : "asc");
    if (window.location.hash === next) return;
    // replaceState, not a hash assignment: sorting a table is not a
    // navigation, and stacking history entries would turn Back into an
    // undo of every click rather than a way off the page.
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search + next);
    } else {
      window.location.hash = next;
    }
  }

  function setUp(table) {
    var headers = Array.prototype.slice.call(
      table.querySelectorAll("thead tr:last-child th"));
    var body = table.tBodies[0];
    if (!body) return;

    function apply(index, descending) {
      headers.forEach(function (other) { other.removeAttribute("aria-sort"); });
      headers[index].setAttribute("aria-sort", descending ? "descending" : "ascending");

      var rows = Array.prototype.slice.call(body.rows);
      rows.sort(function (a, b) { return compare(a, b, index, descending); });
      // Re-appending a row that is already in the table moves it, so
      // the fragment is only to avoid a reflow per row.
      var fragment = document.createDocumentFragment();
      rows.forEach(function (row) { fragment.appendChild(row); });
      body.appendChild(fragment);
    }

    headers.forEach(function (header, index) {
      function sort() {
        var descending = header.getAttribute("aria-sort") === "ascending";
        apply(index, descending);
        writeHash(header.getAttribute("data-key") || String(index), descending);
      }
      header.addEventListener("click", sort);
      header.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          sort();
        }
      });
    });

    // Both tables on the page answer to the same hash: the page is split
    // into two only because 355 rows is a lot to scroll, and a reader who
    // sorted by capacity means both halves.
    tables.push(function (state) {
      for (var i = 0; i < headers.length; i++) {
        if (headers[i].getAttribute("data-key") === state.key) {
          apply(i, state.descending);
          return;
        }
      }
    });
  }

  document.querySelectorAll("table.sortable").forEach(setUp);

  function restore() {
    var state = readHash();
    if (state) tables.forEach(function (fn) { fn(state); });
  }
  restore();
  window.addEventListener("hashchange", restore);
})();
