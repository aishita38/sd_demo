"""Integration checks against a real HTTP server and isolated SQLite database."""
import concurrent.futures
import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
import server

class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        server.DB=Path(cls.temp.name)/'test.sqlite3'
        server.init()
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=cls.http.serve_forever,daemon=True).start()
        cls.url='http://127.0.0.1:'+str(cls.http.server_port)+'/api/'
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close(); cls.temp.cleanup()
    def client(self,email):
        c=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.assertEqual(self.call(c,'login',{'email':email,'password':'Demo@123'})[0],200)
        return c
    def call(self,c,path,data=None):
        req=urllib.request.Request(self.url+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
        try:
            with c.open(req) as r: return r.status,json.load(r)
        except urllib.error.HTTPError as e: return e.code,json.load(e)
    def test_booking_lifecycle_and_atomic_rollback(self):
        c=self.client('student@csms.demo')
        state=self.call(c,'state')[1]
        slots=[s for s in state['slots'] if s['available'] and s['date']>state['today'] and s['counsellor']==4]
        self.assertEqual(self.call(c,'book',{'slot':slots[0]['id']})[0],200)
        self.assertIn(self.call(c,'book',{'slot':slots[0]['id']})[0],(400,409))
        a=next(a for a in self.call(c,'state')[1]['appointments'] if a['slot']==slots[0]['id'])
        self.assertEqual(self.call(c,'reschedule',{'id':a['id'],'slot':slots[1]['id']})[0],200)
        # A failed target leaves the original appointment and slot intact.
        self.assertEqual(self.call(c,'reschedule',{'id':a['id'],'slot':-1})[0],400)
        current=next(x for x in self.call(c,'state')[1]['appointments'] if x['id']==a['id'])
        self.assertEqual(current['slot'],slots[1]['id'])
        self.assertEqual(self.call(c,'status',{'id':a['id'],'status':'Completed'})[0],403)
        self.assertEqual(self.call(c,'status',{'id':a['id'],'status':'Cancelled'})[0],200)
        self.assertTrue(next(s for s in self.call(c,'state')[1]['slots'] if s['id']==slots[1]['id'])['available'])
    def test_roles_and_schedule_overlap(self):
        student=self.client('student@csms.demo'); admin=self.client('admin@csms.demo'); management=self.client('management@csms.demo')
        today=self.call(admin,'state')[1]['today']
        d={'counsellor':4,'shift':'Morning','from':today,'to':today}
        self.assertEqual(self.call(student,'schedule',d)[0],403)
        self.assertEqual(self.call(admin,'schedule',d)[0],400)
        self.assertEqual(self.call(management,'book',{'slot':1})[0],403)
        self.assertEqual(self.call(student,'user',{'id':2,'active':False})[0],403)
        self.assertEqual(self.call(student,'state')[1]['users'],[])
    def test_concurrent_online_offline_booking(self):
        student=self.client('student@csms.demo'); admin=self.client('admin@csms.demo')
        s=self.call(admin,'state')[1]
        target=next(x for x in reversed(s['slots']) if x['available'] and x['date']>s['today'])
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            futures=[pool.submit(self.call,student,'book',{'slot':target['id']}),pool.submit(self.call,admin,'book',{'slot':target['id'],'student':1})]
            results=[f.result()[0] for f in futures]
        self.assertEqual(results.count(200),1)
        self.assertTrue(any(r in (400,409) for r in results))
    def test_registration_and_notifications(self):
        c=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.assertEqual(self.call(c,'register',{'name':'New Student','email':'new@example.test','password':'Password123','role':'Admin'})[0],200)
        self.assertEqual(self.call(c,'state')[1]['user']['role'],'Student')
        self.assertEqual(self.call(c,'logout',{})[0],200)
        self.assertEqual(self.call(c,'state')[0],401)
        student=self.client('student@csms.demo')
        self.assertGreater(len(self.call(student,'state')[1]['notifications']),0)
        self.assertEqual(self.call(student,'read',{})[0],200)
        self.assertFalse(any(n['unread'] for n in self.call(student,'state')[1]['notifications']))

if __name__=='__main__': unittest.main(verbosity=2)
