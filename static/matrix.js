// Matrix view: tap a club to highlight its cells across every season/tier.
(function () {
  var spans = Array.prototype.slice.call(document.querySelectorAll(".matrix-club"));
  var active = null;

  spans.forEach(function (span) {
    span.addEventListener("click", function () {
      var club = span.getAttribute("data-club");
      active = active === club ? null : club;
      spans.forEach(function (s) {
        var isMatch = active && s.getAttribute("data-club") === active;
        s.classList.toggle("matrix-highlight", !!isMatch);
        s.classList.toggle("matrix-dim", !!active && !isMatch);
      });
    });
  });
})();
