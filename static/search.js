// Live filter for the teams index. No dependencies.
(function () {
  var input = document.getElementById("team-search");
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
