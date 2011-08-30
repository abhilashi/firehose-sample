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
  cid = str(client.key().id())
  return (cid, channel.create_channel(cid))


def set_client_connect_state(cid, connect_state):
  logging.info('Looking up client %s' % cid)
  client = client_model.Client.get_by_id(int(cid))
  client.connected = connect_state
  client.put()


def connect_client(cid):
  set_client_connect_state(cid, True)


def disconnect_client(cid):
  set_client_connect_state(cid, False)


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
  connected_clients = 0
  total_clients = 0
  for client in q:
    total_clients += 1
    if datetime.utcnow() - client.created > TOKEN_EXPIRATION:
      logging.debug('Removing expired client: %s' % str(client.created))
      client.delete()
      total_clients -= 1
    elif client.connected:
      connected_clients += 1
      logging.debug('Sending message')
      send_filtered_messages(str(client.key().id()), feed, messages)
    else:
      logging.debug('Skipping disconnected client %s' % client.created)

  logging.debug('Connected clients: %d' % connected_clients)
  logging.debug('Total clients: %d' % total_clients)
  return total_clients


def update_clients(feed, messages, client=None):
  if client:
    send_filtered_messages(client, feed, messages)
    return 1
  else:
    return broadcast_messages(feed, messages)
