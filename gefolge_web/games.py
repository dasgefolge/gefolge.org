import gefolge_web.login
import gefolge_web.util

def setup(index):
    @index.child('games', 'Spiele', decorators=[gefolge_web.login.member_required])
    @gefolge_web.util.template('games-index')
    def games_index():
        return {}

    return games_index # needs to be passed to Werewolf submodule as path parent
