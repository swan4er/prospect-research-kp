"""Текст и ссылки страницы: заголовки помечены [H1]…[H4], кнопки — [BTN], картинки — [IMG:alt].

python3 -I site_text.py page.html
"""
import re
import sys
from html.parser import HTMLParser

SKIP = ('script', 'style', 'noscript', 'svg')
BLOCK = ('p', 'div', 'li', 'br', 'section', 'button', 'footer', 'header')


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.out = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in SKIP:
            self.skip += 1
        if tag == 'a' and a.get('href'):
            self.links.append(a['href'])
        if tag in ('h1', 'h2', 'h3', 'h4'):
            self.out.append('\n\n[%s] ' % tag.upper())
        if tag in BLOCK:
            self.out.append('\n')
        if tag == 'button':
            self.out.append('[BTN] ')
        if tag == 'img' and a.get('alt'):
            self.out.append(' [IMG:%s] ' % a['alt'])

    def handle_endtag(self, tag):
        if tag in SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


page = Page()
page.feed(open(sys.argv[1], encoding='utf-8', errors='replace').read())
text = re.sub(r'[ \t\xa0]+', ' ', ''.join(page.out))
print(re.sub(r'\n\s*\n+', '\n', text).strip())
print('\n=====LINKS=====')
print('\n'.join(dict.fromkeys(page.links)))
