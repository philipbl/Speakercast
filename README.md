# Speakercast

[![CI](https://github.com/philipbl/Speakercast/actions/workflows/ci.yml/badge.svg)](https://github.com/philipbl/Speakercast/actions/workflows/ci.yml)

Speakercast creates a podcast for every General Conference speaker. This lets you get to know a
speaker better, hearing common themes and styles throughout their talks.

Browse the feeds at **[philip.lundrigan.org/Speakercast](https://philip.lundrigan.org/Speakercast/)**.

## How it works

Talk data comes from the Church's public study API:

```
https://www.churchofjesuschrist.org/study/api/v3/language-pages/type/content?lang=eng&uri=/general-conference/2025/04
```

One request returns a conference's table of contents — sessions, speakers, titles — and one request
per talk returns its audio URL and article body. Everything is grouped by speaker into an RSS feed
under `feeds/`, with a generated cover image under `covers/`.

Feeds and covers are committed to `main`, which GitHub Pages serves directly.

## Running it

Requires Python 3.11+. With [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run speakercast
```

Useful flags:

```bash
uv run speakercast --workers 12             # more concurrency
uv run speakercast --refresh                # ignore the on-disk cache
uv run speakercast --start 2026-04          # development only, see below
```

Fetched conferences are cached in `.cache/` (gitignored). Past conferences never change, so only
the most recent one is refetched on each run — a warm cache turns a full rebuild into about thirty
seconds, which is why normal operation is always a full run.

`--start` / `--end` exist for development against a small slice of history. A bounded run only
knows about the speakers in that range, so it rewrites those speakers' feeds with just the in-range
talks and skips pruning entirely. Don't commit the output of one.

## Tests

```bash
uv run pytest            # offline, fixture-based
uv run pytest -m network # contract tests against the live API
```

The offline suite runs on every push. The network suite runs weekly in CI, because the thing most
likely to break this project is the Church changing its endpoints or page markup — not our code.

## Automation

| Workflow | When | What |
| --- | --- | --- |
| `ci.yml` | push, PR | Lint and run the offline tests on Python 3.11–3.13 |
| `ci.yml` (`api-contract`) | weekly | Check the live study API still behaves |
| `update-feeds.yml` | daily, 1st–16th of April and October | Regenerate feeds and commit anything new |

General conference is the first weekend of April and October, and audio lands over the following
days, so the update workflow runs daily through the first half of those months and commits only
when something actually changed. It can also be run by hand from the Actions tab.

## Maintenance

**When Church leadership changes**, update [`assets/leaders.json`](assets/leaders.json) — it holds
the First Presidency and Quorum of the Twelve shown at the top of the site. Everything else on the
page is generated. The roster is read from the most recent solemn assembly; names with no feed yet
are skipped automatically, so a stale entry degrades quietly rather than producing a dead link.

**Speaker names come from the API** and are used verbatim as feed filenames. Spellings that differ
only in punctuation are folded together so one person gets one feed. Filenames are normalized to
NFC — macOS writes NFD by default, and NFD names 404 on GitHub Pages.

## License

MIT — see [LICENSE](LICENSE).
