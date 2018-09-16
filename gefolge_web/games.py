import gefolge_web.login
import gefolge_web.util

def setup(index):
    @index.child('games', 'Spiele')
    @gefolge_web.login.member_required
    @gefolge_web.util.template('games-index')
    def games_index():
        return {}

    @games_index.child('space-alert', 'Space Alert')
    @gefolge_web.login.member_required
    @gefolge_web.util.template('space-alert-index')
    def space_alert():
        return {}

    @space_alert.child('scan', 'Hirnscans')
    @gefolge_web.login.member_required
    @gefolge_web.util.template('brainscans-index')
    def brainscans_index():
        return {}

    return games_index # needs to be passed to Werewolf submodule as path parent
