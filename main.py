import os

from flask import Flask
from flask import redirect
from flask import render_template
from flask import request
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import jwt
from opencensus.ext.flask.flask_middleware import FlaskMiddleware
from opencensus.ext.stackdriver import trace_exporter as stackdriver_exporter
from opencensus.trace import config_integration
from opencensus.trace.execution_context import get_current_span
from opencensus.trace.tracer import Tracer
from opencensus.trace.samplers import AlwaysOnSampler


DEFAULT_GUESTBOOK_NAME = 'default_guestbook'
JWT_HEADER = 'X-Goog-IAP-JWT-Assertion'

app = Flask(__name__)

# Setup tracing.
config_integration.trace_integrations(['google_cloud_clientlibs'])
middleware = FlaskMiddleware(
    app,
    sampler=AlwaysOnSampler(),
    exporter=stackdriver_exporter.StackdriverExporter()
)

# Initialize Firestore client.
cred = credentials.ApplicationDefault()
firebase_admin.initialize_app(cred)
db = firestore.client()


@app.route('/')
def get():
    guestbook_name = request.args.get('guestbook_name', DEFAULT_GUESTBOOK_NAME)
    greetings = _trace(_get_greetings, guestbook_name)

    user = _trace(_get_user)
    if user:
        url = '/_gcp_iap/clear_login_cookie'
        url_linktext = 'Logout'
    else:
        url = '/'
        url_linktext = 'Login'

    template_values = {
        'user': user,
        'greetings': greetings,
        'guestbook_name': guestbook_name,
        'url': url,
        'url_linktext': url_linktext,
    }

    return _trace(render_template, 'index.html', **template_values)


@app.route('/sign', methods=['POST'])
def post():
    guestbook_name = request.args.get('guestbook_name', DEFAULT_GUESTBOOK_NAME)
    author = _trace(_get_user)
    content = request.form.get('content')
    _trace(_save_greeting, guestbook_name, author, content)
    return _trace(redirect, '/?guestbook_name=' + guestbook_name)


@app.route('/_ah/warmup')
def warmup():
    pass


def _get_user():
    # Rely on user identity from Identity-Aware Proxy.
    token = request.headers.get(JWT_HEADER)
    if not token:
        return None
    return jwt.decode(token, verify=False).get('email')


def _save_greeting(guestbook_name, author, content):
    # Save greeting to Firestore.
    db.collection('guestbooks') \
        .document(guestbook_name) \
        .collection('greetings') \
        .document() \
        .set({
            'author': author,
            'content': content,
            'date': firestore.SERVER_TIMESTAMP,
        })


def _get_greetings(guestbook_name):
    # Fetch guestbook greetings from Firestore.
    greetings_stream = db \
        .collection('guestbooks') \
        .document(guestbook_name) \
        .collection('greetings') \
        .order_by('date', direction=firestore.Query.DESCENDING) \
        .limit(10) \
        .stream()
    return [greeting for greeting in greetings_stream]


def _trace(func, *args, **kwargs):
    with get_current_span().span(name=func.__name__):
        return func(*args, **kwargs)


if __name__ == '__main__':
    # This is used when running locally only. When deploying to Google App
    # Engine, a webserver process such as Gunicorn will serve the app. This
    # can be configured by adding an `entrypoint` to app.yaml.
    app.run(host='127.0.0.1', port=8080, debug=True)
