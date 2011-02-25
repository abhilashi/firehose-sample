import feedparser
import logging
import urllib
import os

from datetime import datetime
from datetime import timedelta
from django.utils import simplejson
from google.appengine.api import channel
from google.appengine.ext import db
from google.appengine.api import memcache
from google.appengine.api import urlfetch
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app


class Client(db.Model):
    name = db.StringProperty(required=True)
    created = db.TimeProperty(required=True)


class SubCallbackPage(webapp.RequestHandler):
  def get(self):
    if self.request.get('hub.challenge'):
      self.response.out.write(self.request.get('hub.challenge'))      

  def post(self):
    feed = feedparser.parse(self.request.body)
    person_url = feed['entries'][0]['authors'][0]['href'] + '.json'
    logging.debug("Person_url: %s" % person_url)
    response = urlfetch.fetch(person_url)
    logging.debug("Response (%d): %s" % (response.status_code, response.content))
    if response.content:
      person = simplejson.loads(response.content)
      if 'location' not in person:
        return
      url = 'http://maps.googleapis.com/maps/api/geocode/json?%s' % urllib.urlencode({'address': person['location'], 'sensor': 'false'})
      logging.debug(url)
      response = urlfetch.fetch(url)
      logging.debug("Response (%d): %s" % (response.status_code, response.content))
      if response.content:
        loc = simplejson.loads(response.content)
        message = {
          'entry': feed['entries'][0]['title'],
          'person': person,
          'latlng': loc['results'][0]['geometry']['location']
          }
        channel.send_message('client', simplejson.dumps(message))

    self.response.out.write('ok')


class SubscribePage(webapp.RequestHandler):
  def get(self):
    post_fields = {
      'hub.callback': 'http://firehose-sample.appspot.com/subcb?url=http://www.dailymile.com/entries.atom',
      'hub.mode': 'subscribe',
      'hub.topic': 'http://www.dailymile.com/entries.atom',
      'hub.verify': 'async',
      'hub.verify_token': 'tokentokentoken'
    }
    url = 'http://pubsubhubbub.appspot.com/'
    result = urlfetch.fetch (url, payload=post_fields)
    self.response.out.write(result.status_code)
    self.response.out.write(result.content)
#    path = os.path.join(os.path.dirname(__file__), 'index.html')
#    self.response.headers['Content-Type'] = 'text/html'
#    self.response.out.write(template.render(path, {}))


class MainPage(webapp.RequestHandler):
  def get(self):
    if 'token' in self.request.cookies:
      token = self.request.cookies['token']
      logging.debug('Using existing token: %s' % token)
    else:
      token = channel.create_channel('client')
      expiration = (datetime.utcnow() + timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
      self.response.headers.add_header('Set-Cookie', 'token=%s; expires=%s' % (token, expiration))
      logging.warning('Created token: %s, expires %s' % (token, expiration))
    path = os.path.join(os.path.dirname(__file__), 'index.html')
    self.response.out.write(template.render(path, {'token': token}));


application = webapp.WSGIApplication(
        [('/', MainPage),
         ('/sub', SubscribePage),
         ('/subcb', SubCallbackPage)],
        debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
