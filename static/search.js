// Live filter for a list: the teams index, and the index of all pages.
// The input is #team-search or anything marked data-live-filter; the items
// are .searchable li, each with what it matches in data-name. No dependencies.
(function () {
  var input = document.getElementById("team-search") || document.querySelector("[data-live-filter]");
  if (!input) return;

  var items = Array.prototype.slice.call(
    document.querySelectorAll(".searchable li")
  );
  var headings = Array.prototype.slice.call(
    document.querySelectorAll("h2, h3")
  );

  function normalize(s) {
    return s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }

  input.addEventListener("input", function () {
    var q = normalize(input.value);
    items.forEach(function (li) {
      var hit = !q || li.getAttribute("data-name").indexOf(q) !== -1;
      li.style.display = hit ? "" : "none";
    });
    // Hide section headings when a query is active, to present a flat result list
    headings.forEach(function (h) {
      h.style.display = q ? "none" : "";
    });
  });
})();
