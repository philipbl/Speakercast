#!/usr/bin/env python3
"""Speakercast — build a podcast feed for every General Conference speaker.

Talk data comes from the Church's public study API:

    https://www.churchofjesuschrist.org/study/api/v3/language-pages/type/content

One request returns a conference's table of contents (sessions, speakers,
titles); one more per talk returns the audio URL and the article body.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import unicodedata
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger("speakercast")

API = "https://www.churchofjesuschrist.org/study/api/v3/language-pages/type/content"
SITE = "https://philip.lundrigan.org/Speakercast"
USER_AGENT = "Speakercast/2.0 (+https://github.com/philipbl/Speakercast)"

TZ = ZoneInfo("America/Denver")
FIRST_CONFERENCE = (1971, 4)
CONFERENCE_MONTHS = (4, 10)

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / ".cache"
FEED_DIR = ROOT / "feeds"
COVER_DIR = ROOT / "covers"
ASSET_DIR = ROOT / "assets"

COVER_IMAGE = ASSET_DIR / "images" / "cover.jpg"
COVER_FONT = ASSET_DIR / "Montserrat-Regular.ttf"


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def _build_session() -> requests.Session:
    """A requests Session that retries the failures worth retrying."""
    retry = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
    )
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=32))
    return session


SESSION = _build_session()


def fetch_page(uri: str) -> dict | None:
    """Fetch one study-API page. Returns None when the page does not exist.

    The API answers an unknown talk URI with its *parent* conference page
    rather than a 404, so the response URI is checked against the request.
    """
    response = SESSION.get(API, params={"lang": "eng", "uri": uri}, timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    page = response.json()
    if page.get("uri") != uri:
        LOGGER.warning("API answered %s with %s; treating as missing", uri, page.get("uri"))
        return None
    return page


def audio_size(url: str) -> int | None:
    """Byte length of an audio enclosure, via HEAD."""
    try:
        response = SESSION.head(url, timeout=30, allow_redirects=True)
        response.raise_for_status()
        return int(response.headers["content-length"])
    except (requests.RequestException, KeyError, ValueError):
        LOGGER.warning("No content-length for %s", url)
        return None


# --------------------------------------------------------------------------
# Conference calendar
# --------------------------------------------------------------------------


def conferences(start=FIRST_CONFERENCE, end=None):
    """Yield (year, month) for every conference from `start` through `end`."""
    year, month = start
    if month not in CONFERENCE_MONTHS:
        raise ValueError(f"start month must be 4 or 10, got {month}")
    if end is None:
        today = date.today()
        end = (today.year, today.month)

    while (year, month) <= tuple(end):
        yield year, month
        year, month = (year, 10) if month == 4 else (year + 1, 4)


def conference_sunday(year: int, month: int) -> date:
    """The first Sunday of the month — general conference's closing day."""
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7)


# Days *before* conference Sunday that a named weekday's sessions fall on.
# Tuesday is negative because those sessions followed the Sunday.
_DAYS_BEFORE_SUNDAY = {"thursday": 3, "friday": 2, "saturday": 1, "sunday": 0, "tuesday": -2}
_HOURS = {"morning": 10, "afternoon": 14, "evening": 18}

# Sessions named for an audience rather than a time slot.
_NAMED_SESSIONS = (
    (("women", "relief society"), (8, 18)),  # the Saturday a week before conference
    (("priesthood",), (1, 18)),
    (("welfare",), (0, 18)),
)


def session_slot(session: str) -> tuple[int, int] | None:
    """(days before conference Sunday, hour) for a session name, or None.

    Handles both "Saturday Evening Session" and audience-named sessions like
    "General Relief Society Meeting", including names the Church has not used
    yet, so a renamed session does not silently drop a conference of talks.
    """
    name = unicodedata.normalize("NFKC", session).replace("’", "'").lower()

    day = next((word for word in _DAYS_BEFORE_SUNDAY if word in name), None)
    hour = next((word for word in _HOURS if word in name), None)
    if day and hour:
        return _DAYS_BEFORE_SUNDAY[day], _HOURS[hour]

    for keywords, slot in _NAMED_SESSIONS:
        if any(keyword in name for keyword in keywords):
            return slot
    return None


def session_time(year: int, month: int, session: str) -> datetime:
    """When a session was held. Unknown sessions fall back to Sunday noon."""
    slot = session_slot(session)
    if slot is None:
        LOGGER.warning("Unmapped session %r in %d-%02d; using Sunday noon", session, year, month)
        slot = (0, 12)

    offset, hour = slot
    day = conference_sunday(year, month) - timedelta(days=offset)
    return datetime(day.year, day.month, day.day, hour, tzinfo=TZ)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

# Conference business, not talks. Matched as prefixes so real talks that merely
# contain a word ("Sustaining the Prophets", "Sustainable Societies") survive.
_SKIP_PREFIXES = (
    "sustaining of",
    "the sustaining of",
    "solemn assembly",
    "the solemn assembly",
    "statistical report",
    "church auditing department report",
    "the annual report of the church",
)
_SKIP_EXACT = {
    "welcome to conference",
    "revelation on priesthood accepted, church officers sustained",
}


def clean_speaker(name: str) -> str:
    """Normalize a speaker name so one person maps to exactly one feed.

    NFKC also composes accents, which keeps feed filenames in NFC — the form
    the website's URLs use. NFD filenames 404 on GitHub Pages.
    """
    name = unicodedata.normalize("NFKC", name)
    return re.sub(r"\s+", " ", name).strip()


def name_key(name: str) -> tuple[str, ...]:
    """Punctuation-insensitive identity of a name, for folding spellings together."""
    return tuple(re.sub(r"[^\w\s]", "", name, flags=re.UNICODE).lower().split())


def merge_name_variants(speakers: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Fold spellings that differ only in punctuation into one feed.

    The API spells a few people inconsistently across conferences ("Jack H
    Goaslind Jr." and "Jack H. Goaslind Jr."), which would otherwise split one
    person's talks across two feeds. The best-punctuated spelling wins, since
    that is the one with properly written initials.
    """
    groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for name in speakers:
        groups[name_key(name)].append(name)

    merged: dict[str, list[dict]] = {}
    for names in groups.values():
        canonical = max(names, key=lambda n: (len(re.findall(r"[^\w\s]", n)), len(speakers[n]), n))
        if len(names) > 1:
            LOGGER.info("Merging %s into %r", sorted(set(names) - {canonical}), canonical)

        talks = [talk for name in names for talk in speakers[name]]
        for talk in talks:
            talk["speaker"] = canonical
        merged[canonical] = talks

    return merged


def prune_stale(speakers: set[str], folder: Path, suffix: str) -> list[str]:
    """Delete feeds/covers for names no longer produced, so nothing rots in place."""
    removed = []
    for path in folder.glob(f"*{suffix}"):
        if unicodedata.normalize("NFC", path.stem) not in speakers:
            LOGGER.info("Removing stale %s", path.name)
            path.unlink()
            removed.append(path.name)
    return removed


def is_talk(stub: dict) -> bool:
    """False for sustainings, statistical reports and other conference business."""
    if stub.get("content_type") == "general-conference-business":
        return False
    title = (stub.get("title") or "").strip().lower()
    if not title:
        return False
    return title not in _SKIP_EXACT and not title.startswith(_SKIP_PREFIXES)


def parse_toc(body: str) -> list[dict]:
    """Talk stubs from a conference table of contents.

    Markup varies by era — conferences from 2021-2023 carry no
    `data-content-type` attributes at all — so sessions are located by their
    `h2.label` heading and talks by having a `primaryMeta` (speaker) line,
    which also excludes the session-overview links.
    """
    soup = BeautifulSoup(body, "html.parser")
    stubs = []

    for heading in soup.select("h2.label"):
        block = heading.parent
        if block is None:
            continue
        session = heading.get_text(strip=True)

        for anchor in block.select("a.list-tile"):
            speaker = anchor.find("p", class_="primaryMeta")
            if speaker is None:
                continue
            title = anchor.find("p", class_="title")
            description = anchor.find("p", class_="description")
            href = anchor.get("href") or ""
            item = anchor.find_parent("li")

            stubs.append(
                {
                    "session": session,
                    "speaker": clean_speaker(speaker.get_text(strip=True)),
                    "title": title.get_text(strip=True) if title else None,
                    "description": description.get_text(strip=True) if description else None,
                    "uri": talk_uri(href),
                    "content_type": item.get("data-content-type") if item else None,
                }
            )
    return stubs


def talk_uri(href: str) -> str:
    """Strip the `/study` prefix and query off a table-of-contents href.

    `/study/general-conference/2025/04/13holland?lang=eng`
        -> `/general-conference/2025/04/13holland`
    """
    path = urllib.parse.urlsplit(href).path
    return path[len("/study") :] if path.startswith("/study/") else path


def audio_url(page: dict) -> str | None:
    """The MP3 enclosure for a talk page, if one was published."""
    for item in page.get("meta", {}).get("audio") or []:
        url = item.get("mediaUrl")
        if url:
            return url
    return None


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


def _resolve_talk(stub: dict, year: int, month: int) -> dict | None:
    """Fill a stub out with audio and article body. None if it has no audio."""
    page = fetch_page(stub["uri"])
    if page is None:
        LOGGER.warning("Missing talk page %s", stub["uri"])
        return None

    url = audio_url(page)
    if url is None:
        return None

    size = audio_size(url)
    if size is None:
        return None

    return {
        "title": page["meta"].get("title") or stub["title"],
        "speaker": stub["speaker"],
        "session": stub["session"],
        "time": session_time(year, month, stub["session"]).isoformat(),
        "uri": stub["uri"],
        "url": f"https://www.churchofjesuschrist.org/study{stub['uri']}?lang=eng",
        "preview": stub["description"] or "",
        "html": page["content"]["body"],
        "audio_url": url,
        "audio_size": size,
    }


def fetch_conference(year: int, month: int, workers: int = 8) -> list[dict] | None:
    """Every talk with audio from one conference. None if not published yet."""
    uri = f"/general-conference/{year}/{month:02}"
    LOGGER.info("Fetching %s", uri)

    page = fetch_page(uri)
    if page is None:
        LOGGER.info("%s is not published yet", uri)
        return None

    stubs = [stub for stub in parse_toc(page["content"]["body"]) if is_talk(stub)]
    if not stubs:
        LOGGER.warning("No talks parsed from %s — the markup may have changed", uri)
        return []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        resolved = executor.map(lambda stub: _resolve_talk(stub, year, month), stubs)
        talks = [talk for talk in resolved if talk is not None]

    LOGGER.info("%s: %d talks with audio (of %d)", uri, len(talks), len(stubs))
    return talks


def load_conference(year: int, month: int, workers: int = 8, refresh: bool = False):
    """fetch_conference, memoized on disk. Past conferences never change."""
    cache = CACHE_DIR / f"{year}-{month:02}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())

    talks = fetch_conference(year, month, workers=workers)
    if talks:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(talks))
    return talks


# --------------------------------------------------------------------------
# Feeds
# --------------------------------------------------------------------------


def feed_path(speaker: str, folder: Path = FEED_DIR) -> Path:
    return folder / f"{speaker}.rss"


def cover_path(speaker: str, folder: Path = COVER_DIR) -> Path:
    return folder / f"{speaker}.jpg"


def build_feed(speaker: str, talks: list[dict], path: Path) -> None:
    """Write one speaker's RSS feed, oldest talk first."""
    talks = sorted(talks, key=lambda talk: talk["time"])
    latest = datetime.fromisoformat(talks[-1]["time"])
    cover = f"{SITE}/covers/{urllib.parse.quote(speaker)}.jpg"
    summary = f"General Conference talks by {speaker}."

    feed = FeedGenerator()
    feed.load_extension("podcast")
    feed.language("en")
    feed.title(f"Talks By {speaker}")
    feed.link(href=f"{SITE}/")
    feed.image(url=cover, title=summary)
    feed.description(summary)
    feed.author({"name": "Philip Lundrigan", "email": "philiplundrigan@gmail.com"})
    feed.generator("Speakercast")
    feed.pubDate(latest)
    feed.lastBuildDate(latest)
    feed.podcast.itunes_category("Religion & Spirituality", "Christianity")
    feed.podcast.itunes_author(speaker)
    feed.podcast.itunes_summary(summary)
    feed.podcast.itunes_image(cover)
    feed.podcast.itunes_explicit("no")

    for talk in talks:
        # feedgen 1.0 defaults to `prepend`, which would reverse every feed.
        entry = feed.add_entry(order="append")
        entry.id(talk["uri"])
        entry.title(talk["title"])
        entry.description(talk["preview"])
        entry.content(talk["html"], type="CDATA")
        entry.enclosure(talk["audio_url"], str(talk["audio_size"]), "audio/mpeg")
        entry.link(href=talk["url"])
        entry.published(datetime.fromisoformat(talk["time"]))
        entry.podcast.itunes_author(talk["speaker"])

    path.parent.mkdir(parents=True, exist_ok=True)
    feed.rss_file(str(path), pretty=True)


def build_cover(speaker: str, path: Path) -> None:
    """Render `Talks By <speaker>` onto the shared cover art."""
    text = f"Talks By\n{speaker}"
    font_size = 120

    image = Image.open(COVER_IMAGE).convert("RGBA")
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    def measure(value: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
        # Measured from the draw origin, not the ink corner, so the backing
        # box lines up with where multiline_text actually puts the glyphs.
        _, _, right, bottom = draw.multiline_textbbox(
            (0, 0), value, font=font, spacing=font.size / 2, align="center"
        )
        return right, bottom

    font = ImageFont.truetype(COVER_FONT, font_size)
    width, height = measure(text, font)

    # Wrap onto more lines until it fits; shrink the font once we run out of spaces.
    while width > image.size[0]:
        if " " not in text:
            font_size -= 5
            font = ImageFont.truetype(COVER_FONT, font_size)
            text = f"Talks By\n{speaker}"
        else:
            text = "\n".join(text.rsplit(" ", 1))
        width, height = measure(text, font)

    x, y = (image.size[0] - width) / 2, (image.size[1] - height) / 2
    draw.rectangle(((0, y), (image.size[0] + 25, y + height)), fill=(255, 255, 255, 200))
    draw.multiline_text(
        (x, y), text=text, fill=(0, 0, 0), font=font, spacing=font_size / 2, align="center"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.composite(layer, image, layer).convert("RGB").save(path)


def write_index(speakers: dict[str, list[dict]], path: Path) -> None:
    """The speaker list the website reads."""
    data = sorted(
        (
            {
                "name": speaker,
                "count": len(talks),
                "latest": max(talk["time"] for talk in talks)[:10],
            }
            for speaker, talks in speakers.items()
        ),
        key=lambda entry: entry["name"].rsplit(" ", 1)[-1],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


def collect_talks(start=FIRST_CONFERENCE, end=None, workers: int = 8, refresh: bool = False):
    """Every talk from every conference in range, grouped by speaker."""
    schedule = list(conferences(start, end))
    speakers: dict[str, list[dict]] = defaultdict(list)

    for index, (year, month) in enumerate(schedule):
        # The newest conference is still gaining audio, so never serve it from cache.
        is_latest = index == len(schedule) - 1
        talks = load_conference(year, month, workers=workers, refresh=refresh or is_latest)
        for talk in talks or []:
            speakers[talk["speaker"]].append(talk)

    return merge_name_variants(speakers)


def generate_feeds(
    start=FIRST_CONFERENCE,
    end=None,
    workers: int = 8,
    refresh: bool = False,
    feed_dir: Path = FEED_DIR,
    cover_dir: Path = COVER_DIR,
) -> dict[str, list[dict]]:
    """Build a feed and cover for every speaker, plus the website index."""
    speakers = collect_talks(start, end, workers=workers, refresh=refresh)
    if not speakers:
        raise RuntimeError("No talks were collected; refusing to overwrite existing feeds")

    LOGGER.info("Building feeds for %d speakers", len(speakers))
    for speaker, talks in speakers.items():
        build_feed(speaker, talks, feed_path(speaker, feed_dir))
        cover = cover_path(speaker, cover_dir)
        if not cover.exists():
            build_cover(speaker, cover)

    stale = prune_stale(set(speakers), feed_dir, ".rss") + prune_stale(
        set(speakers), cover_dir, ".jpg"
    )
    if stale:
        LOGGER.info("Removed %d stale files", len(stale))

    write_index(speakers, ASSET_DIR / "data.json")
    LOGGER.info("Done: %d speakers, %d talks", len(speakers), sum(map(len, speakers.values())))
    return speakers


def _conference_arg(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if not match:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {value!r}")
    year, month = int(match[1]), int(match[2])
    if month not in CONFERENCE_MONTHS:
        raise argparse.ArgumentTypeError("month must be 04 or 10")
    return year, month


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--start",
        type=_conference_arg,
        default=FIRST_CONFERENCE,
        metavar="YYYY-MM",
        help="first conference (default 1971-04)",
    )
    parser.add_argument(
        "--end",
        type=_conference_arg,
        default=None,
        metavar="YYYY-MM",
        help="last conference (default: today)",
    )
    parser.add_argument("--workers", type=int, default=8, help="concurrent requests (default 8)")
    parser.add_argument("--refresh", action="store_true", help="ignore the on-disk cache")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    generate_feeds(start=args.start, end=args.end, workers=args.workers, refresh=args.refresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
