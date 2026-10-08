# timelineMap — weekly Discord timeline digest

Reads a project timeline from **Google Sheets** or **Excel/CSV**, finds what's coming up, and posts a
weekly digest to a Discord channel through a webhook. You choose who writes the digest:

- **Code only**: a clean, plain list. Free, no AI and no extra accounts.
- **A free AI model**: GitHub Models, Google Gemini, Groq, or a local Ollama model. It adds a short
  summary of what matters this week and flags risks and deadline clusters.
- **Claude** (paid): the same kind of summary, written by Anthropic's Claude.

## 🌐 Open the app

**https://nickburum.github.io/timelineMap/**

Works in any browser on a phone or computer. **Upload timeline** reads your Excel or CSV file (or a Google
Sheets link) and shows a preview of the digest. From there:
- **Post to Discord now** sends the preview straight to your channel.
- **Save for weekly posts** stores the file in this repo's `timelines/` folder. The automatic Monday
  post always uses the newest file there.

The first time you open the app, paste your Discord webhook URL in **⚙️ Settings**. It's saved only in
your browser, never in this public repo. To save a timeline in one click, also add a GitHub token there
(a fine-grained token for this repository only, with *Contents: Read and write*). Without a token,
the save button opens GitHub's upload page instead.

**One-time setup to turn the link on:** in this repo, open **Settings → Pages**, choose
**Deploy from a branch**, then branch `main` and folder `/docs`, and click **Save**. The link starts
working about a minute later.

Each digest has four sections:

| Section | What goes in it |
|---|---|
| 📅 Next 7 days | Events whose date falls in the coming week |
| 🔭 Later | Events 8 to `LOOKAHEAD_DAYS` days out (default 14) |
| ⏳ In progress | Started already, has an end date that hasn't passed, not marked done |
| ⚠️ Overdue | Date passed in the last `OVERDUE_DAYS` (default 30) and has a status that isn't done/complete |

## 1. Set up your spreadsheet

Two layouts work, and the tool works out which one you're using.

### Weekly grid (team schedule)

Week dates run across the top row, with one row per person and that week's task in each cell:

|       |      | Aug 23 | Aug 30 | … | Oct 11 |
|---|---|---|---|---|---|
|       |      | PRE PRODUCTION *(merged across weeks)* | | | ALPHA PHASE |
|       |      |  | Pitch Day! | | Dev Begins |
| **Track / Focus** | **Name** | Week 1 | Week 2 | | Week 8 |
| Art | Ava | Ideation | Art style | | Fall Break! *(merged down)* |

- **Dates** can be written without a year (`August 23`, `November 1st`); the year is worked out
  automatically, including schedules that run past New Year.
- **Phase banners** (cells merged across several weeks) are reported as phases with a start and end.
- **Other cells above the name header** (e.g. *Pitch Day!*, *Playtest*) are milestones.
  `Week 1` labels are ignored.
- **Each person's cell** becomes their task for that week. A cell merged down the whole team
  (e.g. *Fall Break!*) is reported once, for everyone.
- **Hidden rows and columns are skipped**, so old weeks you've hidden won't show up.
- Merges and hidden columns are only kept in Excel (`.xlsx`) files. Google Sheets links are read as
  CSV, which loses them, so for grid schedules it's best to download the sheet as `.xlsx` and upload it.

See `examples/sample_grid_timeline.xlsx`.

### List (one event per row)

Use one row per event or milestone. Column names are detected automatically, and title rows above
the header are fine. Any of these work:

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

**Where the timeline can live** (`TIMELINE_SOURCE`, default `timelines`):
- **The `timelines/` folder (default):** upload files with the app, or with GitHub's
  **Add file → Upload files**. The newest file is used.
- **Google Sheets:** paste the normal sheet link. In Google Sheets, open **Share → General access**
  and set it to **Anyone with the link → Viewer**. To use a tab other than the first, copy the link
  while that tab is open; the link then includes `#gid=…`.
- **Excel / CSV file in this repo:** commit it (for example `timeline.xlsx`) and set
  `TIMELINE_SOURCE=timeline.xlsx`. Use `SHEET_NAME` to pick a worksheet.
- **Excel online / any URL:** a direct-download link to an `.xlsx` or `.csv` file.

## 2. Run it every week with GitHub Actions (no server needed)

1. In GitHub, open **Settings → Secrets and variables → Actions** for this repo.
2. Under **Secrets**, add `DISCORD_WEBHOOK_URL`: your Discord webhook URL.
3. Under **Variables**, add:
   - `TIMELINE_SOURCE` (optional): a Google Sheets link or file path. Leave it unset to use the newest
     file in `timelines/`. If it's set, it overrides the uploaded files.
   - optionally `AI_PROVIDER` (see the next section; default `github`), `PROJECT_NAME`,
     `TIMEZONE` (default `America/New_York`), `LOOKAHEAD_DAYS`, `SKIP_IF_EMPTY`, `DAY_FIRST`
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

Flags: `--source <link-or-path>`, `--dry-run`, `--ai none|github|gemini|groq|ollama|openai|claude|auto`, `--today YYYY-MM-DD`.

## Choosing code only, free AI, or Claude

Set the `AI_PROVIDER` variable (or pass `--ai <name>` on the command line):

| `AI_PROVIDER` | Cost | What you need |
|---|---|---|
| `none` | Free | Nothing. Code only: a plain list grouped by week. |
| `github` *(default in Actions)* | Free, with daily limits | Nothing extra in GitHub Actions: the workflow's built-in token is used. For local runs, set `GITHUB_TOKEN` to a personal access token with **Models: read**. Default model: `openai/gpt-4.1-mini`. |
| `gemini` | Free tier | A key from [Google AI Studio](https://aistudio.google.com/apikey), saved as the `GEMINI_API_KEY` secret. Default model: `gemini-2.5-flash`. On the free tier, Google may use prompts to improve its products. |
| `groq` | Free tier | A key from [console.groq.com](https://console.groq.com/keys), saved as the `GROQ_API_KEY` secret. Default model: `llama-3.3-70b-versatile`. |
| `ollama` | Free (runs locally) | Local runs only: install [Ollama](https://ollama.com) and run `ollama pull llama3.2`. |
| `openai` | Varies | Any OpenAI-compatible endpoint: set `AI_BASE_URL`, `AI_API_KEY` and `AI_MODEL`. |
| `claude` | Paid | An `ANTHROPIC_API_KEY` secret. Uses `claude-opus-5-5`; override it with `CLAUDE_MODEL`. |
| `auto` *(default locally)* | Varies | Claude if its key is set, then Gemini or Groq if a key is set, otherwise code only. |

To change the model, set `AI_MODEL`. The AI only sees the events in the digest window, sent as JSON,
and is told never to invent events, dates or owners. **If anything goes wrong** (a missing key, a
rate limit, an outage), the tool posts the code-only list instead, so the weekly post always goes
out. The message footer shows which writer was used.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```
