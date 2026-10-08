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


  // ---- Week-by-week grids: dates across the top, one row per person (mirrors timeline_notifier/grid.py) ----
  const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
  const MONTH_DAY = /^([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?$/i;
  const DAY_MONTH = /^(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?(?:,?\s+(\d{4}))?$/i;
  const WEEK_LABEL = /^(week|wk|sprint)\s*#?\s*\d+$/i;
  const NAME_HEADERS = new Set(["name", "names", "owner", "person", "assignee", "who", "member", "teammember", "people"]);
  const TRACK_HEADERS = new Set(["track", "focus", "trackfocus", "role", "team", "discipline", "department", "category", "group", "area"]);

  function headerDate(value, dayFirst) {
    if (value instanceof Date) { const d = toDate(value); return d ? [d.getMonth() + 1, d.getDate(), d.getFullYear()] : null; }
    const s = text(value);
    if (!s) return null;
    let m = s.match(MONTH_DAY);
    if (m && MONTHS[m[1].slice(0, 3).toLowerCase()]) return [MONTHS[m[1].slice(0, 3).toLowerCase()], +m[2], m[3] ? +m[3] : null];
    m = s.match(DAY_MONTH);
    if (m && MONTHS[m[2].slice(0, 3).toLowerCase()]) return [MONTHS[m[2].slice(0, 3).toLowerCase()], +m[1], m[3] ? +m[3] : null];
    if (/^\d{4}-\d{1,2}-\d{1,2}$|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$/.test(s) || typeof value === "number") {
      const d = toDate(value, dayFirst);
      if (d) return [d.getMonth() + 1, d.getDate(), d.getFullYear()];
    }
    return null;
  }

  // Year-less dates get the year that keeps the schedule continuous (the first one nearest today).
  function resolveYears(parts, today) {
    let anchor = today;
    return parts.map(([month, day, year]) => {
      const options = year ? [year] : [anchor.getFullYear() - 1, anchor.getFullYear(), anchor.getFullYear() + 1];
      const cands = options.map((y) => ymd(y, month, day)).filter(Boolean);
      if (!cands.length) return null;
      const best = cands.reduce((a, b) => (Math.abs(b - anchor) < Math.abs(a - anchor) ? b : a));
      anchor = best;
      return best;
    });
  }

  /** grid: array of row arrays. layout: { merges: [[r0,c0,r1,c1]], hiddenRows: Set, hiddenCols: Set } */
  function parseGrid(grid, layout, today, dayFirst) {
    const merges = layout.merges || [];
    const hiddenRows = layout.hiddenRows || new Set();
    const hiddenCols = layout.hiddenCols || new Set();
    const ncols = Math.max(0, ...grid.map((r) => r.length));
    const cell = (r, c) => (grid[r] && grid[r][c] !== undefined ? grid[r][c] : null);
    const visCols = [...Array(ncols).keys()].filter((c) => !hiddenCols.has(c));
    const visRows = [...grid.keys()].filter((r) => !hiddenRows.has(r));

    let best = null;
    for (const r of visRows.slice(0, 25)) {
      const found = [];
      for (const c of visCols) { const d = headerDate(cell(r, c), dayFirst); if (d) found.push([c, d]); }
      if (found.length >= 3 && (!best || found.length > best[1].length)) best = [r, found];
    }
    if (!best) throw new Error("no row of dates found");
    const [dateRow, found] = best;
    const resolved = resolveYears(found.map(([, d]) => d), today);
    const colDate = new Map();
    found.forEach(([c], i) => { if (resolved[i]) colDate.set(c, resolved[i]); });
    const dateCols = [...colDate.keys()].sort((a, b) => a - b);
    const colEnd = new Map();
    dateCols.forEach((c, i) => {
      const next = i + 1 < dateCols.length ? colDate.get(dateCols[i + 1]) : null;
      const gap = next ? daysBetween(colDate.get(c), next) : 7;
      colEnd.set(c, addDays(colDate.get(c), gap >= 1 && gap <= 31 ? gap - 1 : 6));
    });

    const labelCols = visCols.filter((c) => c < dateCols[0]);
    let headerRow = null, nameCol = null, trackCol = null;
    for (const r of visRows) {
      if (r <= dateRow) continue;
      const labels = labelCols.map((c) => [c, norm(text(cell(r, c)))]);
      if (labels.some(([, v]) => NAME_HEADERS.has(v) || TRACK_HEADERS.has(v))) {
        headerRow = r;
        nameCol = (labels.find(([, v]) => NAME_HEADERS.has(v)) || [null])[0];
        trackCol = (labels.find(([c, v]) => TRACK_HEADERS.has(v) && c !== nameCol) || [null])[0];
        break;
      }
    }
    if (labelCols.length && nameCol === null) {
      nameCol = labelCols[labelCols.length - 1];
      trackCol = labelCols.length > 1 ? labelCols[0] : null;
    }

    const mergeAt = new Map();
    const covered = new Set();
    for (const m of merges) {
      const [r0, c0, r1, c1] = m;
      mergeAt.set(`${r0},${c0}`, m);
      for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) if (r !== r0 || c !== c0) covered.add(`${r},${c}`);
    }
    const label = (r, c) => {
      if (c === null) return "";
      for (const [r0, c0, r1, c1] of merges) {
        if (r0 < r && r <= r1 && c0 <= c && c <= c1 && r0 > dateRow) return text(cell(r0, c0));
      }
      return text(cell(r, c));
    };

    const firstBody = (headerRow !== null ? headerRow : dateRow) + 1;
    const personRows = visRows.filter((r) => r >= firstBody && nameCol !== null && label(r, nameCol));
    const personSet = new Set(personRows);
    const bannerRows = visRows.filter((r) => (dateRow < r && r < firstBody) || (r >= firstBody && !personSet.has(r)));
    const span = (r, c, allowedRows) => {
      const m = mergeAt.get(`${r},${c}`);
      return [
        dateCols.filter((dc) => c <= dc && dc <= (m ? m[3] : c)),
        allowedRows.filter((rr) => r <= rr && rr <= (m ? m[2] : r)),
      ];
    };
    const blank = { status: "", owner: "", category: "", notes: "" };
    const events = [];
    const hasMerges = merges.length > 0;

    bannerRows.forEach((r, i) => {
      const cells = dateCols
        .filter((c) => !covered.has(`${r},${c}`) && text(cell(r, c)) && !WEEK_LABEL.test(text(cell(r, c))))
        .map((c) => [c, text(cell(r, c))]);
      if (!cells.length) return;
      const wide = cells.some(([c]) => span(r, c, [r])[0].length > 1);
      // Without merge info (CSV), treat a sparse first banner row as phases that run until the next one.
      const guessPhases = !hasMerges && i === 0 && r < firstBody && cells.length <= dateCols.length / 2;
      cells.forEach(([c, t], j) => {
        if (wide || guessPhases) {
          let cols;
          if (hasMerges) cols = span(r, c, [r])[0];
          else {
            const next = j + 1 < cells.length ? cells[j + 1][0] : null;
            cols = dateCols.filter((dc) => c <= dc && (next === null || dc < next));
          }
          events.push({ ...blank, name: t, date: colDate.get(c), end: colEnd.get(cols[cols.length - 1]), category: "Phase" });
        } else {
          events.push({ ...blank, name: t, date: colDate.get(c), end: colEnd.get(c), category: "Milestone" });
        }
      });
    });

    for (const r of personRows) {
      for (const c of dateCols) {
        const t = text(cell(r, c));
        if (covered.has(`${r},${c}`) || !t) continue;
        const [cols, rws] = span(r, c, personRows);
        const names = rws.map((rr) => label(rr, nameCol));
        const tracks = [...new Set(rws.map((rr) => label(rr, trackCol)).filter(Boolean))].sort();
        const wholeTeam = rws.length > 1 && rws.length === personRows.length;
        events.push({
          ...blank,
          name: t,
          date: colDate.get(c),
          end: colEnd.get(cols[cols.length - 1]),
          owner: wholeTeam ? "Everyone" : names.join(", "),
          category: wholeTeam ? "" : tracks.join(" / "),
        });
      }
    }
    events.sort((a, b) => a.date - b.date);
    return { events, columns: { layout: "grid" } };
  }

  /** Read either layout: a list (one event per row with Name/Date headers) or a week-by-week grid. */
  function parseSheet(grid, layout, opts = {}) {
    layout = layout || {};
    const hiddenRows = layout.hiddenRows || new Set();
    const visRows = [...grid.keys()].filter((r) => !hiddenRows.has(r));
    for (const r of visRows.slice(0, 10)) {
      const headers = (grid[r] || []).map((h) => text(h));
      try { detectColumns(headers); } catch { continue; }
      const rows = visRows.filter((rr) => rr > r).map((rr) => {
        const obj = {};
        headers.forEach((h, c) => { if (h) obj[h] = grid[rr][c] === undefined ? "" : grid[rr][c]; });
        return obj;
      });
      return parseEvents(rows, opts);
    }
    try {
      return parseGrid(grid, layout, opts.today || new Date(), opts.dayFirst);
    } catch {
      throw new Error("Couldn't read this timeline. Use either a list (one event per row, with columns like " +
        "\"Milestone\" and \"Date\") or a weekly grid (week dates across the top row, one row per person).");
    }
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

  function compact(ev) {
    return `• **${ev.owner}**${ev.category ? ` (${ev.category})` : ""}: ${ev.name}${ev.status ? ` · ${ev.status}` : ""}`;
  }

  // Events in date order; when 3+ people's tasks share the same dates, list them under one heading.
  function sectionLines(items, today) {
    const ordered = [...items].sort((a, b) => a.date - b.date || (a.end || a.date) - (b.end || b.date));
    const lines = [];
    let i = 0;
    while (i < ordered.length) {
      const key = (e) => `${+e.date}|${e.end ? +e.end : ""}`;
      const group = [];
      const k = key(ordered[i]);
      while (i < ordered.length && key(ordered[i]) === k) group.push(ordered[i++]);
      const assigned = group.filter((e) => e.owner);
      if (assigned.length < 3) { group.forEach((e) => lines.push(line(e, today))); continue; }
      group.filter((e) => !e.owner).forEach((e) => lines.push(line(e, today)));
      lines.push(`__${when(assigned[0], today)}__`);
      assigned.forEach((e) => lines.push(compact(e)));
    }
    return lines;
  }

  function sections(digest) {
    return [
      ["⏳ Happening now", digest.inProgress],
      ["📅 Next 7 days", digest.thisWeek],
      [`🔭 Later (up to ${digest.lookaheadDays} days out)`, digest.later],
      ["⚠️ Overdue / needs attention", digest.overdue],
    ];
  }

  function renderPlain(digest) {
    const out = sections(digest)
      .filter(([, items]) => items.length)
      .map(([title, items]) => `**${title}**\n` + sectionLines(items, digest.today).join("\n"));
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
    detectColumns, toDate, parseEvents, parseGrid, parseSheet, buildDigest, renderPlain, sections, line, when,
    chunkText, discordPayloads, digestTitle, googleSheetCsvUrl, fmt,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Timeline = api;
})(typeof window !== "undefined" ? window : globalThis);
