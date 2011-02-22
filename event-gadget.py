import feedparser
import logging
import os

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
    channel.send_message('client', feed['entries'][0]['title'])
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
    token = channel.create_channel('client')
    logging.warning('Created token: %s' % token)
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
