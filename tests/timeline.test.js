const path = require("path");
const T = require(path.join(__dirname, "..", "docs", "timeline.js"));
const assert = require("assert");
const rows = [
  { Milestone: "Kickoff meeting", "Start Date": "2026-09-28", "End Date": "", Owner: "Alex", Status: "Done" },
  { Milestone: "Requirements sign-off", "Start Date": "2026-10-02", Status: "In progress", Owner: "Priya" },
  { Milestone: "Design sprint", "Start Date": new Date(Date.UTC(2026, 9, 5)), "End Date": "10/16/2026", Status: "In progress" },
  { Milestone: "Prototype demo", "Start Date": 46304, Status: "Not started" },
  { Milestone: "Beta build freeze", "Start Date": "2026-10-13" },
  { Milestone: "Marketing brief due", "Start Date": "Oct 19, 2026" },
  { Milestone: "", "Start Date": "2026-10-10" },
  { Milestone: "Public launch", "Start Date": "2026-11-16" },
];
const { events, columns } = T.parseEvents(rows);
assert.deepStrictEqual(columns, { date: "Start Date", end: "End Date", name: "Milestone", status: "Status", owner: "Owner" });
const d = T.buildDigest(events, new Date(2026, 9, 7), 14);
const names = (xs) => xs.map((e) => e.name);
assert.deepStrictEqual(names(d.thisWeek), ["Prototype demo", "Beta build freeze"]);
assert.deepStrictEqual(names(d.later), ["Marketing brief due"]);
assert.deepStrictEqual(names(d.inProgress), ["Design sprint"]);
assert.deepStrictEqual(names(d.overdue), ["Requirements sign-off"]);
assert.strictEqual(T.toDate("14/10/2026", true).getDate(), 14);
assert.strictEqual(T.toDate("14/10/2026", false), null);
const body = T.renderPlain(d);
const p = T.discordPayloads("t", body + "\n" + "x".repeat(90).concat("\n").repeat(100), "f");
assert(p.length > 1 && p.every((x) => x.embeds[0].description.length <= 4096));
assert.throws(() => T.parseEvents([{ Foo: 1 }]), /Couldn't find/);



// Weekly grid without merge info (as from a CSV export), crossing into the next year.
{
  const grid = [
    ["", "", "Nov 29", "Dec 6", "Dec 13", "Dec 20", "Jan 3", "Jan 10"],
    ["", "", "ALPHA", "", "", "", "BETA", ""],
    ["", "", "", "Playtest", "", "", "", "Launch"],
    ["Team", "Name", "Week 1", "Week 2", "Week 3", "Week 4", "Week 5", "Week 6"],
    ["Art", "Ava", "Boss", "Textures", "", "", "Polish", ""],
    ["", "Ben", "VFX", "", "", "", "", ""],
  ];
  const { events } = T.parseSheet(grid, {}, { today: new Date(2026, 11, 1) });
  const by = Object.fromEntries(events.map((e) => [e.name, e]));
  assert.deepStrictEqual(by.ALPHA.end, new Date(2027, 0, 2));
  assert.deepStrictEqual(by.BETA.date, new Date(2027, 0, 3));
  assert.strictEqual(by.Launch.category, "Milestone");
  assert.strictEqual(by.Polish.owner, "Ava");
  assert.strictEqual(by.VFX.owner, "Ben");
  assert.deepStrictEqual(by.Textures.date, new Date(2026, 11, 6));
}

// Weekly grid with merged cells and hidden columns (as SheetJS reports them from .xlsx).
{
  const grid = [
    ["STUDIO", "", "August 23", "May 4", "August 30", "September 6"],
    ["", "", "PRE PRODUCTION", "", "", "ALPHA"],
    ["Track / Focus", "Name", "Week 1", "", "Week 2", "Week 3"],
    ["Art", "Ava", "Ideation", "old", "Fall Break!", "Boss"],
    ["Art", "Ben", "Ideation", "old", "", "VFX"],
    ["Design", "Dee", "Ideation", "old", "", "Levels"],
  ];
  const layout = { merges: [[0, 0, 0, 1], [1, 2, 1, 4], [3, 4, 5, 4]], hiddenCols: new Set([3]) };
  const { events } = T.parseSheet(grid, layout, { today: new Date(2026, 8, 7) });
  assert(!events.some((e) => e.name === "old"));
  const pre = events.find((e) => e.name === "PRE PRODUCTION");
  assert.deepStrictEqual([pre.category, pre.end], ["Phase", new Date(2026, 8, 5)]);
  const fall = events.filter((e) => e.name === "Fall Break!");
  assert.strictEqual(fall.length, 1);
  assert.strictEqual(fall[0].owner, "Everyone");
  const d = T.buildDigest(events, new Date(2026, 8, 7), 14);
  const text = T.renderPlain(d);
  assert(text.startsWith("**⏳ Happening now**"));
  assert(text.includes("• **Ava** (Art): Boss") && text.includes("__Sun Sep 6"));
}

assert.throws(() => T.parseSheet([["foo", "bar"], [1, 2]], {}, {}), /weekly grid/);
console.log("timeline.test.js: all checks passed");
