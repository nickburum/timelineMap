/* Timeline parsing + digest logic for the browser (mirrors timeline_notifier/events.py + formatter.py).
   Works as a plain <script> (window.Timeline) and under Node for tests (module.exports). */
(function (root) {
  "use strict";

  const COLUMN_ALIASES = {
    name: ["event", "milestone", "name", "title", "task", "item", "deliverable", "activity", "description"],
    date: ["date", "duedate", "due", "deadline", "startdate", "start", "when", "targetdate", "eventdate"],
    end: ["enddate", "end", "finish", "finishdate", "until"],
    status: ["status", "state", "progress"],
    owner: ["owner", "assignee", "assignedto", "responsible", "lead", "who"],
    category: ["type", "category", "phase", "workstream", "team", "stage"],
    notes: ["notes", "details", "comments", "description", "location"],
  };
  const FIELD_ORDER = ["date", "end", "name", "status", "owner", "category", "notes"];
  const DONE = new Set(["done", "complete", "completed", "finished", "closed", "cancelled", "canceled", "shipped", "n/a"]);
  const DAY = 86400000;

  const norm = (h) => String(h).toLowerCase().replace(/[^a-z0-9]/g, "");

  function detectColumns(headers) {
    const byNorm = {};
    headers.forEach((h) => { if (!(norm(h) in byNorm)) byNorm[norm(h)] = h; });
    const mapping = {};
    const used = new Set();
    for (const field of FIELD_ORDER) {
      for (const alias of COLUMN_ALIASES[field]) {
        const col = byNorm[alias];
        if (col !== undefined && !used.has(col)) { mapping[field] = col; used.add(col); break; }
      }
    }
    const missing = ["date", "name"].filter((f) => !(f in mapping));
    if (missing.length) {
      throw new Error(`Couldn't find a ${missing.join(" or ")} column. Headers found: ${headers.join(", ")}. ` +
        "Use a header like \"Milestone\" for the name and \"Date\" or \"Due Date\" for the date.");
    }
    return mapping;
  }

  // Dates are handled as local-midnight Date objects so day arithmetic is simple.
  function ymd(y, m, d) {
    const dt = new Date(y, m - 1, d);
    return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d ? dt : null;
  }

  function toDate(value, dayFirst) {
    if (value === null || value === undefined || value === "") return null;
    if (value instanceof Date) {
      if (isNaN(value)) return null;
      // SheetJS builds dates in UTC-ish time; round to the nearest calendar day.
      const shifted = new Date(value.getTime() + 12 * 3600000);
      return ymd(shifted.getUTCFullYear(), shifted.getUTCMonth() + 1, shifted.getUTCDate());
    }
    if (typeof value === "number") {
      if (value > 20000 && value < 80000) { // Excel serial date
        const d = new Date(Date.UTC(1899, 11, 30) + Math.floor(value) * DAY);
        return ymd(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate());
      }
      return null;
    }
    const s = String(value).trim();
    let m = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/);
    if (m) return ymd(+m[1], +m[2], +m[3]);
    m = s.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})/);
    if (m) {
      let year = +m[3];
      if (year < 100) year += 2000;
      return dayFirst ? ymd(year, +m[2], +m[1]) : ymd(year, +m[1], +m[2]);
    }
    if (/^\d+(\.\d+)?$/.test(s)) return toDate(Number(s), dayFirst);
    const parsed = new Date(s); // e.g. "Oct 14, 2026"
    return isNaN(parsed) ? null : ymd(parsed.getFullYear(), parsed.getMonth() + 1, parsed.getDate());
  }

  const text = (v) => (v === null || v === undefined ? "" : String(v).trim());

  /** rows: array of objects keyed by header (as from SheetJS sheet_to_json). */
  function parseEvents(rows, opts = {}) {
    rows = rows.map((r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [String(k).trim(), v])));
    const headers = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((h) => !/^__EMPTY/.test(h));
    if (!rows.length) return { events: [], columns: {} };
    const cols = detectColumns(headers);
    const get = (row, field) => (cols[field] === undefined ? "" : row[cols[field]]);
    const events = [];
    for (const row of rows) {
      const name = text(get(row, "name"));
      const date = toDate(get(row, "date"), opts.dayFirst);
      if (!name || !date) continue;
      events.push({
        name,
        date,
        end: cols.end ? toDate(get(row, "end"), opts.dayFirst) : null,
        status: text(get(row, "status")),
        owner: text(get(row, "owner")),
        category: text(get(row, "category")),
        notes: text(get(row, "notes")),
      });
    }
    events.sort((a, b) => a.date - b.date);
    return { events, columns: cols };
  }

  const isDone = (ev) => DONE.has(ev.status.toLowerCase());
  const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const daysBetween = (a, b) => Math.round((b - a) / DAY);

  function buildDigest(events, today, lookaheadDays = 14, overdueDays = 30) {
    today = ymd(today.getFullYear(), today.getMonth() + 1, today.getDate());
    const weekEnd = addDays(today, 7);
    const horizon = addDays(today, lookaheadDays);
    const overdueFrom = addDays(today, -overdueDays);
    const d = { today, lookaheadDays, thisWeek: [], later: [], inProgress: [], overdue: [] };
    for (const ev of events) {
      if (ev.date >= today && ev.date < weekEnd) d.thisWeek.push(ev);
      else if (ev.date >= weekEnd && ev.date <= horizon) d.later.push(ev);
      else if (ev.date < today && ev.end && ev.end >= today && !isDone(ev)) d.inProgress.push(ev);
      else if (ev.date >= overdueFrom && ev.date < today && !ev.end && ev.status && !isDone(ev)) d.overdue.push(ev);
    }
    d.isEmpty = !(d.thisWeek.length || d.later.length || d.inProgress.length || d.overdue.length);
    return d;
  }

  const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const fmt = (d) => `${WD[d.getDay()]} ${MO[d.getMonth()]} ${d.getDate()}`;

  function when(ev, today) {
    let label = fmt(ev.date);
    if (ev.end && ev.end - ev.date !== 0) label += ` → ${fmt(ev.end)}`;
    const delta = daysBetween(today, ev.date);
    if (delta === 0) label += " (today)";
    else if (delta === 1) label += " (tomorrow)";
    else if (delta > 1) label += ` (in ${delta} days)`;
    else if (delta < 0 && !ev.end) label += ` (${-delta} days ago)`;
    return label;
  }

  function line(ev, today) {
    const parts = [`• **${ev.name}** — ${when(ev, today)}`];
    const extras = [ev.category, ev.owner ? `👤 ${ev.owner}` : "", ev.status].filter(Boolean);
    if (extras.length) parts.push(extras.join(" · "));
    let out = parts.join("\n   ");
    if (ev.notes) out += `\n   _${ev.notes.slice(0, 200)}_`;
    return out;
  }

  function sections(digest) {
    return [
      ["📅 Next 7 days", digest.thisWeek],
      [`🔭 Later (up to ${digest.lookaheadDays} days out)`, digest.later],
      ["⏳ In progress", digest.inProgress],
      ["⚠️ Overdue / needs attention", digest.overdue],
    ];
  }

  function renderPlain(digest) {
    const out = sections(digest)
      .filter(([, items]) => items.length)
      .map(([title, items]) => `**${title}**\n` + items.map((e) => line(e, digest.today)).join("\n"));
    return out.length ? out.join("\n\n") : `Nothing scheduled in the next ${digest.lookaheadDays} days. 🎉`;
  }

  function chunkText(body, limit = 4000) {
    const chunks = [];
    let cur = "";
    for (let para of body.split("\n")) {
      while (para.length > limit) { chunks.push(para.slice(0, limit)); para = para.slice(limit); }
      const cand = cur ? `${cur}\n${para}` : para;
      if (cand.length > limit) { chunks.push(cur); cur = para; } else cur = cand;
    }
    if (cur.trim()) chunks.push(cur);
    return chunks;
  }

  function discordPayloads(title, body, footer, username = "Timeline Bot") {
    const chunks = chunkText(body);
    if (!chunks.length) chunks.push("(empty)");
    return chunks.map((chunk, i) => {
      const embed = { description: chunk, color: 0x5865f2 };
      if (i === 0) embed.title = title.slice(0, 256);
      if (i === chunks.length - 1) embed.footer = { text: footer };
      return { username, embeds: [embed], allowed_mentions: { parse: [] } };
    });
  }

  function digestTitle(today, project) {
    return `🗓️ ${project ? project + " — " : ""}Week of ${MO[today.getMonth()]} ${today.getDate()}, ${today.getFullYear()}`;
  }

  function googleSheetCsvUrl(url) {
    const m = url.match(/docs\.google\.com\/spreadsheets\/d\/([A-Za-z0-9_-]+)/);
    if (!m) return null;
    const gid = url.match(/[#?&]gid=(\d+)/);
    return `https://docs.google.com/spreadsheets/d/${m[1]}/export?format=csv${gid ? "&gid=" + gid[1] : ""}`;
  }

  const api = {
    detectColumns, toDate, parseEvents, buildDigest, renderPlain, sections, line, when,
    chunkText, discordPayloads, digestTitle, googleSheetCsvUrl, fmt,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Timeline = api;
})(typeof window !== "undefined" ? window : globalThis);
