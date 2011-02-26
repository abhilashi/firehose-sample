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


TOPIC_URL = 'http://www.dailymile.com/entries.atom'


class Client(db.Model):
    created = db.DateTimeProperty(required=True, auto_now=True, auto_now_add=True)

    
class People():
  def get_person(self, person_entry):
    person_url = person_entry['href']
    person = memcache.get(person_url)
    if not person:
      response = urlfetch.fetch(person_url + '.json')
      if response.status_code != 200:
        return None
      
      person = simplejson.loads(response.content)
      memcache.add(person_url, person, 24 * 60 * 60)
    return person


class Locations():
  MAP_URL_TEMPLATE = 'http://maps.googleapis.com/maps/api/geocode/json?%s'
  
  def get_latlong(self, location):
    latlong = memcache.get(location)
    if not latlong:
      if isinstance(location, unicode):
        location = location.encode('utf-8')
      url = Locations.MAP_URL_TEMPLATE % urllib.urlencode({'address': location, 
                                                           'sensor': 'false'})
      response = urlfetch.fetch(url)
      if response.status_code != 200:
        return None      
      geocode_data = simplejson.loads(response.content)
      if geocode_data['status'] == 'OK':
        latlong = geocode_data['results'][0]['geometry']['location']
        memcache.add(location, latlong)
    return latlong
  
  
class Messages():
  def messages_from_entries(self, entries, use_cache):
    messages = []
    for entry in entries:
      if use_cache and memcache.get(entry['id']):
        continue

      if use_cache: 
        memcache.add(entry['id'], 'seen')
        
      person = People().get_person(entry['authors'][0])        
      if person and 'location' in person:
        latlong = Locations().get_latlong(person['location'])
      else:
        latlong = None
      messages.append({
        'entry': entry['title'],
#        'entry-content': entry['content'][0]['value'],
        'photo-url': '',
        'latlng': latlong,
        'id': entry['id']
        })
    return messages    
  
  def get_initial_messages(self, mock=False):
    if mock:
      feed = feedparser.parse(MOCK_FEED)
    else:
      result = urlfetch.fetch(TOPIC_URL)
      if result.status_code == 200:
        feed = feedparser.parse(result.content)
    if feed:
      return self.messages_from_entries(feed['entries'], False)
    else:
      return []
  
  
class Clients():
  def add_client(self):
    client = Client()
    db.put(client)
    logging.warning(client.created)
    return channel.create_channel('client')

  def broadcast_message(self, message):
    logging.debug('sending (%s) to client (%s)' % (message, 'client'))
    channel.send_message('client', message)

  def update_clients(self, text, use_cache=True, client=None):
    feed = feedparser.parse(text)
    entries = feed['entries']
    messages = Messages().messages_from_entries(entries, use_cache)
    if client:
      channel.send_message(client, simplejson.dumps(messages))
    else:
      self.broadcast_message(simplejson.dumps(messages))


class SubCallbackPage(webapp.RequestHandler):
  def get(self):
    if self.request.get('hub.challenge'):
      self.response.out.write(self.request.get('hub.challenge'))

  def post(self):
    Clients().update_clients(text)
    self.response.out.write('ok')
    
class MockPage(webapp.RequestHandler):
  def get(self):
    # for dev appserver, make sure the channel's created and not just re-using
    # a token from a cookie.
    feed = feedparser.parse(MOCK_FEED)
    Clients().update_clients(feed['entries'])
    self.response.out.write(len(feed['entries']))

class SubscribePage(webapp.RequestHandler):
  def get(self):
    post_fields = {
      'hub.callback': 'http://firehose-sample.appspot.com/subcb?url=http://www.dailymile.com/entries.atom',
      'hub.mode': 'subscribe',
      'hub.topic': TOPIC_URL,
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


class GetSeedMessages(webapp.RequestHandler):
  def post(self):
    messages = simplejson.dumps(Messages().get_initial_messages(self.request.get('mock') == '1'))
    memcache.add('initial_messages', initial_messages, 60)
    self.response.out.write(messages)


class MainPage(webapp.RequestHandler):
  def get(self):
    if (not self.request.get('nt')) and ('token' in self.request.cookies):
      token = self.request.cookies['token']
    else:
      token = Clients().add_client()
      expiration = (datetime.utcnow() + timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
      self.response.headers.add_header('Set-Cookie', 'token=%s; expires=%s' % (token, expiration))
      logging.warning('Created token: %s, expires %s' % (token, expiration))

    initial_messages = memcache.get('initial_messages')
    if not initial_messages:
      initial_messages = '[]'
    path = os.path.join(os.path.dirname(__file__), 'index.html')
    self.response.out.write(template.render(path, {'token': token, 'initial_messages': initial_messages}));


application = webapp.WSGIApplication(
        [('/', MainPage),
         ('/mock', MockPage),
         ('/seed', GetSeedMessages),
         ('/sub', SubscribePage),
         ('/subcb', SubCallbackPage)],
        debug=True)

def main():
  run_wsgi_app(application)
  
MOCK_FEED = """
<?xml version="1.0" encoding="UTF-8"?>
<feed xml:lang="en-US" xmlns="http://www.w3.org/2005/Atom" xmlns:activity="http://activitystrea.ms/spec/1.0/" xmlns:media="http://example.com/to-be-confirmed" xmlns:thr="http://purl.org/syndication/thread/1.0">
  <id>tag:www.dailymile.com,2005:/entries</id>
  <link rel="alternate" type="text/html" href="http://www.dailymile.com"/>
  <link rel="self" type="application/atom+xml" href="http://www.dailymile.com/entries.atom"/>
  <title>dailymile Public Feed</title>
  <updated>2011-02-25T20:29:57Z</updated>
  <generator uri="http://www.dailymile.com/">dailymile</generator>
  <icon>http://www.dailymile.com/favicon.ico</icon>
  <link rel="hub" href="http://pubsubhubbub.appspot.com/"/>
  <entry>
    <id>tag:www.dailymile.com,2010:/entries/5578775</id>
    <published>2011-02-25T12:29:57-08:00</published>
    <updated>2011-02-25T12:29:57-08:00</updated>
    <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/NatalieA/entries/5578775"/>
    <title type="text">Natalie posted a workout</title>
    <category term="http://schemas.dailymile.com/entry#workout"/>
    <link rel="replies" type="applicaton/xhtml+xml" thr:count="0" href="http://www.dailymile.com/people/NatalieA/entries/5578775#comments"/>
    <activity:verb>http://activitystrea.ms/schema/1.0/post/</activity:verb>
    <activity:object>
      <id>tag:www.dailymile.com,2010:workout/5578775</id>
      <title type="text">Natalie ran for 40 hours</title>
      <published>2011-02-25T12:29:57-08:00</published>
      <activity:object-type>http://activitystrea.ms/schema/1.0/workout</activity:object-type>
      <content type="xhtml">
<span class="workout-feeling good">good</span>
<a href="/people/NatalieA/entries/5578775" class="workout-title">gym</a>
  <span class="workout-time">40:00</span>

<div class="entry-description">
  <p>20 min run, 6 x 1:00 sprints, 10 min run. treadmills are not as fun as running outside...</p>
</div>      </content>
    </activity:object>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
<span class="workout-activity-type">Running</span><span class="workout-feeling good">good</span>
<a href="/people/NatalieA/entries/5578775" class="workout-title">gym</a>
  <span class="workout-time">40:00</span>

<div class="entry-description">
  <p>20 min run, 6 x 1:00 sprints, 10 min run. treadmills are not as fun as running outside...</p>
</div>      </div>
    </content>
    <author>
      <activity:object-type>http://activitystrea.ms/schema/1.0/person</activity:object-type>
      <name>Natalie</name>
      <uri>http://www.dailymile.com/people/NatalieA</uri>
      <link rel="photo" type="image/jpeg" href="http://s1.dmimg.com/pictures/users/51747/1266334372_avatar.jpg"/>
      <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/NatalieA"/>
    </author>
  </entry>
  <entry>
    <id>tag:www.dailymile.com,2010:/entries/5578774</id>
    <published>2011-02-25T12:29:56-08:00</published>
    <updated>2011-02-25T12:29:56-08:00</updated>
    <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/gillygirl/entries/5578774"/>
    <title type="text">Leigh Ann posted a workout</title>
    <category term="http://schemas.dailymile.com/entry#workout"/>
    <link rel="replies" type="applicaton/xhtml+xml" thr:count="0" href="http://www.dailymile.com/people/gillygirl/entries/5578774#comments"/>
    <activity:verb>http://activitystrea.ms/schema/1.0/post/</activity:verb>
    <activity:object>
      <id>tag:www.dailymile.com,2010:workout/5578774</id>
      <title type="text">Leigh Ann did a fitness workout for 1 hour</title>
      <published>2011-02-25T12:29:56-08:00</published>
      <activity:object-type>http://activitystrea.ms/schema/1.0/workout</activity:object-type>
      <content type="xhtml">
<span class="workout-feeling great">great</span>
<a href="/people/gillygirl/entries/5578774" class="workout-title">Ellipitical machine workout</a>
  <span class="workout-time">01:00</span>

<div class="entry-description">
  <p>At least I can rely on my ellipitical machine when I need a little escape.  I started listening to music again and it is giving my the motivation I need to get through some workouts.</p>
</div>      </content>
    </activity:object>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
<span class="workout-activity-type">Fitness</span><span class="workout-feeling great">great</span>
<a href="/people/gillygirl/entries/5578774" class="workout-title">Ellipitical machine workout</a>
  <span class="workout-time">01:00</span>

<div class="entry-description">
  <p>At least I can rely on my ellipitical machine when I need a little escape.  I started listening to music again and it is giving my the motivation I need to get through some workouts.</p>
</div>      </div>
    </content>
    <author>
      <activity:object-type>http://activitystrea.ms/schema/1.0/person</activity:object-type>
      <name>Leigh Ann G.</name>
      <uri>http://www.dailymile.com/people/gillygirl</uri>
      <link rel="photo" type="image/jpeg" href="http://s1.dmimg.com/pictures/users/111853/1287936213_avatar.jpg"/>
      <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/gillygirl"/>
    </author>
  </entry>
  <entry>
    <id>tag:www.dailymile.com,2010:/entries/5578773</id>
    <published>2011-02-25T12:29:55-08:00</published>
    <updated>2011-02-25T12:29:55-08:00</updated>
    <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/SharonG5/entries/5578773"/>
    <title type="text">Sharon posted a workout</title>
    <category term="http://schemas.dailymile.com/entry#workout"/>
    <link rel="replies" type="applicaton/xhtml+xml" thr:count="0" href="http://www.dailymile.com/people/SharonG5/entries/5578773#comments"/>
    <activity:verb>http://activitystrea.ms/schema/1.0/post/</activity:verb>
    <activity:object>
      <id>tag:www.dailymile.com,2010:workout/5578773</id>
      <title type="text">Sharon walked 2 sec</title>
      <published>2011-02-25T12:29:55-08:00</published>
      <activity:object-type>http://activitystrea.ms/schema/1.0/workout</activity:object-type>
      <content type="xhtml">

<a href="/people/SharonG5/entries/5578773" class="workout-title">Golf Course Upper Route, Walk</a>

<div class="entry-description">
  <p>Started Walk at 12:29 PM, <a href="http://j.mp/fLfumC" rel="nofollow" target="_blank">http://j.mp/fLfumC</a>, Walkmeter will speak your messages to me.</p>
</div>      </content>
    </activity:object>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
<span class="workout-activity-type">Walking</span>
<a href="/people/SharonG5/entries/5578773" class="workout-title">Golf Course Upper Route, Walk</a>

<div class="entry-description">
  <p>Started Walk at 12:29 PM, <a href="http://j.mp/fLfumC" rel="nofollow" target="_blank">http://j.mp/fLfumC</a>, Walkmeter will speak your messages to me.</p>
</div>      </div>
    </content>
    <source>
      <generator uri="http://www.abvio.com/walkmeter">Walkmeter</generator>
    </source>
    <author>
      <activity:object-type>http://activitystrea.ms/schema/1.0/person</activity:object-type>
      <name>Sharon G.</name>
      <uri>http://www.dailymile.com/people/SharonG5</uri>
      <link rel="photo" type="image/jpeg" href="http://www.dailymile.com/images/defaults/user_avatar.jpg"/>
      <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/SharonG5"/>
    </author>
  </entry>
  <entry>
    <id>tag:www.dailymile.com,2010:/entries/5578772</id>
    <published>2011-02-25T12:29:54-08:00</published>
    <updated>2011-02-25T12:29:54-08:00</updated>
    <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/bojo/entries/5578772"/>
    <title type="text">Bojo posted a workout</title>
    <category term="http://schemas.dailymile.com/entry#workout"/>
    <link rel="replies" type="applicaton/xhtml+xml" thr:count="0" href="http://www.dailymile.com/people/bojo/entries/5578772#comments"/>
    <activity:verb>http://activitystrea.ms/schema/1.0/post/</activity:verb>
    <activity:object>
      <id>tag:www.dailymile.com,2010:workout/5578772</id>
      <title type="text">Bojo ran 6.1 miles in 56 mins</title>
      <published>2011-02-25T12:29:54-08:00</published>
      <activity:object-type>http://activitystrea.ms/schema/1.0/workout</activity:object-type>
      <content type="xhtml">
<span class="workout-feeling great">great</span>
<a href="/people/bojo/entries/5578772" class="workout-title">park loops</a>
<span class="workout-distance">6.1
<span class="workout-distance-units">mi</span></span>
  <span class="workout-time">00:57</span>
<span class="workout-pace">09:18 pace</span>
<div class="entry-description">
  <p>thought i had a nice break in the rain then the skies just busted open along with hurricane winds at 1.7. stood under awning for a few til it was just drizzling. not a bad run, just interesting....</p>
</div>      </content>
    </activity:object>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
<span class="workout-activity-type">Running</span><span class="workout-feeling great">great</span>
<a href="/people/bojo/entries/5578772" class="workout-title">park loops</a>
<span class="workout-distance">6.1
<span class="workout-distance-units">mi</span></span>
  <span class="workout-time">00:57</span>
<span class="workout-pace">09:18 pace</span>
<div class="entry-description">
  <p>thought i had a nice break in the rain then the skies just busted open along with hurricane winds at 1.7. stood under awning for a few til it was just drizzling. not a bad run, just interesting....</p>
</div>      </div>
    </content>
    <author>
      <activity:object-type>http://activitystrea.ms/schema/1.0/person</activity:object-type>
      <name>Bojo</name>
      <uri>http://www.dailymile.com/people/bojo</uri>
      <link rel="photo" type="image/jpeg" href="http://s3.dmimg.com/pictures/users/87363/1273944150_avatar.jpg"/>
      <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/bojo"/>
    </author>
  </entry>
  <entry>
    <id>tag:www.dailymile.com,2010:/entries/5578770</id>
    <published>2011-02-25T12:29:43-08:00</published>
    <updated>2011-02-25T12:29:43-08:00</updated>
    <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/Run_Pablo_Run/entries/5578770"/>
    <title type="text">Paul posted a workout</title>
    <category term="http://schemas.dailymile.com/entry#workout"/>
    <link rel="replies" type="applicaton/xhtml+xml" thr:count="0" href="http://www.dailymile.com/people/Run_Pablo_Run/entries/5578770#comments"/>
    <activity:verb>http://activitystrea.ms/schema/1.0/post/</activity:verb>
    <activity:object>
      <id>tag:www.dailymile.com,2010:workout/5578770</id>
      <title type="text">Paul ran 1 mile in 6 mins and 40 secs</title>
      <published>2011-02-25T12:29:43-08:00</published>
      <activity:object-type>http://activitystrea.ms/schema/1.0/workout</activity:object-type>
      <content type="xhtml">
<span class="workout-feeling good">good</span>
<a href="/people/Run_Pablo_Run/entries/5578770" class="workout-title">Treadmill</a>
<span class="workout-distance">1
<span class="workout-distance-units">mi</span></span>
  <span class="workout-time">00:06:40</span>
<span class="workout-pace">06:40 pace</span>
<div class="entry-description">
  <p>Quick warmup run for working out at the gym.</p>
</div>      </content>
    </activity:object>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
<span class="workout-activity-type">Running</span><span class="workout-feeling good">good</span>
<a href="/people/Run_Pablo_Run/entries/5578770" class="workout-title">Treadmill</a>
<span class="workout-distance">1
<span class="workout-distance-units">mi</span></span>
  <span class="workout-time">00:06:40</span>
<span class="workout-pace">06:40 pace</span>
<div class="entry-description">
  <p>Quick warmup run for working out at the gym.</p>
</div>      </div>
    </content>
    <author>
      <activity:object-type>http://activitystrea.ms/schema/1.0/person</activity:object-type>
      <name>Paul G.</name>
      <uri>http://www.dailymile.com/people/Run_Pablo_Run</uri>
      <link rel="photo" type="image/jpeg" href="http://s1.dmimg.com/pictures/users/195158/1297273873_avatar.jpg"/>
      <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/Run_Pablo_Run"/>
    </author>
  </entry>
  <entry>
    <id>tag:www.dailymile.com,2010:/entries/5578767</id>
    <published>2011-02-25T12:29:33-08:00</published>
    <updated>2011-02-25T12:29:33-08:00</updated>
    <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/KieraC/entries/5578767"/>
    <title type="text">Kiera posted a workout</title>
    <category term="http://schemas.dailymile.com/entry#workout"/>
    <link rel="replies" type="applicaton/xhtml+xml" thr:count="0" href="http://www.dailymile.com/people/KieraC/entries/5578767#comments"/>
    <activity:verb>http://activitystrea.ms/schema/1.0/post/</activity:verb>
    <activity:object>
      <id>tag:www.dailymile.com,2010:workout/5578767</id>
      <title type="text">Kiera did a fitness workout for 20 mins</title>
      <published>2011-02-25T12:29:33-08:00</published>
      <activity:object-type>http://activitystrea.ms/schema/1.0/workout</activity:object-type>
      <content type="xhtml">
<span class="workout-feeling good">good</span>
<a href="/people/KieraC/entries/5578767" class="workout-title">my stairway</a>
  <span class="workout-time">00:20</span>

<div class="entry-description">
  <div class="preview_text"><p>finally put our 'stair master' of a house to work for me...with 2 sick kids at home I knew I wasn't going to make it to the Y or even around the block...and with them in front of the tv a wii worko<span class="ellipsis">...</span> <a href="#" onclick="$(this).up('div.preview_text').hide().next().show(); return false;">read more</a></p></div><div class="full_text" style="display: none"><p>finally put our 'stair master' of a house to work for me...with 2 sick kids at home I knew I wasn't going to make it to the Y or even around the block...and with them in front of the tv a wii workout wasn't going to happen either...so I spent 15 minutes doing our stairs...kicked my bootah.</p></div>
</div>      </content>
    </activity:object>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
<span class="workout-activity-type">Fitness</span><span class="workout-feeling good">good</span>
<a href="/people/KieraC/entries/5578767" class="workout-title">my stairway</a>
  <span class="workout-time">00:20</span>

<div class="entry-description">
  <div class="preview_text"><p>finally put our 'stair master' of a house to work for me...with 2 sick kids at home I knew I wasn't going to make it to the Y or even around the block...and with them in front of the tv a wii worko<span class="ellipsis">...</span> <a href="#" onclick="$(this).up('div.preview_text').hide().next().show(); return false;">read more</a></p></div><div class="full_text" style="display: none"><p>finally put our 'stair master' of a house to work for me...with 2 sick kids at home I knew I wasn't going to make it to the Y or even around the block...and with them in front of the tv a wii workout wasn't going to happen either...so I spent 15 minutes doing our stairs...kicked my bootah.</p></div>
</div>      </div>
    </content>
    <author>
      <activity:object-type>http://activitystrea.ms/schema/1.0/person</activity:object-type>
      <name>Kiera C.</name>
      <uri>http://www.dailymile.com/people/KieraC</uri>
      <link rel="photo" type="image/jpeg" href="http://s1.dmimg.com/pictures/users/189831/1296256103_avatar.jpg"/>
      <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/KieraC"/>
    </author>
  </entry>
  <entry>
    <id>tag:www.dailymile.com,2010:/entries/5578766</id>
    <published>2011-02-25T12:29:26-08:00</published>
    <updated>2011-02-25T12:29:37-08:00</updated>
    <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/SharonG5/entries/5578766"/>
    <title type="text">Sharon posted a workout</title>
    <category term="http://schemas.dailymile.com/entry#workout"/>
    <link rel="replies" type="applicaton/xhtml+xml" thr:count="0" href="http://www.dailymile.com/people/SharonG5/entries/5578766#comments"/>
    <activity:verb>http://activitystrea.ms/schema/1.0/post/</activity:verb>
    <activity:object>
      <id>tag:www.dailymile.com,2010:workout/5578766</id>
      <title type="text">Sharon walked 0.01 miles 11 sec</title>
      <published>2011-02-25T12:29:26-08:00</published>
      <activity:object-type>http://activitystrea.ms/schema/1.0/workout</activity:object-type>
      <content type="xhtml">

<a href="/people/SharonG5/entries/5578766" class="workout-title">Walk</a>
<span class="workout-distance">0.01
<span class="workout-distance-units">mi</span></span>
<span class="workout-pace">18:19 pace</span>
<div class="entry-description">
  <p>Stopped Walk at 12:29 PM, <a href="http://j.mp/fLfumC" rel="nofollow" target="_blank">http://j.mp/fLfumC</a>.</p>
</div>      </content>
    </activity:object>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
<span class="workout-activity-type">Walking</span>
<a href="/people/SharonG5/entries/5578766" class="workout-title">Walk</a>
<span class="workout-distance">0.01
<span class="workout-distance-units">mi</span></span>
<span class="workout-pace">18:19 pace</span>
<div class="entry-description">
  <p>Stopped Walk at 12:29 PM, <a href="http://j.mp/fLfumC" rel="nofollow" target="_blank">http://j.mp/fLfumC</a>.</p>
</div>      </div>
    </content>
    <source>
      <generator uri="http://www.abvio.com/walkmeter">Walkmeter</generator>
    </source>
    <author>
      <activity:object-type>http://activitystrea.ms/schema/1.0/person</activity:object-type>
      <name>Sharon G.</name>
      <uri>http://www.dailymile.com/people/SharonG5</uri>
      <link rel="photo" type="image/jpeg" href="http://www.dailymile.com/images/defaults/user_avatar.jpg"/>
      <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/SharonG5"/>
    </author>
  </entry>
  <entry>
    <id>tag:www.dailymile.com,2010:/entries/5578765</id>
    <published>2011-02-25T12:29:22-08:00</published>
    <updated>2011-02-25T12:29:22-08:00</updated>
    <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/ShaylaD/entries/5578765"/>
    <title type="text">Shayla posted a workout</title>
    <category term="http://schemas.dailymile.com/entry#workout"/>
    <link rel="replies" type="applicaton/xhtml+xml" thr:count="0" href="http://www.dailymile.com/people/ShaylaD/entries/5578765#comments"/>
    <activity:verb>http://activitystrea.ms/schema/1.0/post/</activity:verb>
    <activity:object>
      <id>tag:www.dailymile.com,2010:workout/5578765</id>
      <title type="text">Shayla ran 5.1 miles in 41 mins</title>
      <published>2011-02-25T12:29:22-08:00</published>
      <activity:object-type>http://activitystrea.ms/schema/1.0/workout</activity:object-type>
      <content type="xhtml">

<span class="workout-distance">5.1
<span class="workout-distance-units">mi</span></span>
  <span class="workout-time">00:41</span>
<span class="workout-pace">08:05 pace</span>
<div class="entry-description">
  <p>Felt pretty good out there today. It was very pleasant running out on the Capitol City Trail but a little more breezy on the way back in. Nonetheless, the sunshine was nice and there was no wicked ... <a href="/people/ShaylaD/entries/5578765">read more</a></p>
</div>      </content>
    </activity:object>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
<span class="workout-activity-type">Running</span>
<span class="workout-distance">5.1
<span class="workout-distance-units">mi</span></span>
  <span class="workout-time">00:41</span>
<span class="workout-pace">08:05 pace</span>
<div class="entry-description">
  <p>Felt pretty good out there today. It was very pleasant running out on the Capitol City Trail but a little more breezy on the way back in. Nonetheless, the sunshine was nice and there was no wicked ... <a href="/people/ShaylaD/entries/5578765">read more</a></p>
</div>      </div>
    </content>
    <author>
      <activity:object-type>http://activitystrea.ms/schema/1.0/person</activity:object-type>
      <name>Shayla D.</name>
      <uri>http://www.dailymile.com/people/ShaylaD</uri>
      <link rel="photo" type="image/jpeg" href="http://s2.dmimg.com/pictures/users/17701/1285814622_avatar.jpg"/>
      <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/ShaylaD"/>
    </author>
  </entry>
  <entry>
    <id>tag:www.dailymile.com,2010:/entries/5578763</id>
    <published>2011-02-25T12:29:05-08:00</published>
    <updated>2011-02-25T12:29:05-08:00</updated>
    <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/markleeman/entries/5578763"/>
    <title type="text">Mark posted a workout</title>
    <category term="http://schemas.dailymile.com/entry#workout"/>
    <link rel="replies" type="applicaton/xhtml+xml" thr:count="0" href="http://www.dailymile.com/people/markleeman/entries/5578763#comments"/>
    <activity:verb>http://activitystrea.ms/schema/1.0/post/</activity:verb>
    <activity:object>
      <id>tag:www.dailymile.com,2010:workout/5578763</id>
      <title type="text">Mark ran 5 miles in 37 mins</title>
      <published>2011-02-25T12:29:05-08:00</published>
      <activity:object-type>http://activitystrea.ms/schema/1.0/workout</activity:object-type>
      <content type="xhtml">

<span class="workout-distance">5
<span class="workout-distance-units">mi</span></span>
  <span class="workout-time">00:37</span>
<span class="workout-pace">07:25 pace</span>
<div class="entry-description">
  <p></p>
</div>      </content>
    </activity:object>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
<span class="workout-activity-type">Running</span>
<span class="workout-distance">5
<span class="workout-distance-units">mi</span></span>
  <span class="workout-time">00:37</span>
<span class="workout-pace">07:25 pace</span>
<div class="entry-description">
  <p></p>
</div>      </div>
    </content>
    <author>
      <activity:object-type>http://activitystrea.ms/schema/1.0/person</activity:object-type>
      <name>Mark L.</name>
      <uri>http://www.dailymile.com/people/markleeman</uri>
      <link rel="photo" type="image/jpeg" href="http://s2.dmimg.com/pictures/users/43971/1296338285_avatar.jpg"/>
      <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/markleeman"/>
    </author>
  </entry>
  <entry>
    <id>tag:www.dailymile.com,2010:/entries/5578762</id>
    <published>2011-02-25T12:29:05-08:00</published>
    <updated>2011-02-25T12:29:42-08:00</updated>
    <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/LindaB8/entries/5578762"/>
    <title type="text">Linda posted a workout</title>
    <category term="http://schemas.dailymile.com/entry#workout"/>
    <link rel="replies" type="applicaton/xhtml+xml" thr:count="0" href="http://www.dailymile.com/people/LindaB8/entries/5578762#comments"/>
    <activity:verb>http://activitystrea.ms/schema/1.0/post/</activity:verb>
    <activity:object>
      <id>tag:www.dailymile.com,2010:workout/5578762</id>
      <title type="text">Linda ran 3.1 miles in 45 mins</title>
      <published>2011-02-25T12:29:05-08:00</published>
      <activity:object-type>http://activitystrea.ms/schema/1.0/workout</activity:object-type>
      <content type="xhtml">
<span class="workout-feeling good">good</span>
<span class="workout-distance">3.1
<span class="workout-distance-units">mi</span></span>
  <span class="workout-time">00:45</span>
<span class="workout-pace">14:30 pace</span>
<div class="entry-description">
  <p></p>
</div>      </content>
    </activity:object>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
<span class="workout-activity-type">Running</span><span class="workout-feeling good">good</span>
<span class="workout-distance">3.1
<span class="workout-distance-units">mi</span></span>
  <span class="workout-time">00:45</span>
<span class="workout-pace">14:30 pace</span>
<div class="entry-description">
  <p></p>
</div>      </div>
    </content>
    <author>
      <activity:object-type>http://activitystrea.ms/schema/1.0/person</activity:object-type>
      <name>Linda B.</name>
      <uri>http://www.dailymile.com/people/LindaB8</uri>
      <link rel="photo" type="image/jpeg" href="http://s2.dmimg.com/pictures/users/173194/1297541798_avatar.jpg"/>
      <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/LindaB8"/>
    </author>
  </entry>
  <entry>
    <id>tag:www.dailymile.com,2010:/entries/5578761</id>
    <published>2011-02-25T12:29:00-08:00</published>
    <updated>2011-02-25T12:29:00-08:00</updated>
    <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/AndrewP3/entries/5578761"/>
    <title type="text">Andrew posted a workout</title>
    <category term="http://schemas.dailymile.com/entry#workout"/>
    <link rel="replies" type="applicaton/xhtml+xml" thr:count="0" href="http://www.dailymile.com/people/AndrewP3/entries/5578761#comments"/>
    <activity:verb>http://activitystrea.ms/schema/1.0/post/</activity:verb>
    <activity:object>
      <id>tag:www.dailymile.com,2010:workout/5578761</id>
      <title type="text">Andrew ran 7.02 miles in 71 mins</title>
      <published>2011-02-25T12:29:00-08:00</published>
      <activity:object-type>http://activitystrea.ms/schema/1.0/workout</activity:object-type>
      <content type="xhtml">

<a href="/people/AndrewP3/entries/5578761" class="workout-title">5 mi Tempo + 1 mi Warm Up + 1...</a>
<span class="workout-distance">7.02
<span class="workout-distance-units">mi</span></span>
  <span class="workout-time">01:12</span>
<span class="workout-pace">10:13 pace</span>
<div class="entry-description">
  <p>5 mi Tempo + 1 mi Warm Up + 1 mi Cool Down (7 mi)</p>
</div>      </content>
    </activity:object>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
<span class="workout-activity-type">Running</span>
<a href="/people/AndrewP3/entries/5578761" class="workout-title">5 mi Tempo + 1 mi Warm Up + 1...</a>
<span class="workout-distance">7.02
<span class="workout-distance-units">mi</span></span>
  <span class="workout-time">01:12</span>
<span class="workout-pace">10:13 pace</span>
<div class="entry-description">
  <p>5 mi Tempo + 1 mi Warm Up + 1 mi Cool Down (7 mi)</p>
</div>      </div>
    </content>
    <author>
      <activity:object-type>http://activitystrea.ms/schema/1.0/person</activity:object-type>
      <name>Andrew P.</name>
      <uri>http://www.dailymile.com/people/AndrewP3</uri>
      <link rel="photo" type="image/jpeg" href="http://s3.dmimg.com/pictures/users/152533/1288127105_avatar.jpg"/>
      <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/AndrewP3"/>
    </author>
  </entry>
  <entry>
    <id>tag:www.dailymile.com,2010:/entries/5578760</id>
    <published>2011-02-25T12:28:46-08:00</published>
    <updated>2011-02-25T12:28:46-08:00</updated>
    <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/TheresaL3/entries/5578760"/>
    <title type="text">Theresa posted an image</title>
    <category term="http://schemas.dailymile.com/entry#image"/>
    <link rel="replies" type="applicaton/xhtml+xml" thr:count="0" href="http://www.dailymile.com/people/TheresaL3/entries/5578760#comments"/>
    <activity:verb>http://activitystrea.ms/schema/1.0/post/</activity:verb>
    <activity:object>
      <id>tag:www.dailymile.com,2010:image/5578760</id>
      <title type="text">Theresa shared a photo</title>
      <published>2011-02-25T12:28:46-08:00</published>
      <caption>My new plates!  :)</caption>
      <activity:object-type>http://activitystrea.ms/schema/1.0/image</activity:object-type>
      <content type="xhtml">
  <div class="image-container">
    <a href="/people/TheresaL3/entries/5578760"><img alt="Shared Photo" src="http://media.dailymile.com/photos/117283/e48586325164a31e72e4f5a7fa886942.jpg" /></a>
  </div>
<div class="entry-description">
  <p>My new plates!  :)</p>
</div>      </content>
    </activity:object>
    <link rel="enclosure" type="image/jpeg" href="http://media.dailymile.com/photos/117283/e48586325164a31e72e4f5a7fa886942.jpg" media:width="520" media:height="273" length="218171"/>
    <link rel="preview" type="image/jpeg" href="http://media.dailymile.com/photos/117283/e48586325164a31e72e4f5a7fa886942.jpg" media:width="75" media:height="75"/>
    <content type="xhtml">
      <div xmlns="http://www.w3.org/1999/xhtml">
  <div class="image-container">
    <a href="/people/TheresaL3/entries/5578760"><img alt="Shared Photo" src="http://media.dailymile.com/photos/117283/e48586325164a31e72e4f5a7fa886942.jpg" /></a>
  </div>
<div class="entry-description">
  <p>My new plates!  :)</p>
</div>      </div>
    </content>
    <author>
      <activity:object-type>http://activitystrea.ms/schema/1.0/person</activity:object-type>
      <name>Theresa L.</name>
      <uri>http://www.dailymile.com/people/TheresaL3</uri>
      <link rel="photo" type="image/jpeg" href="http://s1.dmimg.com/pictures/users/157089/1289227138_avatar.jpg"/>
      <link rel="alternate" type="text/html" href="http://www.dailymile.com/people/TheresaL3"/>
    </author>
  </entry>
</feed>
"""
  

if __name__ == "__main__":
  main()
