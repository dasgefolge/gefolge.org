import flask
import markdown
import markdown.inlinepatterns
import markdown.util
import pathlib
import re

import gefolge_web.login
import gefolge_web.util

DISCORD_TAG_REGEX = r'@([^#]{2,32})#([0-9]{4}?)'
DISCORD_MENTION_REGEX = r'<@!?([0-9]+)>'

WIKI_ROOT = gefolge_web.util.BASE_PATH / 'wiki'

class DiscordMentionPattern(markdown.inlinepatterns.LinkInlineProcessor):
    def handleMatch(self, m, data):
        mensch = gefolge_web.login.Mensch(m.group(1))
        el = markdown.util.etree.Element('a')
        el.text = '@{}'.format(mensch.name)
        el.set('href', flask.url_for('profile', mensch=str(mensch.snowflake)))
        return el, m.start(0), m.end(0)

class DiscordMentionExtension(markdown.Extension):
    def extendMarkdown(self, md, md_globals):
        config = self.getConfigs()
        md.inlinePatterns.add('discord-mention', DiscordMentionPattern(DISCORD_MENTION_REGEX, md), '<reference')

def setup(index, md):
    md.register_extension(DiscordMentionExtension)

    @index.child('wiki', decorators=[gefolge_web.login.member_required])
    @gefolge_web.util.template('wiki-index')
    def wiki_index():
        {}

    @wiki_index.children()
    @gefolge_web.util.template('wiki')
    def wiki_article(article_name):
        source = get_article_source('wiki', article_name)
        if source is None:
            return gefolge_web.util.render_template('wiki-404', article_name=article_name), 404
        return {
            'article_name': article_name,
            'article_namespace': 'wiki',
            'article_source': source
        }

def get_article_source(namespace, article_name):
    article_path = WIKI_ROOT / namespace / '{}.md'.format(article_name)
    if article_path.exists():
        with article_path.open() as article_f:
            return article_f.read()

def mentions_to_tags(text):
    while True:
        match = re.search(DISCORD_MENTION_REGEX, text)
        if not match:
            return text
        text = '{}@{}{}'.format(text[:match.start()], gefolge_web.login.Mensch(match.group(1)), text[match.end():])

def tags_to_mentions(text):
    while True:
        match = re.search(DISCORD_TAG_REGEX, text)
        if not match:
            return text
        text = '{}<@{}>{}'.format(text[:match.start()], gefolge_web.login.Mensch.by_tag(match.group(1), int(match.group(2))).snowflake, text[match.end():])
