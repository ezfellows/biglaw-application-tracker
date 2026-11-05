# Application Tracker

A local tracker for BigLaw summer associate applications. Every firm's
summer program sits on one page with its opening date, deadline and status.
Each program has an "applied" tick box, a checklist of the materials the firm
asks for, and a season calendar showing every open-to-deadline window.

Programs are grouped by what to do next: open now, opening soon, dates not
announced, applied, and closed or decided.

The data is a handful of CSV files you can open in any spreadsheet. The page
is served from your own machine and writes back to those files. It is plain
Python 3 with no dependencies to install.

## Quick start

```bash
git clone <this repo> application-tracker
cd application-tracker
python3 tracker.py --data demo init --sample   # invented firms and dates
python3 tracker.py --data demo serve           # open http://localhost:8765
```

The sample firms, people and email addresses are all made up. The sample
dates are for the 2028 summer hiring cycle (2L programs for summer 2028, 1L
programs for summer 2027).

To start your own:

```bash
python3 tracker.py init          # creates data/ next to tracker.py
```

Then list your firms in `data/firms.csv` (columns are described below):

```
key,name,aliases,target,priority,offices
hartwell,Hartwell & Pike LLP,Hartwell & Pike;Hartwell,y,1,DC;NY
```

and add applications:

```bash
python3 tracker.py app add "Hartwell & Pike" --office DC --program "2028 Summer Associate" --letter-required y
python3 tracker.py app set hartwell-dc opens=2026-11-01 deadline=2027-01-15
python3 tracker.py app list
python3 tracker.py serve
```

`data/` is in `.gitignore`, so your own applications never end up in a commit.
Every command takes `--data DIR` (or set `APPTRACKER_DATA`) to keep the data
somewhere else.

Requirements: Python 3.9 or later on macOS or Linux. Writes are serialized with
`fcntl` file locks, which Windows doesn't have.

## Commands

| Command | What it does |
|---|---|
| `init [--sample]` | Create the data folder with empty files, or with the invented sample. Never overwrites a file. |
| `serve [--port N]` | Serve the page on `http://localhost:8765` (localhost only). |
| `app list [--due]` | Every application with its priority (P1 to P4) and next step; `--due` shows only P1 and P2. |
| `app add FIRM [--office --program --id --letter-required y/n/optional/? --source URL --track --force]` | Add an application row. `FIRM` is a key or any name or alias from `firms.csv`. |
| `app adopt ID` | Turn a row from `cycle_others.csv` into an application, keeping its dates and materials. |
| `app set ID key=value ...` | Change fields on one row; `today` means today's date. A unique id prefix works. |
| `app fold ID --into LIVE_ID` | Fold a firm's second row into its first (see "One application per firm"). |
| `export [--as-of T]` | The JSON document for the phone copy. |
| `import-checks FILE [--since T --until T]` | Apply ticks made on the phone copy. |
| `confirm query / new / ingest / list / resolve` | Optional: match "we received your application" emails to applications. |

## One application per firm

Each firm gets one row in `applications.csv`. If a firm runs a second track you
might also apply to (a 1L program, or a dual 1L/2L option), put it in that
row's `note` instead of adding a second row.

- `app add` refuses a second row for a firm that already has one, and points
  you to `app adopt` when the firm already has a row in `cycle_others.csv`.
  Use `--force` only for a program with its own application form, such as a
  fellowship.
- `app fold ID --into LIVE_ID` cleans up a duplicate. It moves the row to
  `applications_merged.csv` (or `cycle_others_merged.csv`) with `merged_into`
  and `merged_on`, adds its track and program to the live row's note, and
  copies any checklist ticks the live row lacks. A row that records a sent
  application is refused.
- A folded id is never resurrected. A tick from a stale page or phone, or a
  receipt matched to a folded track, lands on the live row, and it never
  clears or overwrites what the live row already holds.

## The files

All files live in the data folder. Everything is UTF-8 CSV with a header row.

### applications.csv: your applications

| Column | Meaning |
|---|---|
| `id` | Short unique id, such as `hartwell-dc`. |
| `firm` | Firm key from `firms.csv`. |
| `office` | Offices, separated by `;` (e.g. `DC;NY`). |
| `program` | Program name as the firm writes it. |
| `track` | `2L-<cycle>` or `1L-<cycle-1>`, e.g. `2L-2028` / `1L-2027`. Guessed from `program` when empty. |
| `opens`, `deadline` | `YYYY-MM-DD`. |
| `open_status` | `open`, `upcoming`, `closed` or `unknown`, for a page that states a status but no date. |
| `rolling` | `y` if the firm reviews on a rolling basis. |
| `letter_required` | `y`, `n`, `optional` or `?`. |
| `letter` | Your cover letter: a folder under `letters_dir`, or `submitted`. |
| `materials` | What the firm asks for, as free text. The checklist is read from it. |
| `needs` | A hand-set checklist that overrides `materials`, e.g. `resume;cover_letter:opt;law_transcript:later`. |
| `checklist` | Items done, `item=YYYY-MM-DD;...`. The page writes this. |
| `apply_where` | Portal or address. |
| `source`, `checked` | Where the dates came from (a URL shows as a link), and the day you last checked them. |
| `applied` | The day you applied. The tick box writes this. |
| `confirmed`, `confirm_ref` | The day the firm's receipt email came, and that message's id. |
| `channel`, `referral` | How you applied, and who referred you, if anyone. |
| `screener`, `callback` | Interview dates. |
| `offer`, `offer_deadline` | Offer date and decision deadline. |
| `update_sent` | The day you sent first-semester grades (see `grades_released`). |
| `outcome` | `accepted`, `declined`, `rejected` or `withdrawn`. |
| `last_news` | The day you last heard anything. |
| `recruiter`, `recruiter_email` | The recruiting contact. |
| `note` | Anything else, including the firm's other track. |
| `updated` | Set on every change. |

`app list` turns these into a next step. Examples: "open since Mon 02 Nov,
rolling - apply; letter draft", "offer decision due tomorrow", "callback 12
days ago, no word - check in with recruiting".

### cycle_others.csv: programs you're watching

These are programs you know about but haven't decided to apply to, for
example from a sweep of firm career pages. Columns: `id, firm, office, track,
program, opens, deadline, open_status, rolling, letter_required, materials,
apply_where, note, source, checked`. The page shows them under "Every firm",
plus "My firms" for firms marked `target`. Ticking one makes it an
application. Unticking it with nothing else recorded turns it back into a
watched program. Checklist ticks on a watched program go to
`cycle_checks.csv` (`id, checklist`), so gathering a resume for one doesn't
make it an application.

### applications_merged.csv, cycle_others_merged.csv

Rows folded into their firm's live row. They have the same columns as the
file they came from, plus `merged_into` and `merged_on`.

### firms.csv: the firm list

| Column | Meaning |
|---|---|
| `key` | Short id used in the other files. |
| `name` | Display name. |
| `aliases` | Other names, separated by `;`, used to recognize the firm in `app add` and in email. The longest name is tried first, so "Morrow Hale" isn't read as "Morrow". |
| `target` | `y` to show the firm under "My firms". |
| `priority` | 1 (highest) and up; sorts the page. |
| `offices` | Offices you care about. |

Extra columns are ignored, so a roster you already keep elsewhere can be used
as is: point the `firms` setting at it.

### confirmations.csv

One row per email `confirm ingest` has read: `message_id, date, sender,
subject, kind, firm, app_id, result, evidence, logged, resolved`.

### config.json: settings (all optional)

```json
{
  "firms": "firms.csv",
  "domains": "firm_domains.csv",
  "letters_dir": "",
  "cycle": 2028,
  "timezone": "America/New_York",
  "offices": [],
  "grades_released": "",
  "receipts_since": "",
  "receipt_skip_senders": [],
  "lock": ".tracker.lock",
  "port": 8765
}
```

| Setting | Meaning |
|---|---|
| `firms`, `domains` | Paths to the firm list and the email-domain map. Relative paths are read from the data folder, and `~` works. |
| `letters_dir` | Optional cover-letter folder. The `letter` column names a subfolder holding `letter.md` (or a file directly), and a `state: draft/final/sent` line in its front matter shows on the page. |
| `cycle` | The summer the 2L programs hire for. Tracks, badges and the 1L/2L cues in email follow from it. |
| `timezone` | Decides what "today" is, on the page and in the CLI. |
| `offices` | Office filter buttons. By default they're the offices that appear most in your data. |
| `grades_released` | Once set, every applied row asks you to send your grades until `update_sent` is filled in. |
| `receipts_since`, `receipt_skip_senders` | Where the first receipt search starts, and sender domains to leave out (event platforms, school mailing lists). |
| `lock` | The lock file. If another tool writes the same CSVs, point both at one lock. |

## Materials checklist

Each application gets a checklist built from `materials` and `letter_required`
(or from `needs`, if you set it). The items are `resume`, `cover_letter`,
`undergrad`, `law_transcript`, `writing_sample`, `statement`, `references`,
`suited` (the Suited assessment some firms use), `test_score` and `video`.
Each item has a level:

- `req`: needed to apply
- `later`: can follow, such as a law transcript once first-semester grades post
- `opt`: welcome but not needed
- `unknown`: the firm hasn't said. This level is only kept for the cover letter.

The parser handles lists ("resume, cover letter and transcripts"), negations
("no writing sample"), hedges ("optional video introduction"), timing ("once
available", "at the callback stage") and notes cut off mid-word. It always
adds a resume, and a law transcript as `later` unless the firm wants grades
before it will look at an application. When it misreads a firm, set `needs`
by hand:

```bash
python3 tracker.py app set hartwell-dc "needs=resume;cover_letter;writing_sample:opt;law_transcript:later"
```

At the top of the page, a row of buttons counts what is still to gather
across the programs shown. Pressing one narrows the list to the programs
still missing that item.

## Optional: application receipts from email

Most firms send a receipt when an application goes in. The tracker can read
those receipts and mark applications `confirmed`, but it never reads mail
itself. You (or a script, or an AI assistant with access to your mailbox)
fetch the messages and hand them over as JSON:

```bash
python3 tracker.py confirm query          # six Gmail searches, starting two days before the last ingest
python3 tracker.py confirm new ID ID ...  # which message ids haven't been read yet
python3 tracker.py confirm ingest messages.json
python3 tracker.py confirm list --review  # what needs a look
python3 tracker.py confirm resolve MESSAGE_ID APP_ID   # or: ignore
```

`messages.json` is a list of `{message_id, date, from, from_name, subject,
body}`. `examples/messages.json` has a few invented ones to try. Whoever reads
the mail may add `kind` (`application`, `status`, `started`, `assessment`,
`assessment_invite` or `other`) and `program`. A label wins over the built-in
phrase rules, which on their own only confirm an application whose box is
already ticked.

What ingest does with each kind of message:

- **A receipt for a ticked application** sets `confirmed`. A labeled receipt
  for an unticked one also sets `applied`.
- **A finished Suited assessment** ticks that checklist item.
- **Interview or decision news, a firm named only in the body, or a program
  no row matches** waits in `confirm list --review`.
- **An application started but never submitted** ("click here to continue
  your application") is flagged after two days.
- **Event registrations, talent-community sign-ups and FAQ pages** are
  recognized and skipped.

Sender domains map to firms through `firm_domains.csv` (`domain,firm`).
Display names and subjects are matched against `firms.csv`.

## Optional: a phone copy

`tracker.html` also runs as a private claude.ai artifact page, using that
page's document store. Without a server, it shows the rows from the last sync
and saves ticks to the store. A sync runs on the computer that holds the data:

1. List the store's `checks` collection and save it (a JSON file, or a folder
   of one JSON file per document). Note the time `T` you listed it.
2. `python3 tracker.py import-checks SAVED --since <last synced_at> --until T`
3. `python3 tracker.py export --as-of T` and write the output over the
   `meta/rows` document.

The store holds one `meta/rows` document plus one `checks/<id>` document per
applied tick (`checks/<id>__<item>` for a checklist item). Ticks made after
`T` wait for the next sync. A tick older than the last sync is ignored,
because the ledger has the newer answer. `examples/checks.json` shows the
format. Nothing in this repository talks to the network. Whatever runs the
sync moves the JSON.

## Tests

```bash
python3 -m unittest discover -s tests
```

Each test builds its own throwaway data folder with invented firms.
`tests/test_setup.py` also checks that every email address in the repository
is on a reserved `.example` domain and that no file holds a home-directory
path, a phone number or a private page link.

## License

Not chosen yet.
