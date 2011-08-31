import feedparser
import logging
import urllib
import zlib

from django.utils import simplejson
from google.appengine.api import app_identity
from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.api import urlfetch
from google.appengine.ext import webapp

class SubCallbackPage(webapp.RequestHandler):
  def get(self):
    if self.request.get('hub.challenge'):
      logging.debug('cb %s' % self.request.get('hub.challenge'))
      self.response.headers['Content-Type'] = 'text/plain'
      self.response.out.write(self.request.get('hub.challenge'))

  def strip_entry(self, entry):
    return entry

  def get_payload(self):
    """Do a first-pass removal of messages we already know about."""
    feed = feedparser.parse(self.request.body)
    entries = feed['entries']
    entries_to_send = []
    for entry in entries:
      if not memcache.get(entry['id']):
        memcache.set(entry['id'], 1)
        entries_to_send.append(self.strip_entry(entry))

    return simplejson.dumps(entries_to_send)

  def post(self):
    taskqueue.add(url='/newdata', payload=zlib.compress(self.get_payload()))
    self.response.out.write('ok')


def set_subscribe_state(topic_url, callback_url, hub_url, secret, mode):
  hostname = app_identity.get_default_version_hostname()
  post_fields = {
    'hub.callback': 'http://' + hostname + '/subcb?url=http://www.dailymile.com/entries.atom',
    'hub.mode': mode,
    'hub.topic': topic_url,
    'hub.verify': 'async',
    'hub.verify_token': 'tokentokentoken'
  }
  url = 'http://pubsubhubbub.appspot.com'
  response = urlfetch.fetch(url, method=urlfetch.POST,
                              payload=urllib.urlencode(post_fields))
  logging.debug('%s (%s): %d: %s' % (url, str(post_fields), response.status_code, response.content))

def subscribe(topic_url, callback_url, hub_url, secret):
  logging.debug('Subscribing with callback %s' % callback_url)
  set_subscribe_state(topic_url, callback_url, hub_url, secret, 'subscribe')

def unsubscribe(topic_url, callback_url, hub_url, secret):
  logging.debug('Unsubscribing.')
  set_subscribe_state(topic_url, callback_url, hub_url, secret, 'unsubscribe')
