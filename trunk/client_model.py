from google.appengine.ext import db

class Client(db.Model):
  """A record of a client connection. The string representation of the 'created'
  field is the clientid used by the Channel API
  """
  created = db.DateTimeProperty(required=True, auto_now_add=True)
  feeds = db.StringListProperty(required=True)
    
