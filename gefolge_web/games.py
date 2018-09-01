import gefolge_web.login
import gefolge_web.util

def setup(app):
    @app.route('/games')
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('games', 'Spiele'))
    @gefolge_web.util.template('games-index')
    def games_index():
        return {}

    @app.route('/games/space-alert')
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('space-alert', 'Space Alert'), games_index)
    @gefolge_web.util.template('space-alert-index')
    def space_alert():
        return {}

    @app.route('/games/space-alert/scan')
    @gefolge_web.login.member_required
    @gefolge_web.util.path(('scan', 'Hirnscans'), space_alert)
    @gefolge_web.util.template('brainscans-index')
    def brainscans_index():
        return {}

    return games_index # needs to be passed to Werewolf submodule as path parent
