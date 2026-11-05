// Planning poker -> Jira, READ ONLY. The one hand-written JavaScript of this app: a bookmarklet, minified and embedded
// into a javascript: link by page/jira.py (which replaces __ROOM__ with the room's URL: never a secret).
// Run on a *.atlassian.net page: reads the tickets with the user's own Jira session (same origin: allowed by Jira's
// CSP), then sends them to the room's page with postMessage (a fetch to the poker server would be refused by Jira's
// connect-src). The room page only accepts messages from https://*.atlassian.net and asks its host to confirm.
// Keep it minifiable line by line: statements end with ";", no "//" except on full comment lines.
void (async function () {
  var room = __ROOM__;
  var roomOrigin = new URL(room).origin;
  var here = new URL(location.href);
  var KEY = /[A-Z][A-Z0-9_]+-[0-9]+/;
  var MAX = 200;
  var ready;
  var target;
  var timer;

  if (!/[.]atlassian[.]net$/.test(location.hostname)) {
    alert("Planning poker : ouvrez d'abord une page Jira (xxx.atlassian.net), puis cliquez sur ce favori. Ici, glissez-le dans votre barre de favoris.");
    return;
  }
  // the room opens first, in the click's own gesture (a pop-up blocker refuses it after a slow request)
  var opened = new Promise(function (resolve) {
    ready = resolve;
  });
  window.addEventListener("message", function (event) {
    if (event.source === target && event.origin === roomOrigin && event.data && event.data.type === "planningpoker:ready") {
      ready();
    }
  });
  target = window.open(room, "planningpoker");
  if (!target) {
    alert("Planning poker : le navigateur a bloqué l'ouverture de la salle. Autorisez les fenêtres pop-up pour ce site.");
    return;
  }
  timer = setInterval(function () {
    target.postMessage({type: "planningpoker:hello"}, roomOrigin);
  }, 700);
  setTimeout(function () {
    clearInterval(timer);
  }, 90000);

  async function search(jql) {
    var found = [];
    var token = "";
    do {
      var query = new URLSearchParams({jql: jql, fields: "summary,issuetype,parent", maxResults: "100"});
      if (token) query.set("nextPageToken", token);
      var reply = await fetch("/rest/api/3/search/jql?" + query.toString(), {credentials: "same-origin", headers: {Accept: "application/json"}});
      if (!reply.ok) throw new Error("Jira a répondu " + reply.status + ". Êtes-vous connecté à Jira ?");
      var page = await reply.json();
      found = found.concat(page.issues || []);
      token = page.isLast ? "" : page.nextPageToken || "";
    } while (token && found.length < MAX);
    return found;
  }

  function level(issue) {
    var type = issue.fields.issuetype || {};
    return typeof type.hierarchyLevel === "number" ? type.hierarchyLevel : 0;
  }

  try {
    var issues;
    var jql = here.searchParams.get("jql");
    var filter = here.searchParams.get("filter");
    var found = (here.searchParams.get("selectedIssue") || here.pathname).match(KEY);
    if (jql) {
      issues = await search(jql);
    } else if (filter) {
      issues = await search("filter = " + filter);
    } else {
      var key = found ? found[0] : (prompt("Planning poker : clé de l'epic ou du ticket à importer (ex. KP-12)") || "").trim().toUpperCase();
      if (!KEY.test(key)) throw new Error("Aucune clé de ticket reconnue.");
      issues = await search("key = " + key + " OR parent = " + key);
      var below = issues.filter(function (issue) {
        return issue.key !== key && level(issue) >= 0;
      });
      if (below.length) {
        var keys = below.map(function (issue) {
          return issue.key;
        });
        issues = issues.concat(await search("parent in (" + keys.join(",") + ")"));
      }
    }
    var seen = {};
    var items = [];
    issues.forEach(function (issue) {
      if (seen[issue.key] || items.length >= MAX) return;
      seen[issue.key] = true;
      var kind = level(issue) > 0 ? "epic" : level(issue) < 0 ? "subtask" : /stor|récit|histoire/i.test((issue.fields.issuetype || {}).name || "") ? "story" : "task";
      items.push({key: issue.key, title: issue.fields.summary || "", kind: kind, parent: issue.fields.parent ? issue.fields.parent.key : ""});
    });
    if (!items.length) throw new Error("Aucun ticket trouvé.");
    await opened;
    clearInterval(timer);
    target.postMessage({type: "planningpoker:import", items: items}, roomOrigin);
  } catch (error) {
    clearInterval(timer);
    alert("Planning poker : " + error.message);
  }
})();
