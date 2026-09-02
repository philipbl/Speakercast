"""Contract tests against the live study API.

These are what catch the Church changing its endpoints or markup — the failure
mode that silently broke this project before. They are marked `network` and
excluded from the default run; CI executes them on a schedule:

    pytest -m network
"""

from __future__ import annotations

import pytest

import speakercast as sc

pytestmark = pytest.mark.network


@pytest.mark.parametrize("year,month", [(1971, 4), (1995, 10), (2021, 4), (2025, 4)])
def test_conference_toc_still_parses_in_every_era(year, month):
    page = sc.fetch_page(f"/general-conference/{year}/{month:02}")
    assert page is not None, "conference page disappeared"

    stubs = sc.parse_toc(page["content"]["body"])
    assert len(stubs) >= 20, f"only {len(stubs)} talks parsed — markup likely changed"
    assert all(stub["speaker"] and stub["title"] for stub in stubs)


def test_every_session_name_in_use_still_maps_to_a_time():
    page = sc.fetch_page("/general-conference/2025/04")
    unmapped = {
        stub["session"]
        for stub in sc.parse_toc(page["content"]["body"])
        if sc.session_slot(stub["session"]) is None
    }
    assert not unmapped, f"unmapped sessions: {unmapped}"


def test_a_talk_page_still_exposes_audio_and_a_body():
    page = sc.fetch_page("/general-conference/2025/04/13holland")
    assert page is not None
    assert page["meta"]["title"] == "As a Little Child"
    assert sc.audio_url(page), "no audio enclosure in talk metadata"
    assert len(page["content"]["body"]) > 1000


def test_audio_enclosures_still_report_a_size():
    page = sc.fetch_page("/general-conference/2025/04/13holland")
    assert sc.audio_size(sc.audio_url(page)) > 1_000_000


def test_a_missing_conference_is_reported_as_missing():
    assert sc.fetch_page("/general-conference/2099/10") is None


def test_a_missing_talk_does_not_silently_return_its_parent_page():
    """The API answers unknown talk URIs with the conference page."""
    assert sc.fetch_page("/general-conference/2025/04/definitely-not-a-talk") is None


def test_a_whole_conference_resolves_end_to_end():
    talks = sc.fetch_conference(2025, 4, workers=8)
    assert len(talks) >= 25

    talk = talks[0]
    assert talk["audio_url"].endswith(".mp3")
    assert talk["audio_size"] > 0
    assert talk["speaker"] and talk["title"] and talk["html"]
