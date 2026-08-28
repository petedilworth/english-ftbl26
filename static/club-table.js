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

  function setUp(table) {
    var headers = table.querySelectorAll("thead tr:last-child th");
    var body = table.tBodies[0];
    if (!body) return;

    headers.forEach(function (header, index) {
      function sort() {
        var descending = header.getAttribute("aria-sort") === "ascending";

        headers.forEach(function (other) {
          other.removeAttribute("aria-sort");
        });
        header.setAttribute("aria-sort", descending ? "descending" : "ascending");

        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (a, b) { return compare(a, b, index, descending); });
        // Re-appending a row that is already in the table moves it, so
        // the fragment is only to avoid a reflow per row.
        var fragment = document.createDocumentFragment();
        rows.forEach(function (row) { fragment.appendChild(row); });
        body.appendChild(fragment);
      }

      header.addEventListener("click", sort);
      header.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          sort();
        }
      });
    });
  }

  document.querySelectorAll("table.sortable").forEach(setUp);
})();
