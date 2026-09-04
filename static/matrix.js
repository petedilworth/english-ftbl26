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

  // ── Density toggle ────────────────────────────────────────────────────
  // Compact mode swaps club names for colour bars, which is what makes all
  // every level fits on one screen. The class is applied here rather than
  // rendered, because the choice is a per-visitor preference.
  var table = document.querySelector("table.matrix");
  var button = document.getElementById("matrix-density");
  var hint = document.getElementById("matrix-density-hint");
  if (!table || !button) return;

  var KEY = "matrix-density";

  function apply(mode) {
    var compact = mode === "compact";
    table.classList.toggle("compact", compact);
    button.textContent = compact ? "Show names" : "Compact";
    if (hint) {
      hint.textContent = compact
        ? "Colour bars in club colours — hover or tap a bar for the name."
        : "Names shown. Switch to compact to see every level at once.";
    }
  }

  var stored;
  try { stored = localStorage.getItem(KEY); } catch (e) { stored = null; }
  apply(stored || "names");

  button.addEventListener("click", function () {
    var next = table.classList.contains("compact") ? "names" : "compact";
    apply(next);
    try { localStorage.setItem(KEY, next); } catch (e) { /* private mode */ }
  });
})();
