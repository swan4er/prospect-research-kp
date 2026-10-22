"""Ролики из RSS YouTube-канала (последние 15): по строке JSON на ролик.

python3 -I yt_rss.py feed.xml
Фид: https://www.youtube.com/feeds/videos.xml?channel_id=UC…
"""
import html
import json
import re
import sys

feed = open(sys.argv[1], encoding='utf-8', errors='replace').read()
for entry in re.findall(r'<entry>(.*?)</entry>', feed, re.S):
    desc = re.search(r'<media:description>(.*?)</media:description>', entry, re.S)
    desc = html.unescape(desc.group(1)) if desc else ''
    views = re.search(r'views="(\d+)"', entry)
    likes = re.search(r'<media:starRating count="(\d+)"', entry)
    print(json.dumps({
        'date': re.search(r'<published>([^<]+)</published>', entry).group(1)[:10],
        'id': re.search(r'<yt:videoId>([^<]+)</yt:videoId>', entry).group(1),
        'title': html.unescape(re.search(r'<title>([^<]*)</title>', entry).group(1)),
        'views': int(views.group(1)) if views else None,
        'likes': int(likes.group(1)) if likes else None,
        # порядок сохранён: по нему видно, какие ссылки появились, пропали или переехали наверх
        'links': re.findall(r'https?://[^\s)]+', desc),
        'description': desc,
    }, ensure_ascii=False))
