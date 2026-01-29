import gefolge_web.login
import gefolge_web.util

def setup(index):
    @index.child('games', 'Spiele')
    @gefolge_web.login.mensch_required
    def games_index():
        raise NotImplementedError('Ported to Rust')

    return games_index # needs to be passed to Werewolf submodule as path parent
