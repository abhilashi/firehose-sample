import unittest
import mox

import clients


class ClientsUnitTest(unittest.TestCase):
  def setUp(self):
    self.mox = mox.Mox()

  def testAddClient(self):
    clients.db = self.mox.CreateMockAnything()
    self.mox.StubOutWithMock(clients.db, 'put')
    
    clients.Client = self.mox.CreateMockAnything()
    
    self.mox.ReplayAll()
    
    clients.add_client()
    
if __name__ == '__main__':
    unittest.main()