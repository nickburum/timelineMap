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


