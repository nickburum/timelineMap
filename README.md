# timelineMap — weekly Discord timeline digest

Reads a project timeline from **Google Sheets** or **Excel/CSV**, finds what's coming up, and posts a
weekly digest to a Discord channel through a webhook. If an Anthropic API key is set, **Claude**
writes the digest: a short summary of what matters this week, plus flags for risks and deadline clusters.
Without a key it posts a clean, plain list instead.

Each digest has four sections:

| Section | What goes in it |
|---|---|
| 📅 Next 7 days | Events whose date falls in the coming week |
| 🔭 Later | Events 8 to `LOOKAHEAD_DAYS` days out (default 14) |
| ⏳ In progress | Started already, has an end date that hasn't passed, not marked done |
| ⚠️ Overdue | Date passed in the last `OVERDUE_DAYS` (default 30) and has a status that isn't done/complete |

## 1. Set up your spreadsheet

Use one row per event or milestone. Column names are detected automatically. Any of these work:

| Field | Required | Recognised headers |
|---|---|---|
| Name | ✅ | Event, Milestone, Name, Title, Task, Item, Deliverable, Activity |
| Date | ✅ | Date, Due Date, Due, Deadline, Start Date, Start, When, Target Date |
| End date | | End Date, End, Finish, Until |
| Status | | Status, State, Progress (rows marked *Done/Complete/Cancelled* are skipped) |
| Owner | | Owner, Assignee, Assigned To, Responsible, Lead |
| Category | | Type, Category, Phase, Workstream, Team, Stage |
| Notes | | Notes, Details, Comments, Description, Location |

If your headers are different, set `DATE_COLUMN`, `NAME_COLUMN`, and so on. Dates can be real
spreadsheet dates or text like `2026-10-14` or `10/14/2026`. For day-first dates such as `14/10/2026`,
set `DAY_FIRST=true`. See `examples/sample_timeline.xlsx` for a working sheet.

**Where the timeline can live** (`TIMELINE_SOURCE`):
- **Google Sheets:** paste the normal sheet link. In Google Sheets, open **Share → General access**
  and set it to **Anyone with the link → Viewer**. To use a tab other than the first, copy the link
  while that tab is open; the link then includes `#gid=…`.
- **Excel / CSV file in this repo:** commit it (for example `timeline.xlsx`) and set
  `TIMELINE_SOURCE=timeline.xlsx`. Use `SHEET_NAME` to pick a worksheet.
- **Excel online / any URL:** a direct-download link to an `.xlsx` or `.csv` file.

## 2. Run it every week with GitHub Actions (no server needed)

1. In GitHub, open **Settings → Secrets and variables → Actions** for this repo.
2. Under **Secrets**, add:
   - `DISCORD_WEBHOOK_URL`: your Discord webhook URL
   - `ANTHROPIC_API_KEY` (optional): turns on the Claude-written digest
3. Under **Variables**, add:
   - `TIMELINE_SOURCE`: your Google Sheets link or file path
   - optionally `PROJECT_NAME`, `TIMEZONE` (default `America/New_York`), `LOOKAHEAD_DAYS`, `SKIP_IF_EMPTY`, `DAY_FIRST`
4. Open **Actions → Weekly timeline digest → Run workflow**. Tick *dry run* to preview the digest in
   the log, or leave it unticked to post right away.

After that it posts automatically every **Monday at 13:07 UTC**. To change the time, edit the `cron`
line in `.github/workflows/weekly-digest.yml`. Cron times are always UTC.

> Keep the webhook URL out of the code. Anyone who has it can post to your channel. If it leaks,
> delete it in Discord (**Server Settings → Integrations → Webhooks**) and create a new one.

## 3. Run it locally

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in DISCORD_WEBHOOK_URL and TIMELINE_SOURCE
python -m timeline_notifier --dry-run                  # preview in the terminal
python -m timeline_notifier --today 2026-10-12 --dry-run  # pretend it's another day
python -m timeline_notifier                            # post to Discord
```

Flags: `--source <link-or-path>`, `--dry-run`, `--no-ai`, `--today YYYY-MM-DD`.

## How the AI part works

`timeline_notifier/summarizer.py` sends only the events in the digest window, as JSON, to Claude
(`claude-opus-5-5` at low effort; override it with `CLAUDE_MODEL`). Claude is told to use only those
facts and never to invent events. If the API key is missing, the call fails, or the request is
declined, the tool falls back to the plain list, so the weekly post always goes out.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```
