import client_model
import feedparser
import logging

from datetime import datetime
from datetime import timedelta
from django.utils import simplejson
from google.appengine.api import channel
from google.appengine.ext import db
from google.appengine.api import memcache

# Channel API tokens expire after two hours.
TOKEN_EXPIRATION = timedelta(hours = 2)

def add_client(feed):
  """Add a new client to the database.""" 
  client = client_model.Client()
  client.feeds = [feed]
  db.put(client)
  return (str(client.created), channel.create_channel(str(client.created)))


def get_memcache_id(clientid, feed, message):
  return clientid + '.' + feed + '.' + message['id']


def send_filtered_messages(clientid, feed, messages):
  """Send messages to a client, doing a best-effort elimination of dupes."""
  messages_to_send = []
  for message in messages:
    id = get_memcache_id(clientid, feed, message)
    if memcache.get(id):
      continue
    
    memcache.add(id, 's')
    messages_to_send.append(message)
    
  if len(messages_to_send):
    message = simplejson.dumps(messages_to_send);
    logging.debug("Sending (%s): %s" % (clientid, message))
    channel.send_message(clientid, message)


def broadcast_messages(feed, messages):
  """Broadcast the given message list to all known clients.
  
  Args:
    messages: A list of objects to be sent to the clients. These messages
    will be JSON-encoded before sending. Each message object must have an
    'id' field, used to eliminate duplicates.
  """
  q = client_model.Client.all()
  active_clients = 0
  for client in q:
    if datetime.utcnow() - client.created > TOKEN_EXPIRATION:
      logging.debug('Removing expired client: %s' % str(client.created))
      client.delete()
    else:
      active_clients += 1
      logging.debug('Sending message')
      send_filtered_messages(str(client.created), feed, messages)
  logging.debug('Active clients: %d' % active_clients)
  return active_clients


def update_clients(feed, messages, client=None):
  if client:
    send_filtered_messages(client, feed, messages)
    return 1
  else:
    return broadcast_messages(feed, messages)


