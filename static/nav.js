// The "Browse" disclosure in the header. <details> handles open/close and
// keyboard access on its own; all this adds is the two behaviours it lacks —
// closing on an outside click, and closing on Escape.
(function () {
  var more = document.querySelector(".nav-more");
  if (!more) return;

  document.addEventListener("click", function (e) {
    if (more.open && !more.contains(e.target)) more.open = false;
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && more.open) {
      more.open = false;
      var summary = more.querySelector("summary");
      if (summary) summary.focus();
    }
  });

  // A menu link closes the panel before navigating, so returning via the
  // back button doesn't land on a page with the menu still hanging open.
  more.addEventListener("click", function (e) {
    if (e.target.tagName === "A") more.open = false;
  });
})();

// The visitor's own club. The allocation page keeps the club it assigned
// in localStorage - the club, never the date of birth - and every page's
// header shows it from then on: the name where "Your club" was, its kit
// colours on the dot, and a link to its record. Called again by the
// allocation page the moment a club is assigned.
(function () {
  var link = document.getElementById("nav-club");
  if (!link) return;
  var home = link.getAttribute("href");   // .../allocation/index.html, before any swap

  function apply() {
    var club = null;
    try { club = JSON.parse(localStorage.getItem("ais.club") || "null"); } catch (e) { club = null; }
    // localStorage is shared by every page on this host, so nothing read
    // from it is trusted: the id has to look like a club id, and the
    // colours like colours, before either is put on the page.
    if (!club || typeof club.name !== "string" || !/^[a-z0-9-]{1,80}$/.test(club.id || "")) return;
    link.textContent = club.name.slice(0, 60);
    link.title = "Your club, by allocation";
    link.href = home.replace(/allocation\/index\.html$/, "team/" + club.id + "/index.html");
    if (/^#[0-9a-f]{3,8}$/i.test(club.a || "")) link.style.setProperty("--club-a", club.a);
    if (/^#[0-9a-f]{3,8}$/i.test(club.b || "")) link.style.setProperty("--club-b", club.b);
  }

  window.applyYourClub = apply;
  apply();
})();
