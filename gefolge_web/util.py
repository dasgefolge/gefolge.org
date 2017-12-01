import flask
import functools

def template(template_name=None):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if template_name is None:
                template_path = '{}.html'.format(flask.request.endpoint.replace('.', '/'))
            else:
                template_path = '{}.html'.format(template_name.replace('.', '/'))
            context = f(*args, **kwargs)
            if context is None:
                context = {}
            elif not isinstance(context, dict):
                return context
            return flask.render_template(template_path, **context)

        return wrapper

    return decorator
