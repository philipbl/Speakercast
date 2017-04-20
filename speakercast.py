#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, wait
from datetime import date, datetime, timedelta
import itertools
import logging
import json
import os
import queue
import sqlite3

from feedgen.feed import FeedGenerator
from gospellibrary.catalogs import CatalogDB, current_catalog_version
from gospellibrary.item_packages import ItemPackage
from PIL import Image, ImageFont, ImageDraw
import pytz
import requests


logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s:%(threadName)s:%(levelname)s:'
                           '%(name)s:%(message)s',
                    handlers=[logging.StreamHandler()])
LOGGER = logging.getLogger("speakercast." + __name__)


def _get_month_year(start, end):
    start_year, start_month = start
    end_year, end_month = end

    # Make sure we start on a boundary
    if start_month <= 4:
        start_month = 4
    elif start_month <= 10:
        start_month = 10
    else:
        start_month = 4
        start_year += 1

    # Make sure we end on a boundary
    if end_month < 4:
        end_month = 10
        end_year -= 1
    elif end_month < 10:
        end_month = 4
    else:
        end_month = 10

    yield (start_month, start_year)

    while start_year != end_year or start_month != end_month:
        start_month += 6
        start_year = start_year + start_month // 12
        start_month = start_month % 12

        yield (start_month, start_year)


def _clean_speaker(speaker):
    speaker = speaker.replace('\xa0', ' ')
    speaker = speaker.replace('By ', '')
    speaker = speaker.replace('President ', '')
    speaker = speaker.replace('Elder ', '')
    speaker = speaker.replace('Bishop ', '')
    speaker = speaker.replace('Presented by ', '')
    speaker = speaker.strip()

    return speaker


def _clean_session(session):
    session = session.lower()
    if session in ['priesthood', 'general priesthood session',
                   'general priesthood meeting']:
        session = 'priesthood session'

    elif session == 'welfare session':
        session = 'general welfare session'

    elif session == 'saturday morning':
        session = 'saturday morning session'

    elif session in ['general women\'s meeting', 'women\'s fireside address',
                   'general relief society meeting', 'general women\'s session',
                   'general women’s meeting', 'general women’s meeting ',
                   'relief society sesquicentennial satellite broadcast']:
        session = "general young women meeting"

    session = session.replace('sesssion', 'session')
    session = session.replace('preisthood', 'priesthood')

    return session


def _get_time(year, month, session):
    first_of_month = datetime(year, month, 1)
    days_ahead = 6 - first_of_month.weekday()
    sunday = first_of_month + timedelta(days_ahead)

    def adjust_time(delta_day, hour):
        return (sunday - timedelta(delta_day)).replace(hour=hour)

    try:
        time = {"general young women meeting": adjust_time(8, 18),
                "thursday morning session": adjust_time(3, 10),
                "thursday afternoon session": adjust_time(3, 14),
                "friday morning session": adjust_time(2, 10),
                "friday afternoon session": adjust_time(2, 14),
                "saturday morning session": adjust_time(1, 10),
                "saturday afternoon session": adjust_time(1, 14),
                "priesthood session": adjust_time(1, 18),
                "sunday morning session": adjust_time(0, 10),
                "sunday afternoon session": adjust_time(0, 14),
                "general welfare session": adjust_time(0, 18),
                "tuesday morning session": adjust_time(-2, 10),
                "tuesday afternoon session": adjust_time(-2, 14)}[session.lower()]

        time = time.replace(tzinfo=pytz.timezone('US/Mountain'))
        return time
    except:
        return None


def _get_preview(talk, package):
    with sqlite3.connect(os.path.join(package.path(), 'package.sqlite')) as db:
        c = db.cursor()
        try:
            c.execute('''SELECT preview FROM nav_item WHERE uri=?''', [talk['uri']])
            return c.fetchone()[0]
        finally:
            c.close()


def _get_session(talk, package):
    with sqlite3.connect(os.path.join(package.path(), 'package.sqlite')) as db:
        c = db.cursor()
        try:
            c.execute('''SELECT nav_section.title FROM nav_section INNER JOIN nav_item ON nav_section._id=nav_item.nav_section_id WHERE nav_item.uri=?''', [talk['uri']])
            return c.fetchone()[0]
        finally:
            c.close()


def _get_talk_info(talk, package, year, month):
    # Get talk information
    title = talk['primary_title_component']
    speaker = _clean_speaker(talk['secondary_title_component'])
    talk_url = talk['web_url']
    preview = _get_preview(talk, package)

    # Get time information
    date = (year, month)
    session = _clean_session(_get_session(talk, package))
    time = _get_time(date[0], date[1], session)

    # Get audio information if available
    try:
        audio = package.related_audio_items(talk['id'])[0]
        audio_url = audio['media_url']
        audio_size = audio['file_size']
    except IndexError:
        audio_url = None
        audio_size = None

    return {'title': title,
            'speaker': speaker.replace('\xc2', ''),
            'session': session,
            'time': time,
            'uri': talk['uri'],
            'url': talk_url,
            'preview': preview,
            'audio_url': audio_url,
            'audio_size': audio_size}


def _valid_talk(talk):
    title = talk['title']

    if title in ['Welcome to Conference', 'The Sustaining of Church Officers']:
        return False

    if 'Church Auditing Department Report' in title or \
       'Statistical Report' in title:
        return False

    return True


def _get_talks(catalog, month, year):
        item_uri = f"/general-conference/{year}/{month:02}"
        LOGGER.info(f"~~~> Getting {item_uri}")
        item = catalog.item(uri=item_uri, lang='eng')
        package = ItemPackage(item_external_id=item['external_id'], item_version=item['version'])

        talks = (_get_talk_info(subitem, package, year, month) for subitem in package.subitems())
        talks = (talk for talk in talks if talk['audio_url'] is not None)
        talks = (talk for talk in talks if talk['time'] is not None)
        talks = (talk for talk in talks if _valid_talk(talk))

        return list(talks)


def _feed_version(version=None):
    if version is None:
        try:
            with open('assets/version.json') as f:
                return json.load(f)['version']
        except Exception:
            return -1
    else:
        with open('assets/version.json', 'w') as f:
            json.dump({'version': version}, f)


def _create_feed(speaker, talks, file_name):
    LOGGER.info("Creating feed for %s", speaker)
    now = datetime.now()
    now = now.replace(tzinfo=pytz.timezone('US/Mountain'))

    fg = FeedGenerator()
    fg.load_extension('podcast')
    fg.language('en')
    fg.title(f'Talks By {speaker}')
    fg.link(href='http://speakercast.net/')
    fg.description(f'General Conference talks by {speaker}.')
    fg.author({'name':'Philip Lundrigan', 'email':'philiplundrigan@gmail.com'})
    fg.generator('Speakercast')
    fg.pubDate(now)
    fg.podcast.itunes_category('Religion & Spirituality', 'Christianity')

    for talk in talks:
        fe = fg.add_entry()
        fe.id('http://lernfunk.de/media/654321/1/file.mp3')
        fe.title(talk['title'])
        fe.description(talk['preview'])
        fe.enclosure(talk['audio_url'], str(talk['audio_size']), 'audio/mpeg')
        fe.id(talk['uri'])
        fe.link(href=talk['url'])
        fe.published(talk['time'])

    fg.rss_file(file_name, pretty=True)


def _create_cover(speaker, file_name):
    LOGGER.info("Creating cover for %s", speaker)
    text = f'Talks By\n{speaker}'
    spacing = 80

    img = Image.open(os.path.join("assets", "images", "cover.jpg"))
    img = img.convert('RGBA')

    layer = Image.new('RGBA', img.size, (0,0,0,0))

    draw = ImageDraw.Draw(layer)
    font = ImageFont.truetype(os.path.join("assets", "Montserrat-Regular.ttf"), 160)

    # Keep adding newlines until text fits
    size = draw.multiline_textsize(text, font=font, spacing=spacing)
    while size[0] > img.size[0]:
        text = '\n'.join(text.rsplit(' ', 1))
        size = draw.multiline_textsize(text, font=font, spacing=spacing)

    # Center text
    x, y = (img.size[0] - size[0]) / 2, (img.size[1] - size[1]) / 2

    # Draw box under text
    draw.rectangle(((0, y), (img.size[0] + 25, y + size[1])), fill=(255, 255, 255, 200))

    # Draw
    draw.multiline_text((x, y),
                        text=text,
                        fill=(0, 0, 0),
                        font=font,
                        spacing=spacing,
                        align="center")

    test = Image.composite(layer, img, layer)
    test.save(file_name)


def _create_feed_and_cover(speaker, talks, feed_folder, cover_folder):
    _create_feed(speaker,
                 sorted(talks, key=lambda x: x['time']),
                 os.path.join(feed_folder, f'{speaker}.rss'))

    # Only generate a cover if one has not been created
    cover_name = os.path.join(cover_folder, f'{speaker}.jpg')
    if not os.path.isfile(cover_name):
        _create_cover(speaker, cover_name)


def _create_template_data(speakers):
    data = [{'name': speaker, 'count': len(talks)}
            for speaker, talks in speakers.items()]

    with open('assets/data.json', 'w') as f:
        json.dump(data, f)


def generate_feeds(start=(1971, 4), end=None):
    if end is None:
        end = (date.today().year, date.today().month)

    if current_catalog_version() == _feed_version():
        LOGGER.info("Feeds are already up to date")
        return

    catalog = CatalogDB()

    with ThreadPoolExecutor(max_workers=10) as executor:
        gen = executor.map(lambda x: _get_talks(catalog, x[0], x[1]),
                           _get_month_year(start, end))

        talks = list(itertools.chain(*gen))

    # Combine all data together into one dict
    LOGGER.info("Processing data")
    speakers = defaultdict(list)
    for talk in talks:
        speakers[talk['speaker']].append(talk)

    # Make sure the necessary folder exist
    feed_folder = 'feeds'
    cover_folder = 'covers'
    if not os.path.exists(feed_folder):
        os.makedirs(feed_folder)

    if not os.path.exists(cover_folder):
        os.makedirs(cover_folder)

    # Start a bunch of process workers
    # (this work is CPU bound so processes are needed)
    with ProcessPoolExecutor(max_workers=8) as executor:
        fs = [executor.submit(_create_feed_and_cover, speaker, talks, feed_folder, cover_folder)
              for speaker, talks in speakers.items()]
        wait(fs)

    _create_template_data(speakers)

    _feed_version(current_catalog_version())


if __name__ == '__main__':
    generate_feeds()
