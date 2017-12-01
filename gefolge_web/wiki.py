import flask
import markdown
import markdown.inlinepatterns
import markdown.util
import pathlib

import gefolge_web.login

DISCORD_TAG_REGEX = r'@([^#]{2,32})#([0-9]{4}?)'
DISCORD_MENTION_REGEX = r'<@!?([0-9]+)>'

WIKI_ROOT = pathlib.Path('/usr/local/share/fidera/wiki')

class DiscordMentionPattern(markdown.inlinepatterns.LinkPattern):
    def handle_match(self, m):
        mensch = gefolge_web.login.Mensch(m.group(1))
        el = markdown.util.etree.Element('a')
        el.text = '@{}'.format(mensch.name)
        el.set('href', flask.url_for('profile', snowflake=str(mensch.snowflake)))
        return el

class DiscordMentionExtension(markdown.Extension):
    def extendMarkdown(self, md, md_globals):
        config = self.getConfigs()
        md.inlinePatterns.add('discord-mention', DiscordMentionPattern(DISCORD_MENTION_REGEX, md), '<reference')

def setup(app, md):
    md.register_extension(DiscordMentionExtension)

    @app.route('/wiki/<article_name>')
    @gefolge_web.login.member_required
    @gefolge_web.util.template('wiki')
    def wiki_article(article_name):
        return {
            'article_name': article_name,
            'article_namespace': 'wiki',
            'article_source': get_article_source('wiki', article_name)
        }

def get_article_source(namespace, article_name):
    article_path = WIKI_ROOT / namespace / '{}.md'.format(article_name)
    if article_path.exists():
        with article_path.open() as article_f:
            return article_f.read()
