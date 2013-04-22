#!/usr/bin/python

import re
import datetime
import optparse

APRIL = 4
OCTOBER = 10


def enum(**enums):
    return type('Enum', (), enums)

media_types = enum(AUDIO="audio", VIDEO_LOW="low", VIDEO_HIGH="high")


class Talk():
    def __init__(self, title, description, url, media_url, date):
        self.title = title
        self.description = description
        self.url = url
        self.media_url = media_url
        self.date = date

    def get_title(self):
        return self.title

    def set_title(self, title):
        self.title = title

    def get_description(self):
        return self.description

    def set_description(self, description):
        self.description = description

    def get_url(self):
        return self.url

    def set_url(self, url):
        self.url = url

    def get_media_url(self):
        return self.media_url

    def set_media_url(self, media_url):
        self.media_url = media_url

    def get_date(self):
        return self.date

    def set_date(self, date):
        self.date = date


class TalkFeed():
    def __init__(self, speaker, media=media_types.AUDIO, start_year=1971,
                 end_year=datetime.date.today().year, file_name="feed.rss",
                 quiet=False):
        self.speaker = speaker
        self.media = media
        self.start_year = start_year
        self.end_year = end_year
        self.file_name = file_name
        self.quiet = quiet

        self.url = "https://www.lds.org/general-conference/sessions/" + \
                   "{year}/{month:02}?lang=eng"

    def __get_talks(self):
        if not self.quiet:
            print "Finding talks for {speaker}\n".format(speaker=self.speaker)

        talks = []
        for year in range(self.start_year, self.end_year+1):
            for month in [APRIL, OCTOBER]:
                if year == datetime.date.today().year and month > datetime.date.today().month:
                    break

                url = self.url.format(year=year, month=month)

                if not self.quiet:
                    print u"Downloading {month} {year} Conference".format(month="April" if month == APRIL else "October",
                                                                          year=year)

                page = Downloader().download_page(url)
                parser = TalkParser(page, self.speaker, self.media)

                talks += self.__create_talks(parser, year, month)

                if not self.quiet:
                    print

        return talks

    def __create_talks(self, parser, year, month):
        talks = parser.get_talks()

        for talk in talks:
            if not self.quiet:
                print u"\tFound talk titled: {title}".format(title=talk.get_title())
            talk.set_date(datetime.datetime(year, month, 1, 15))

        return talks

    def create_feed(self):
        talks = self.__get_talks()

        rss = RSSer(
            speaker=self.speaker,
            title="General Conference Talks Given by {0}".format(self.speaker),
            description="Talks given by {speaker} ({media})".format(speaker=self.speaker,
                                                                    media="audio" if self.media == media_types.AUDIO else "video"),
            url="http://www.lds.org/general-conference",
            talks=talks,
            media=self.media
        )

        if not self.quiet:
            print "Saving {0} feed as {1}".format("audio" if self.media == media_types.AUDIO else "video",
                                                  self.file_name)

        rss.create(open(self.file_name, 'w+'))


class Downloader():
    def download_page(self, url):
        from urllib import urlopen

        return urlopen(url).read().decode('utf-8')


class TalkParser():
    def __init__(self, data, speaker, media):
        self.data = data
        self.speaker = speaker
        self.media = media

        self.speaker_data = self.__get_speaker_data()

    def get_talks(self):
        talks = []
        for talk in self.speaker_data:
            talks.append(
                Talk(
                    title=self.__get_title(talk),
                    description=self.__get_description(talk),
                    url=self.__get_url(talk),
                    media_url=self.__get_media_url(talk),
                    date=self.__get_date(talk)
                )
            )

        return talks

    def __get_speaker_data(self):
        speakers = re.findall("<tr>.*?</tr>", self.data, re.S)

        speaker_data = []
        for s in speakers:
            # removing nbsp
            s = s.replace(u'\xa0', ' ')

            if s.find(self.speaker) != -1:
                speaker_data.append(s)

        return speaker_data

    def __get_title(self, talk):
        title_html = re.search("<span class=\"talk\"><a href=\".*?\">.*?</a></span>",
                               talk,
                               re.S).group()

        m = re.search("(<span class=\"talk\">)" +
                      "(<a href=\".*?\">)" +
                      "(.*?)" +
                      "(</a></span>)", title_html, re.S)

        return m.group(3)

    def __get_media_url(self, talk):
        audio_url = re.search("\"(https?://\\S*?\\.mp3\\S*?)\"", talk, re.S)
        video_1080_url = re.search("\"(https?://\\S*?-1080p-\\S*?\\.mp4\\S*?)\"", talk, re.S)
        video_720_url = re.search("\"(https?://\\S*?-720p-\\S*?\\.mp4\\S*?)\"", talk, re.S)
        video_480_url = re.search("\"(https?://\\S*?-480p-\\S*?\\.mp4\\S*?)\"", talk, re.S)
        video_360_url = re.search("\"(https?://\\S*?-360p-\\S*?\\.mp4\\S*?)\"", talk, re.S)

        audio_url = audio_url.group(1) if audio_url is not None else None
        video_1080_url = video_1080_url.group(1) if video_1080_url is not None else None
        video_720_url = video_720_url.group(1) if video_720_url is not None else None
        video_480_url = video_480_url.group(1) if video_480_url is not None else None
        video_360_url = video_360_url.group(1) if video_360_url is not None else None

        if self.media == media_types.AUDIO:
            return audio_url

        elif self.media == media_types.VIDEO_LOW:
            return video_360_url or video_480_url or video_720_url or video_1080_url

        elif self.media == media_types.VIDEO_HIGH:
            return video_1080_url or video_720_url or video_480_url or video_360_url

        else:
            print "We have a problem! Media type is not recognized. Exiting..."
            exit()

    def __get_url(self, talk):
        title_html = re.search("<span class=\"talk\"><a href=\".*?\">.*?</a></span>",
                               talk,
                               re.S).group()

        m = re.search("(<span class=\"talk\">)" +
                      "<a href=\"(.*?)\">" +
                      "(.*?)" +
                      "(</a></span>)", title_html, re.S)

        return m.group(2)

    def __get_description(self, talk):
        link = self.__get_url(talk)
        page = Downloader().download_page(link)
        m = re.search("<div class=\"kicker\" id=\"\">(.*?)</div>", page, re.S)

        if m is None:
            m = re.search("/(\\d{4})/(\\d{2})/", link, re.S)
            year = m.group(1)
            month = m.group(2)

            return "Talk given {month} {year} Conference".format(month="April" if month == "04" else "October",
                                                                 year=year)

        return m.group(1)

    def __get_date(self, talk):
        pass


class RSSer():
    def __init__(self, speaker, title, description, url, talks, media):
        self.speaker = speaker
        self.title = title
        self.description = description
        self.url = url
        self.talks = talks
        self.media = media

    def create(self, file):
        import PyRSS2Gen

        items = []

        for talk in self.talks:
            items.append(PyRSS2Gen.RSSItem(
                title=talk.get_title(),
                link=talk.get_url(),
                description=talk.get_description(),
                guid=PyRSS2Gen.Guid(talk.get_url(), False),
                pubDate=talk.get_date(),
                enclosure=PyRSS2Gen.Enclosure(talk.get_media_url(),
                                              0,
                                              "audio/mpeg" if self.media == media_types.AUDIO else "video/mp4")
            ))

        rss = PyRSS2Gen.RSS2(
            title=self.title,
            link=self.url,
            description=self.description,
            lastBuildDate=datetime.datetime.now(),
            items=items
        )

        rss.write_xml(file)

if __name__ == '__main__':
    parser = optparse.OptionParser(usage='%prog -s "speaker name" [-o out_file] '
                                         '[--start=start_year] [--end=end_year] '
                                         '[-v low|high] [-qa]', version="%prog 1.0")

    parser.add_option('-s', '--speaker', type='string',
                      help='Speaker you want to make the feed for. '
                      'Typically, the more specific you can be the better so '
                      'that no false positives arise. '
                      'For example, rather than putting "Holland", it would '
                      'be better to put "Jeffrey R. Holland".')

    parser.add_option('-o', '--out', type='string', dest='file_name', default="feed.rss",
                      help='Output file name')

    parser.add_option('--start', type='int', dest='start_year', default=1971,
                      help='Start year')

    parser.add_option('--end', type='int', dest='end_year', default=datetime.date.today().year,
                      help='End year')

    parser.add_option('-q', '--quiet', action="store_true", default=False,
                      help='Silence all print outs')

    parser.add_option('-a', '--audio', action="store_true", default=True,
                      help='Get the audio for all talks (default)')

    parser.add_option('-v', '--video', choices=['low', 'high'],
                      help='Get the video for all talks. '
                           'There are two choices for quality of video: "low" or "high". '
                           'Low is a good choice for handheld devices. '
                           'This will override the audio flag if both are provided.')

    (options, args) = parser.parse_args()

    speaker = options.speaker
    file_name = options.file_name
    start_year = options.start_year
    end_year = options.end_year
    quiet = options.quiet
    audio = options.audio
    video = options.video

    media = media_types.AUDIO

    if not speaker:
        parser.print_help()
        exit()

    if video == 'low':
        media = media_types.VIDEO_LOW
    elif video == 'high':
        media = media_types.VIDEO_HIGH

    TalkFeed(
        speaker=speaker,
        media=media,
        start_year=start_year,
        end_year=end_year,
        file_name=file_name,
        quiet=quiet
    ).create_feed()
