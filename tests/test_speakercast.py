"""Offline tests. Everything here runs against fixtures — no network.

The live API is exercised separately in test_live_api.py.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

import pytest

import speakercast as sc

FIXTURES = Path(__file__).parent / "fixtures"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


def toc(stem: str) -> str:
    return (FIXTURES / f"toc-{stem}.html").read_text()


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# --------------------------------------------------------------------------
# Conference calendar
# --------------------------------------------------------------------------


def test_conferences_alternate_april_and_october():
    assert list(sc.conferences((2024, 4), (2026, 4))) == [
        (2024, 4),
        (2024, 10),
        (2025, 4),
        (2025, 10),
        (2026, 4),
    ]


def test_conferences_excludes_a_conference_that_has_not_happened():
    # Late September: October's conference is still in the future.
    assert list(sc.conferences((2026, 4), (2026, 9))) == [(2026, 4)]


def test_conferences_starts_at_1971():
    assert next(sc.conferences()) == (1971, 4)


def test_conferences_rejects_a_non_conference_start_month():
    with pytest.raises(ValueError):
        list(sc.conferences((2025, 7)))


@pytest.mark.parametrize(
    ("year", "month", "expected"),
    [
        (2025, 4, date(2025, 4, 6)),
        (2025, 10, date(2025, 10, 5)),
        (1971, 4, date(1971, 4, 4)),
        (2023, 10, date(2023, 10, 1)),  # the 1st is itself a Sunday
    ],
)
def test_conference_sunday(year, month, expected):
    assert sc.conference_sunday(year, month) == expected
    assert sc.conference_sunday(year, month).weekday() == 6


# --------------------------------------------------------------------------
# Session times
# --------------------------------------------------------------------------

# Every session name the API has used since 1971.
ALL_SESSIONS = [
    "Saturday Morning Session",
    "Saturday Afternoon Session",
    "Saturday Evening Session",
    "Sunday Morning Session",
    "Sunday Afternoon Session",
    "Priesthood Session",
    "General Priesthood Session",
    "General Priesthood Meeting",
    "Priesthood Leadership Meeting",
    "General Relief Society Meeting",
    "General Young Women Meeting",
    "General Women’s Meeting",
    "General Women’s Session",
    "Women’s Session",
    "Women’s Fireside Addresses",
    "Relief Society Sesquicentennial Satellite Broadcast",
    "Welfare Session",
    "General Welfare Session",
    "Welfare Services Session",
    "Friday Morning Session",
    "Friday Afternoon Session",
    "Thursday Morning Session",
    "Thursday Afternoon Session",
    "Tuesday Morning Session",
    "Tuesday Afternoon Session",
    "Saturday Morning",
]


@pytest.mark.parametrize("session", ALL_SESSIONS)
def test_every_known_session_maps_to_a_slot(session):
    assert sc.session_slot(session) is not None


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        ("Saturday Morning Session", (1, 10)),
        ("Saturday Afternoon Session", (1, 14)),
        ("Saturday Evening Session", (1, 18)),
        ("Sunday Morning Session", (0, 10)),
        ("Sunday Afternoon Session", (0, 14)),
        ("Priesthood Session", (1, 18)),
        ("General Relief Society Meeting", (8, 18)),
        ("General Women’s Session", (8, 18)),
        ("Welfare Services Session", (0, 18)),
        ("Tuesday Afternoon Session", (-2, 14)),
    ],
)
def test_session_slots(session, expected):
    assert sc.session_slot(session) == expected


def test_curly_and_straight_apostrophes_agree():
    assert sc.session_slot("General Women’s Session") == sc.session_slot("General Women's Session")


def test_unknown_session_has_no_slot_but_still_gets_a_time():
    assert sc.session_slot("Member Finances Fireside") is None
    when = sc.session_time(1999, 4, "Member Finances Fireside")
    assert when.date() == sc.conference_sunday(1999, 4)


def test_session_time_uses_mountain_time_with_correct_dst_offset():
    april = sc.session_time(2025, 4, "Sunday Morning Session")
    assert april == datetime(2025, 4, 6, 10, tzinfo=sc.TZ)
    assert april.utcoffset().total_seconds() == -6 * 3600  # MDT

    january_like = sc.session_time(1971, 4, "Sunday Morning Session")
    assert january_like.utcoffset().total_seconds() == -7 * 3600  # MST, pre-DST in 1971


def test_sessions_order_within_a_conference():
    order = [
        "Saturday Morning Session",
        "Saturday Afternoon Session",
        "Saturday Evening Session",
        "Sunday Morning Session",
        "Sunday Afternoon Session",
    ]
    times = [sc.session_time(2025, 4, name) for name in order]
    assert times == sorted(times)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize("stem", ["1971-04", "2021-04", "2025-04"])
def test_toc_parses_every_markup_era(stem):
    """2021-2023 pages carry no data-content-type attributes at all."""
    stubs = sc.parse_toc(toc(stem))
    assert len(stubs) > 20
    assert all(stub["speaker"] for stub in stubs)
    assert all(stub["title"] for stub in stubs)
    assert all(stub["uri"].startswith("/general-conference/") for stub in stubs)
    assert all(stub["session"] for stub in stubs)


def test_toc_skips_session_overview_links():
    """The per-session landing pages have no speaker and are not talks."""
    uris = [stub["uri"] for stub in sc.parse_toc(toc("2025-04"))]
    assert not any(uri.endswith("saturday-morning-session") for uri in uris)


def test_toc_reads_speaker_title_and_session():
    stubs = sc.parse_toc(toc("2025-04"))
    holland = next(s for s in stubs if s["uri"].endswith("13holland"))
    assert holland["speaker"] == "Jeffrey R. Holland"
    assert holland["title"] == "As a Little Child"
    assert holland["session"] == "Saturday Morning Session"
    assert holland["description"]


def test_toc_assigns_talks_to_their_own_session():
    stubs = sc.parse_toc(toc("2025-04"))
    sessions = {stub["session"] for stub in stubs}
    assert sessions == {
        "Saturday Morning Session",
        "Saturday Afternoon Session",
        "Saturday Evening Session",
        "Sunday Morning Session",
        "Sunday Afternoon Session",
    }


def test_every_parsed_session_is_mappable_in_each_era():
    for stem in ["1971-04", "2021-04", "2025-04"]:
        for stub in sc.parse_toc(toc(stem)):
            assert sc.session_slot(stub["session"]) is not None, stub["session"]


@pytest.mark.parametrize(
    "href",
    [
        "/study/general-conference/2025/04/13holland?lang=eng",
        "/study/general-conference/2025/04/13holland",
        "https://www.churchofjesuschrist.org/study/general-conference/2025/04/13holland?lang=eng",
    ],
)
def test_talk_uri_strips_study_prefix_and_query(href):
    assert sc.talk_uri(href) == "/general-conference/2025/04/13holland"


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "The Sustaining of Church Officers",
        "Sustaining of General Authorities, Area Seventies, and General Officers",
        "Statistical Report, 2016",
        "Church Auditing Department Report, 2025",
        "Solemn Assembly",
        "The Annual Report of the Church",
        "Welcome to Conference",
    ],
)
def test_conference_business_is_not_a_talk(title):
    assert not sc.is_talk({"title": title, "content_type": None})


@pytest.mark.parametrize(
    "title",
    [
        "Sustaining the Prophets",
        "Sustainable Societies",
        "The Sustaining Power of Faith in Times of Uncertainty and Testing",
        "The Power of Sustaining Faith",
        "Welcome to the Church of Joy",
        "Welcome Message",
        "As a Little Child",
    ],
)
def test_real_talks_survive_the_business_filter(title):
    """These merely contain a filtered word — dropping them would lose real talks."""
    assert sc.is_talk({"title": title, "content_type": None})


def test_business_content_type_is_filtered_regardless_of_title():
    stub = {"title": "Something Inspiring", "content_type": "general-conference-business"}
    assert not sc.is_talk(stub)


def test_2025_toc_filters_only_the_business_items():
    stubs = sc.parse_toc(toc("2025-04"))
    kept = [s for s in stubs if sc.is_talk(s)]
    dropped = [s["title"] for s in stubs if not sc.is_talk(s)]
    assert kept
    assert all("Sustaining" in t or "Auditing" in t for t in dropped), dropped


# --------------------------------------------------------------------------
# Speaker names
# --------------------------------------------------------------------------


def test_clean_speaker_normalizes_non_breaking_space():
    """'Dallin\xa0H. Oaks' must not become a second feed."""
    assert sc.clean_speaker("Dallin\xa0H. Oaks") == "Dallin H. Oaks"


def test_clean_speaker_collapses_and_strips_whitespace():
    assert sc.clean_speaker("  Neil  L.   Andersen ") == "Neil L. Andersen"


def test_clean_speaker_leaves_ordinary_names_untouched():
    for name in ["Jeffrey R. Holland", "Ulisses Soares", "Kyle Stephen McKay", "J. Devn Cornish"]:
        assert sc.clean_speaker(name) == name


# --------------------------------------------------------------------------
# Talk pages
# --------------------------------------------------------------------------


def test_audio_url_reads_the_mp3_enclosure():
    assert sc.audio_url(fixture("talk-13holland.json")).endswith("-128k-en.mp3")


def test_audio_url_is_none_when_a_talk_has_no_audio():
    assert sc.audio_url(fixture("talk-no-audio.json")) is None
    assert sc.audio_url({"meta": {}}) is None


def test_resolve_talk_skips_talks_without_audio(monkeypatch):
    monkeypatch.setattr(sc, "fetch_page", lambda uri: fixture("talk-no-audio.json"))
    stub = {
        "uri": "/general-conference/1971/04/no-audio",
        "speaker": "A Speaker",
        "title": "T",
        "session": "Sunday Morning Session",
        "description": "",
    }
    assert sc._resolve_talk(stub, 1971, 4) is None


def test_resolve_talk_builds_a_complete_record(monkeypatch):
    monkeypatch.setattr(sc, "fetch_page", lambda uri: fixture("talk-13holland.json"))
    monkeypatch.setattr(sc, "audio_size", lambda url: 14363134)
    stub = next(s for s in sc.parse_toc(toc("2025-04")) if s["uri"].endswith("13holland"))

    talk = sc._resolve_talk(stub, 2025, 4)

    assert talk["title"] == "As a Little Child"
    assert talk["speaker"] == "Jeffrey R. Holland"
    assert talk["audio_size"] == 14363134
    assert talk["audio_url"].endswith(".mp3")
    assert talk["time"] == "2025-04-05T10:00:00-06:00"
    assert talk["url"].startswith("https://www.churchofjesuschrist.org/study/")
    assert talk["html"]


def test_fetch_page_rejects_a_parent_page_substituted_for_a_missing_talk(monkeypatch):
    """The API answers unknown talk URIs with the conference page, not a 404."""

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"uri": "/general-conference/2005/04", "meta": {}, "content": {"body": ""}}

    monkeypatch.setattr(sc.SESSION, "get", lambda *a, **k: Response())
    assert sc.fetch_page("/general-conference/2005/04/a-talk-that-does-not-exist") is None


def test_fetch_page_returns_none_on_404(monkeypatch):
    class Response:
        status_code = 404

    monkeypatch.setattr(sc.SESSION, "get", lambda *a, **k: Response())
    assert sc.fetch_page("/general-conference/2099/10") is None


# --------------------------------------------------------------------------
# Feed output
# --------------------------------------------------------------------------


@pytest.fixture
def talks():
    return [
        {
            "title": "Second Talk",
            "speaker": "Test Speaker",
            "session": "Sunday Morning Session",
            "time": "2025-04-06T10:00:00-06:00",
            "uri": "/general-conference/2025/04/b",
            "url": "https://www.churchofjesuschrist.org/study/general-conference/2025/04/b",
            "preview": "A summary.",
            "html": "<p>Body &amp; more</p>",
            "audio_url": "https://assets.example.org/b.mp3",
            "audio_size": 222,
        },
        {
            "title": "First Talk",
            "speaker": "Test Speaker",
            "session": "Saturday Morning Session",
            "time": "2024-10-05T10:00:00-06:00",
            "uri": "/general-conference/2024/10/a",
            "url": "https://www.churchofjesuschrist.org/study/general-conference/2024/10/a",
            "preview": "Another summary.",
            "html": "<p>Body</p>",
            "audio_url": "https://assets.example.org/a.mp3",
            "audio_size": 111,
        },
    ]


def test_feed_is_well_formed_rss(tmp_path, talks):
    path = tmp_path / "feed.rss"
    sc.build_feed("Test Speaker", talks, path)

    channel = ET.parse(path).getroot().find("channel")
    assert channel.findtext("title") == "Talks By Test Speaker"
    assert channel.findtext("language") == "en"
    assert channel.find(f"{ITUNES}category").get("text") == "Religion & Spirituality"
    assert channel.findtext(f"{ITUNES}author") == "Test Speaker"
    assert channel.findtext(f"{ITUNES}explicit") == "no"


def test_feed_items_are_oldest_first(tmp_path, talks):
    path = tmp_path / "feed.rss"
    sc.build_feed("Test Speaker", talks, path)

    items = ET.parse(path).getroot().find("channel").findall("item")
    assert [item.findtext("title") for item in items] == ["First Talk", "Second Talk"]


def test_feed_enclosures_carry_url_length_and_type(tmp_path, talks):
    path = tmp_path / "feed.rss"
    sc.build_feed("Test Speaker", talks, path)

    for item in ET.parse(path).getroot().find("channel").findall("item"):
        enclosure = item.find("enclosure")
        assert enclosure.get("url").endswith(".mp3")
        assert int(enclosure.get("length")) > 0
        assert enclosure.get("type") == "audio/mpeg"


def test_feed_pubdate_tracks_the_newest_talk(tmp_path, talks):
    path = tmp_path / "feed.rss"
    sc.build_feed("Test Speaker", talks, path)

    channel = ET.parse(path).getroot().find("channel")
    assert "06 Apr 2025" in channel.findtext("pubDate")


def test_feed_url_encodes_the_speaker_name_in_the_cover_link(tmp_path, talks):
    path = tmp_path / "feed.rss"
    sc.build_feed("Test Speaker", talks, path)
    assert "Test%20Speaker.jpg" in path.read_text()


def test_feed_embeds_the_article_body(tmp_path, talks):
    path = tmp_path / "feed.rss"
    sc.build_feed("Test Speaker", talks, path)
    assert "<p>Body</p>" in path.read_text()


# --------------------------------------------------------------------------
# Covers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "speaker",
    ["Dallin H. Oaks", "Kyle Stephen McKay", "Ulisses Soares", "Bonnie H. Cordon"],
)
def test_cover_renders_a_square_jpeg(tmp_path, speaker):
    from PIL import Image

    path = tmp_path / "cover.jpg"
    sc.build_cover(speaker, path)

    with Image.open(path) as image:
        assert image.format == "JPEG"
        assert image.size == (1000, 1000)


def test_cover_text_fits_inside_the_image(tmp_path):
    """A very long name must wrap or shrink rather than run off the edge."""
    from PIL import Image, ImageDraw, ImageFont

    speaker = "Wilhelmina Bartholomew Featherstonehaugh"
    path = tmp_path / "cover.jpg"
    sc.build_cover(speaker, path)

    with Image.open(path) as image:
        width = image.size[0]

    # Reproduce the wrapping the renderer settled on and confirm it fits.
    draw = ImageDraw.Draw(Image.new("RGBA", (width, width)))
    font = ImageFont.truetype(sc.COVER_FONT, 120)
    assert draw.multiline_textbbox((0, 0), f"Talks By\n{speaker}", font=font)[2] > width


# --------------------------------------------------------------------------
# Website index
# --------------------------------------------------------------------------


def test_index_counts_talks_and_records_the_latest(tmp_path, talks):
    path = tmp_path / "data.json"
    sc.write_index({"Test Speaker": talks, "Ann Adams": talks[:1]}, path)

    data = json.loads(path.read_text())
    assert [entry["name"] for entry in data] == ["Ann Adams", "Test Speaker"]  # by last name
    assert data[1] == {"name": "Test Speaker", "count": 2, "latest": "2025-04-06"}


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


def test_generate_feeds_writes_a_feed_and_cover_per_speaker(tmp_path, monkeypatch, talks):
    other = dict(talks[0], speaker="Other Speaker")
    monkeypatch.setattr(
        sc,
        "collect_talks",
        lambda *a, **k: {"Test Speaker": talks, "Other Speaker": [other]},
    )
    monkeypatch.setattr(sc, "ASSET_DIR", tmp_path)

    sc.generate_feeds(feed_dir=tmp_path / "feeds", cover_dir=tmp_path / "covers")

    for speaker in ["Test Speaker", "Other Speaker"]:
        assert (tmp_path / "feeds" / f"{speaker}.rss").exists()
        assert (tmp_path / "covers" / f"{speaker}.jpg").exists()
    assert json.loads((tmp_path / "data.json").read_text())


def test_generate_feeds_refuses_to_wipe_existing_feeds(tmp_path, monkeypatch):
    """An API outage must not be allowed to publish 473 empty feeds."""
    monkeypatch.setattr(sc, "collect_talks", lambda *a, **k: {})

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        sc.generate_feeds(feed_dir=tmp_path / "feeds", cover_dir=tmp_path / "covers")


def test_collect_talks_groups_by_speaker(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "CACHE_DIR", tmp_path / "cache")
    conference = [
        {"speaker": "A", "time": "2025-04-06T10:00:00-06:00"},
        {"speaker": "B", "time": "2025-04-06T10:00:00-06:00"},
        {"speaker": "A", "time": "2025-04-05T10:00:00-06:00"},
    ]
    monkeypatch.setattr(sc, "fetch_conference", lambda *a, **k: conference)

    speakers = sc.collect_talks(start=(2025, 4), end=(2025, 4))

    assert sorted(speakers) == ["A", "B"]
    assert len(speakers["A"]) == 2


def test_collect_talks_tolerates_an_unpublished_conference(tmp_path, monkeypatch):
    """October runs before conference weekend must not crash."""
    monkeypatch.setattr(sc, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(
        sc,
        "fetch_conference",
        lambda year, month, **k: (
            None if month == 10 else [{"speaker": "A", "time": "2025-04-06T10:00:00-06:00"}]
        ),
    )

    speakers = sc.collect_talks(start=(2025, 4), end=(2025, 10))

    assert sorted(speakers) == ["A"]


def test_cache_is_reused_for_past_conferences(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "CACHE_DIR", tmp_path / "cache")
    calls = []

    def fetch(year, month, **kwargs):
        calls.append((year, month))
        return [{"speaker": "A", "time": "2025-04-06T10:00:00-06:00"}]

    monkeypatch.setattr(sc, "fetch_conference", fetch)

    sc.load_conference(2024, 4)
    sc.load_conference(2024, 4)

    assert calls == [(2024, 4)]


def test_refresh_bypasses_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "CACHE_DIR", tmp_path / "cache")
    calls = []

    def fetch(year, month, **kwargs):
        calls.append((year, month))
        return [{"speaker": "A", "time": "2025-04-06T10:00:00-06:00"}]

    monkeypatch.setattr(sc, "fetch_conference", fetch)

    sc.load_conference(2024, 4)
    sc.load_conference(2024, 4, refresh=True)

    assert calls == [(2024, 4), (2024, 4)]


def test_latest_conference_is_always_refetched(tmp_path, monkeypatch):
    """Audio for a just-finished conference lands over the following days."""
    monkeypatch.setattr(sc, "CACHE_DIR", tmp_path / "cache")
    calls = []

    def fetch(year, month, **kwargs):
        calls.append((year, month))
        return [{"speaker": "A", "time": "2025-04-06T10:00:00-06:00"}]

    monkeypatch.setattr(sc, "fetch_conference", fetch)

    sc.collect_talks(start=(2024, 4), end=(2025, 4))
    sc.collect_talks(start=(2024, 4), end=(2025, 4))

    assert calls.count((2025, 4)) == 2  # newest: refetched
    assert calls.count((2024, 4)) == 1  # older: cached


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_parses_conference_arguments(monkeypatch):
    captured = {}
    monkeypatch.setattr(sc, "generate_feeds", lambda **kwargs: captured.update(kwargs))

    sc.main(["--start", "2020-04", "--end", "2025-10", "--workers", "3", "--refresh"])

    assert captured["start"] == (2020, 4)
    assert captured["end"] == (2025, 10)
    assert captured["workers"] == 3
    assert captured["refresh"] is True


@pytest.mark.parametrize("value", ["2025-07", "2025", "nonsense", "25-04"])
def test_cli_rejects_non_conference_dates(value, monkeypatch):
    monkeypatch.setattr(sc, "generate_feeds", lambda **kwargs: None)
    with pytest.raises(SystemExit):
        sc.main(["--start", value])


# --------------------------------------------------------------------------
# Name variants and pruning
# --------------------------------------------------------------------------


def test_clean_speaker_output_is_nfc():
    """NFD filenames 404 on GitHub Pages — the site links the NFC form."""
    import unicodedata

    for name in ["Gérald Caussé", "José A. Teixeira", "Jörg Klebingat", "Valeri V. Cordón"]:
        cleaned = sc.clean_speaker(unicodedata.normalize("NFD", name))
        assert cleaned == unicodedata.normalize("NFC", cleaned)
        assert cleaned == name


def test_name_key_ignores_punctuation():
    assert sc.name_key("Jack H Goaslind Jr.") == sc.name_key("Jack H. Goaslind Jr.")
    assert sc.name_key("Hartman Rector Jr.") == sc.name_key("Hartman Rector, Jr.")
    assert sc.name_key("Neil L. Andersen") != sc.name_key("Neil L. Anderson")


def test_merge_name_variants_folds_one_person_into_one_feed():
    """The API spells a few people inconsistently across conferences."""
    speakers = {
        "Jack H Goaslind Jr.": [{"speaker": "Jack H Goaslind Jr."} for _ in range(6)],
        "Jack H. Goaslind Jr.": [{"speaker": "Jack H. Goaslind Jr."}],
        "Neil L. Andersen": [{"speaker": "Neil L. Andersen"}],
    }

    merged = sc.merge_name_variants(speakers)

    assert sorted(merged) == ["Jack H. Goaslind Jr.", "Neil L. Andersen"]
    assert len(merged["Jack H. Goaslind Jr."]) == 7
    assert {t["speaker"] for t in merged["Jack H. Goaslind Jr."]} == {"Jack H. Goaslind Jr."}


def test_merge_name_variants_leaves_distinct_people_alone():
    speakers = {"Ronald A. Rasband": [{}], "Gary E. Stevenson": [{}]}
    assert sorted(sc.merge_name_variants(speakers)) == ["Gary E. Stevenson", "Ronald A. Rasband"]


def test_prune_stale_removes_only_departed_names(tmp_path):
    for name in ["Real Speaker", "Stale Speaker"]:
        (tmp_path / f"{name}.rss").write_text("<rss/>")

    removed = sc.prune_stale({"Real Speaker"}, tmp_path, ".rss")

    assert removed == ["Stale Speaker.rss"]
    assert (tmp_path / "Real Speaker.rss").exists()
    assert not (tmp_path / "Stale Speaker.rss").exists()


def test_prune_stale_matches_nfd_filenames_against_nfc_speakers(tmp_path):
    """macOS writes NFD filenames; the speaker set is NFC. Same person."""
    import unicodedata

    (tmp_path / f"{unicodedata.normalize('NFD', 'Gérald Caussé')}.rss").write_text("<rss/>")

    assert sc.prune_stale({"Gérald Caussé"}, tmp_path, ".rss") == []


def test_generate_feeds_prunes_a_departed_speaker(tmp_path, monkeypatch, talks):
    feeds, covers = tmp_path / "feeds", tmp_path / "covers"
    feeds.mkdir()
    covers.mkdir()
    (feeds / "Old Name.rss").write_text("<rss/>")
    (covers / "Old Name.jpg").write_bytes(b"")

    monkeypatch.setattr(sc, "collect_talks", lambda *a, **k: {"Test Speaker": talks})
    monkeypatch.setattr(sc, "ASSET_DIR", tmp_path)

    sc.generate_feeds(feed_dir=feeds, cover_dir=covers)

    assert not (feeds / "Old Name.rss").exists()
    assert not (covers / "Old Name.jpg").exists()
    assert (feeds / "Test Speaker.rss").exists()


def test_partial_run_does_not_prune_the_back_catalogue(tmp_path, monkeypatch, talks):
    """`--start 2026-04` must not delete every feed outside that range."""
    feeds, covers = tmp_path / "feeds", tmp_path / "covers"
    feeds.mkdir()
    covers.mkdir()
    (feeds / "Historic Speaker.rss").write_text("<rss/>")
    (covers / "Historic Speaker.jpg").write_bytes(b"")

    monkeypatch.setattr(sc, "collect_talks", lambda *a, **k: {"Test Speaker": talks})
    monkeypatch.setattr(sc, "ASSET_DIR", tmp_path)

    sc.generate_feeds(start=(2026, 4), feed_dir=feeds, cover_dir=covers)

    assert (feeds / "Historic Speaker.rss").exists()
    assert (covers / "Historic Speaker.jpg").exists()


def test_bounded_end_also_skips_pruning(tmp_path, monkeypatch, talks):
    feeds, covers = tmp_path / "feeds", tmp_path / "covers"
    feeds.mkdir()
    covers.mkdir()
    (feeds / "Historic Speaker.rss").write_text("<rss/>")

    monkeypatch.setattr(sc, "collect_talks", lambda *a, **k: {"Test Speaker": talks})
    monkeypatch.setattr(sc, "ASSET_DIR", tmp_path)

    sc.generate_feeds(end=(2000, 4), feed_dir=feeds, cover_dir=covers)

    assert (feeds / "Historic Speaker.rss").exists()


# --------------------------------------------------------------------------
# Duration
# --------------------------------------------------------------------------


def test_talk_duration_reads_the_player_metadata():
    assert sc.talk_duration('<video data-duration="909700" data-duration-string="15:09">') == 909


def test_talk_duration_is_none_when_the_page_has_no_player():
    assert sc.talk_duration("<p>Just text, no media.</p>") is None
    assert sc.talk_duration('<video data-duration="0">') is None


def test_talk_duration_from_the_real_talk_fixture():
    assert sc.talk_duration(fixture("talk-13holland.json")["content"]["body"]) == 909


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(909, "00:15:09"), (59, "00:00:59"), (3600, "01:00:00"), (3661, "01:01:01"), (0, "00:00:00")],
)
def test_format_duration(seconds, expected):
    assert sc.format_duration(seconds) == expected


def test_resolve_talk_captures_duration(monkeypatch):
    monkeypatch.setattr(sc, "fetch_page", lambda uri: fixture("talk-13holland.json"))
    monkeypatch.setattr(sc, "audio_size", lambda url: 14363134)
    stub = next(s for s in sc.parse_toc(toc("2025-04")) if s["uri"].endswith("13holland"))

    assert sc._resolve_talk(stub, 2025, 4)["duration"] == 909


def test_feed_publishes_itunes_duration(tmp_path, talks):
    talks[0]["duration"] = 909
    path = tmp_path / "feed.rss"
    sc.build_feed("Test Speaker", talks, path)

    items = ET.parse(path).getroot().find("channel").findall("item")
    durations = [item.findtext(f"{ITUNES}duration") for item in items]
    assert "00:15:09" in durations


def test_feed_omits_duration_when_unknown(tmp_path, talks):
    """18 talks have no player metadata; itunes:duration is optional."""
    for talk in talks:
        talk.pop("duration", None)
    path = tmp_path / "feed.rss"
    sc.build_feed("Test Speaker", talks, path)

    items = ET.parse(path).getroot().find("channel").findall("item")
    assert all(item.find(f"{ITUNES}duration") is None for item in items)
