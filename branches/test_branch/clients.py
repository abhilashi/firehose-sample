import feedparser
import logging

from datetime import datetime
from datetime import timedelta
try:
  import client_model
  from django.utils import simplejson
  from google.appengine.api import channel
  from google.appengine.ext import db
  from google.appengine.api import memcache
except:
  """Do nothing. We're testing."""

# Channel API tokens expire after two hours.
TOKEN_EXPIRATION = timedelta(hours = 2)

def add_client():
  """Add a new client to the database.""" 
  client = Client()
  db.put(client)
  return (str(client.created), channel.create_channel(str(client.created)))

def send_filtered_messages(clientid, messages):
  """Send messages to a client, doing a best-effort elimination of dupes."""
  messages_to_send = []
  for message in messages:
    id = clientid + message['id']
    if memcache.get(id):
      continue
    
    memcache.add(id, 's')
    messages_to_send.append(message)
    
  if len(messages_to_send):
    message = simplejson.dumps(messages_to_send);
    logging.warning("Sending (%s): %s" % (clientid, message))
    channel.send_message(clientid, message)

def broadcast_messages(messages):
  """Broadcast the given message list to all known clients.
  
  Args:
    messages: A list of objects to be sent to the clients. These messages
    will be JSON-encoded before sending. Each message object must have an
    'id' field, used to eliminate duplicates.
  """
  q = Client.all()
  active_clients = 0
  for client in q:
    if datetime.utcnow() - client.created > TOKEN_EXPIRATION:
      logging.debug('Removing expired client: %s' % str(client.created))
      client.delete()
    else:
      active_clients += 1
      logging.debug('Sending message')
      send_filtered_messages(str(client.created), messages)
  logging.debug('Active clients: %d' % active_clients)
  return active_clients

def update_clients(messages, client=None):
  if client:
    channel.send_message(client, simplejson.dumps(messages))
    return 1
  else:
    return broadcast_messages(messages)


