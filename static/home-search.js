// Club lookup on the home page.
//
// Deliberately not static/search.js: that one hides every h2/h3 on the page
// while a query is active, which is correct for the teams index (where the
// headings are section labels for the very list being filtered) and would
// blank the rest of the home page. Same data, same search keys, different
// page contract.
(function () {
  var input = document.getElementById("home-search");
  var list = document.getElementById("home-results");
  var noMatch = document.getElementById("home-no-match");
  if (!input || !list) return;

  var items = Array.prototype.slice.call(list.querySelectorAll("li"));
  var LIMIT = 8;

  function normalize(s) {
    return s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }

  input.addEventListener("input", function () {
    var q = normalize(input.value);

    if (!q) {
      list.hidden = true;
      if (noMatch) noMatch.hidden = true;
      return;
    }

    var shown = 0;
    items.forEach(function (li) {
      var hit = shown < LIMIT && li.getAttribute("data-name").indexOf(q) !== -1;
      li.style.display = hit ? "" : "none";
      if (hit) shown++;
    });

    list.hidden = shown === 0;
    if (noMatch) noMatch.hidden = shown !== 0;
  });
})();
