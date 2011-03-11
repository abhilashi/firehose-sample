import unittest
import mox

import clients
import client_model

from datetime import datetime
from google.appengine.ext import db
from google.appengine.api import channel
# Import the 'testbed' module.
from google.appengine.ext import testbed


class ClientsUnitTest(unittest.TestCase):
  def setUp(self):
    self.mox = mox.Mox()
    # At first, create an instance of the Testbed class.
    self.testbed = testbed.Testbed()
    # Then activate the testbed which will prepare the usage of service stubs.
    self.testbed.activate()
    # Next, declare which service stubs you want to use.
    self.testbed.init_datastore_v3_stub()
    self.testbed.init_memcache_stub()

  def test_add_client(self):
    self.mox.StubOutWithMock(clients, 'channel')
    clients.channel.create_channel(mox.IsA(str))
    self.mox.ReplayAll()
    
    (id, token) = clients.add_client('http://example.com/feed')
    self.mox.UnsetStubs()
    self.mox.VerifyAll()
    self.assertEqual(1, len(client_model.Client.all().fetch(2)))
    
  def test_add_client_no_feed(self):
    try:
      clients.add_client()
      self.fail('add_client with no feed should fail.')
    except:
      """Expected behavior."""
    
  def test_send_filtered_messages(self):
    self.mox.StubOutWithMock(clients, 'channel')
    self.mox.StubOutWithMock(clients, 'datetime')
    clients.channel.create_channel(mox.IsA(str))
    clients.channel.send_message(mox.IsA(str), '[{"id": "foo"}, {"id": "bar"}]')
    self.mox.ReplayAll()
    
    (id, token) = clients.add_client('http://example.com/feed')
    clients.send_filtered_messages(id, 'http://example.com/feed',
                                   [{'id': 'foo'}, {'id': 'bar'}])
    self.mox.UnsetStubs()
    self.mox.VerifyAll()

  def test_send_filtered_messages_with_dup(self):
    self.mox.StubOutWithMock(clients, 'channel')
    self.mox.StubOutWithMock(clients, 'datetime')
    clients.channel.create_channel(mox.IsA(str))
    clients.channel.send_message(mox.IsA(str), '[{"id": "foo"}, {"id": "bar"}]')
    clients.channel.send_message(mox.IsA(str), '[{"id": "baz"}]')
    self.mox.ReplayAll()
    
    (id, token) = clients.add_client('http://example.com/feed')
    clients.send_filtered_messages(id, 'http://example.com/feed',
                                   [{'id': 'foo'}, {'id': 'bar'}])
    clients.send_filtered_messages(id, 'http://example.com/feed',
                                   [{'id': 'foo'}, {'id': 'baz'}])
    self.mox.UnsetStubs()
    self.mox.VerifyAll()
    
if __name__ == '__main__':
    unittest.main()