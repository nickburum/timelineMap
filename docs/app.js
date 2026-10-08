/* UI wiring for the Timeline Notifier page. Logic lives in timeline.js. */
(function () {
  "use strict";
  const T = window.Timeline;
  const $ = (id) => document.getElementById(id);

  const store = {
    get(key, fallback = "") { try { return localStorage.getItem("tn." + key) ?? fallback; } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem("tn." + key, value); } catch { /* private mode */ } },
  };

  // Repo defaults to the GitHub Pages site this page is served from (owner.github.io/repo/).
  function defaultRepo() {
    const host = location.hostname.match(/^([^.]+)\.github\.io$/i);
    const path = location.pathname.split("/").filter(Boolean)[0];
    return host && path ? `${host[1]}/${path}` : "nickburum/timelineMap";
  }

  const state = { sheets: null, events: [], file: null, sourceLabel: "" };

  function setStatus(el, msg, kind = "") {
    el.textContent = msg;
    el.className = "status" + (kind ? " " + kind : "");
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  // Render the small subset of Discord markdown we produce (**bold**, __underline__, _italic_).
  function mdToHtml(md) {
    return escapeHtml(md)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/^__(.+?)__$/gm, "<u>$1</u>")
      .replace(/(^|\s)_(.+?)_(?=\s|$)/g, "$1<em>$2</em>");
  }

  function toISODate(d) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  function asOfDate() {
    const [y, m, d] = $("asOf").value.split("-").map(Number);
    return y ? new Date(y, m - 1, d) : new Date();
  }

  function currentDigest() {
    const digest = T.buildDigest(state.events, asOfDate(), Number($("lookahead").value));
    const project = $("project").value.trim();
    return {
      digest,
      title: T.digestTitle(digest.today, project),
      body: T.renderPlain(digest),
      footer: `From ${state.sourceLabel || "the timeline spreadsheet"}`,
    };
  }

  function render() {
    if (!state.sheets) return;
    try {
      state.events = readEvents(state.sheets);
    } catch (err) {
      setStatus($("loadStatus"), err.message, "err");
      $("previewCard").classList.add("hidden");
      $("actionsCard").classList.add("hidden");
      return;
    }
    const { title, body, footer } = currentDigest();
    $("preview").innerHTML =
      `<span class="title">${escapeHtml(title)}</span>${mdToHtml(body)}<span class="foot">${escapeHtml(footer)}</span>`;

    $("allSummary").textContent = `All events (${state.events.length})`;
    const head = "<tr><th>Date</th><th>Event</th><th>Owner</th><th>Status</th></tr>";
    $("allTable").innerHTML = head + state.events.map((e) =>
      `<tr><td>${escapeHtml(T.fmt(e.date))}${e.end ? " → " + escapeHtml(T.fmt(e.end)) : ""}</td>` +
      `<td>${escapeHtml(e.name)}</td><td>${escapeHtml(e.owner)}</td><td>${escapeHtml(e.status)}</td></tr>`).join("");

    $("previewCard").classList.remove("hidden");
    $("actionsCard").classList.remove("hidden");
    $("saveWeekly").disabled = !state.file;
    $("saveHint").innerHTML = state.file
      ? `"Save for weekly posts" stores this file in the repo's <code>timelines/</code> folder. The automatic Monday post always uses the newest file there.`
      : `This timeline comes from a Google Sheets link. For weekly posts, add the link as the <code>TIMELINE_SOURCE</code> variable in the repo's GitHub settings (see the README).`;
  }

  // First worksheet that reads as a timeline (list or weekly grid) wins.
  function readEvents(sheets) {
    const opts = { dayFirst: $("dayFirst").checked, today: asOfDate() };
    let firstError = null;
    for (const sh of sheets) {
      try {
        const { events } = T.parseSheet(sh.grid, sh.layout, opts);
        if (events.length) return events;
      } catch (err) {
        firstError = firstError || err;
      }
    }
    if (firstError) throw firstError;
    return [];
  }

  function loadRows(sheets, label, file) {
    state.sheets = sheets;
    state.file = file || null;
    state.sourceLabel = label;
    setStatus($("actionStatus"), "");
    render();
    if (!$("previewCard").classList.contains("hidden")) {
      setStatus($("loadStatus"), `✅ Loaded ${state.events.length} events from ${label}.`, "ok");
      $("previewCard").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  // Each visible worksheet as a raw grid plus its merged cells and hidden rows/columns,
  // all indexed from cell A1 so they line up.
  function rowsFromWorkbook(wb) {
    const visible = wb.SheetNames.filter((n, i) => !(wb.Workbook && wb.Workbook.Sheets && wb.Workbook.Sheets[i] &&
      wb.Workbook.Sheets[i].Hidden));
    return (visible.length ? visible : wb.SheetNames).map((name) => {
      const ws = wb.Sheets[name];
      if (!ws["!ref"]) return { name, grid: [], layout: {} };
      const range = XLSX.utils.decode_range(ws["!ref"]);
      const body = XLSX.utils.sheet_to_json(ws, { header: 1, raw: true, defval: "", blankrows: true });
      const grid = [];
      body.forEach((row, i) => { grid[range.s.r + i] = Array(range.s.c).fill("").concat(row); });
      for (let r = 0; r < grid.length; r++) if (!grid[r]) grid[r] = [];
      const hiddenCols = new Set();
      (ws["!cols"] || []).forEach((col, c) => { if (col && col.hidden) hiddenCols.add(c); });
      const hiddenRows = new Set();
      (ws["!rows"] || []).forEach((row, r) => { if (row && row.hidden) hiddenRows.add(r); });
      const merges = (ws["!merges"] || []).map((m) => [m.s.r, m.s.c, m.e.r, m.e.c]);
      return { name, grid, layout: { merges, hiddenRows, hiddenCols } };
    });
  }

  async function handleFile(file) {
    if (!file) return;
    setStatus($("loadStatus"), `Reading ${file.name}…`);
    try {
      const buf = await file.arrayBuffer();
      const wb = XLSX.read(buf, { type: "array", cellDates: true, cellStyles: true });
      loadRows(rowsFromWorkbook(wb), file.name, { name: file.name, buffer: buf });
    } catch (err) {
      setStatus($("loadStatus"), `Couldn't read that file: ${err.message}`, "err");
    }
  }

  async function loadFromUrl(url, label) {
    setStatus($("loadStatus"), "Loading…");
    try {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const ctype = resp.headers.get("Content-Type") || "";
      if (ctype.includes("text/html")) throw new Error("got a web page instead of a spreadsheet; check the sharing settings");
      const buf = await resp.arrayBuffer();
      const wb = XLSX.read(buf, { type: "array", cellDates: true, cellStyles: true });
      return rowsFromWorkbook(wb);
    } catch (err) {
      setStatus($("loadStatus"), `Couldn't load ${label}: ${err.message}. ` +
        "Make sure the sheet is shared as 'Anyone with the link → Viewer', or download it as .xlsx and upload it instead.", "err");
      return null;
    }
  }

  async function postToDiscord() {
    const webhook = $("webhook").value.trim();
    if (!/^https:\/\/(discord|discordapp)\.com\/api\/webhooks\//.test(webhook)) {
      $("settings").open = true;
      $("webhook").focus();
      setStatus($("actionStatus"), "Add your Discord webhook URL in Settings first.", "warn");
      return;
    }
    const { title, body, footer } = currentDigest();
    const payloads = T.discordPayloads(title, body, footer);
    $("postNow").disabled = true;
    setStatus($("actionStatus"), "Posting…");
    try {
      for (const payload of payloads) {
        const resp = await fetch(webhook, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!resp.ok) throw new Error(`Discord answered HTTP ${resp.status}`);
      }
      setStatus($("actionStatus"), `✅ Posted to Discord (${payloads.length} message${payloads.length > 1 ? "s" : ""}).`, "ok");
    } catch (err) {
      setStatus($("actionStatus"), `Posting failed: ${err.message}. Check the webhook URL in Settings.`, "err");
    } finally {
      $("postNow").disabled = false;
    }
  }

  function b64(buffer) {
    const bytes = new Uint8Array(buffer);
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(bin);
  }

  async function saveWeekly() {
    if (!state.file) return;
    const repo = ($("repo").value.trim() || defaultRepo()).replace(/^https:\/\/github\.com\//, "").replace(/\/$/, "");
    const token = $("ghToken").value.trim();
    const safeName = state.file.name.replace(/[^\w.\- ]+/g, "_").replace(/\s+/g, "-");
    if (!token) {
      window.open(`https://github.com/${repo}/upload/main/timelines`, "_blank", "noopener");
      setStatus($("actionStatus"),
        `GitHub's upload page opened in a new tab. Drop ${state.file.name} there and click "Commit changes". ` +
        "Add a GitHub token in Settings to make this one click.", "warn");
      return;
    }
    $("saveWeekly").disabled = true;
    setStatus($("actionStatus"), "Saving to GitHub…");
    const api = `https://api.github.com/repos/${repo}/contents/timelines/${encodeURIComponent(safeName)}`;
    const headers = { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" };
    try {
      const existing = await fetch(`${api}?ref=main`, { headers });
      const sha = existing.ok ? (await existing.json()).sha : undefined;
      const resp = await fetch(api, {
        method: "PUT",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          message: `Upload timeline ${safeName}`,
          content: b64(state.file.buffer),
          branch: "main",
          ...(sha ? { sha } : {}),
        }),
      });
      if (!resp.ok) {
        const detail = (await resp.json().catch(() => ({}))).message || "";
        throw new Error(`GitHub answered HTTP ${resp.status} ${detail}`);
      }
      setStatus($("actionStatus"), `✅ Saved as timelines/${safeName}. Monday's post will use it.`, "ok");
    } catch (err) {
      setStatus($("actionStatus"), `Saving failed: ${err.message}. Check the token's repository access in Settings.`, "err");
    } finally {
      $("saveWeekly").disabled = false;
    }
  }

  function init() {
    if (!window.XLSX) {
      setStatus($("loadStatus"), "The spreadsheet reader didn't load. Check your connection and refresh.", "err");
    }
    $("asOf").value = toISODate(new Date());
    $("webhook").value = store.get("webhook");
    $("project").value = store.get("project");
    $("ghToken").value = store.get("ghToken");
    $("repo").value = store.get("repo", defaultRepo());
    $("dayFirst").checked = store.get("dayFirst") === "1";
    $("lookahead").value = store.get("lookahead", "14");
    $("actionsLink").href = `https://github.com/${$("repo").value || defaultRepo()}/actions/workflows/weekly-digest.yml`;
    if (!$("webhook").value) $("settings").open = true;

    $("uploadBtn").addEventListener("click", () => $("file").click());
    $("file").addEventListener("change", (e) => { handleFile(e.target.files[0]); e.target.value = ""; });
    const drop = $("drop");
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => handleFile(e.dataTransfer.files[0]));

    $("loadSheet").addEventListener("click", async () => {
      const url = $("sheetUrl").value.trim();
      const csv = T.googleSheetCsvUrl(url);
      if (!csv) { setStatus($("loadStatus"), "That doesn't look like a Google Sheets link.", "err"); return; }
      const rows = await loadFromUrl(csv, "the Google Sheet");
      if (rows) loadRows(rows, "the Google Sheet");
    });
    $("loadSample").addEventListener("click", async (e) => {
      e.preventDefault();
      const resp = await fetch("sample_timeline.xlsx");
      const buf = await resp.arrayBuffer();
      const wb = XLSX.read(buf, { type: "array", cellDates: true, cellStyles: true });
      loadRows(rowsFromWorkbook(wb), "the sample timeline", { name: "sample_timeline.xlsx", buffer: buf });
    });

    ["asOf", "lookahead", "dayFirst", "project"].forEach((id) => $(id).addEventListener("input", () => {
      store.set("lookahead", $("lookahead").value);
      store.set("dayFirst", $("dayFirst").checked ? "1" : "0");
      render();
    }));
    $("postNow").addEventListener("click", postToDiscord);
    $("saveWeekly").addEventListener("click", saveWeekly);
    $("saveSettings").addEventListener("click", () => {
      store.set("webhook", $("webhook").value.trim());
      store.set("project", $("project").value.trim());
      store.set("ghToken", $("ghToken").value.trim());
      store.set("repo", $("repo").value.trim());
      $("actionsLink").href = `https://github.com/${$("repo").value.trim() || defaultRepo()}/actions/workflows/weekly-digest.yml`;
      setStatus($("settingsStatus"), "✅ Saved in this browser.", "ok");
    });
  }

  init();
})();
