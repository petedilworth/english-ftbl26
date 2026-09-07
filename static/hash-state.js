/*
 * The page's URL fragment as a set of named values, shared by every
 * script that keeps view state there.
 *
 * WHY. club-table.js put the sort order in the hash so a view could be
 * sent to someone, and wrote it by replacing the whole fragment. On the
 * club pages the head-to-head section now keeps the opened opponent in
 * the same fragment, and one script replacing what the other wrote means
 * sorting the table closes the record you were reading, or opening a
 * record throws away the sort. So both go through here.
 *
 * The format is #key=value&key=value, and it is deliberately the same
 * shape club-table.js already published: #sort=capacity,desc still means
 * what it meant, and a link that carries only that keeps working.
 */
(function () {
  "use strict";

  function read() {
    var hash = (window.location.hash || "").replace(/^#/, "");
    var out = {};
    hash.split("&").forEach(function (part) {
      if (!part) return;
      var eq = part.indexOf("=");
      if (eq < 1) return;
      out[decodeURIComponent(part.slice(0, eq))] = decodeURIComponent(part.slice(eq + 1));
    });
    return out;
  }

  function serialize(state) {
    return Object.keys(state).map(function (key) {
      // The value is written through encodeURIComponent but "," is left
      // legible: #sort=capacity,desc reads as what it does, and a hash
      // full of %2C is a worse link to send someone.
      return encodeURIComponent(key) + "=" +
        encodeURIComponent(state[key]).replace(/%2C/g, ",");
    }).join("&");
  }

  function set(key, value) {
    var state = read();
    if (value === null || value === undefined) {
      delete state[key];
    } else {
      state[key] = String(value);
    }
    var body = serialize(state);
    var next = body ? "#" + body : "";
    if ((window.location.hash || "") === next) return;
    // replaceState, not assignment: sorting a table or opening a record
    // is not a navigation, and stacking history entries would turn Back
    // into an undo of every click rather than a way off the page.
    if (window.history && window.history.replaceState) {
      window.history.replaceState(
        null, "", window.location.pathname + window.location.search + next);
    } else {
      window.location.hash = next;
    }
  }

  window.hashState = {
    read: read,
    get: function (key) {
      var state = read();
      return Object.prototype.hasOwnProperty.call(state, key) ? state[key] : null;
    },
    set: set,
  };
})();
