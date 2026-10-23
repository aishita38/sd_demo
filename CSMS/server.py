"""CSMS local prototype. Python 3.10+, no third-party packages required."""
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
DB = Path(os.environ.get('CSMS_DB', str(ROOT / 'csms.sqlite3')))
SHIFTS = {'Morning': (9, 13), 'Afternoon': (13, 17), 'Evening': (17, 20)}

def today():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()

@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()

def password(value, salt):
    return hashlib.pbkdf2_hmac('sha256', value.encode(), salt.encode(), 150000).hex()

def add_user(db, name, email, role, pwd='Demo@123', **profile):
    salt = secrets.token_hex(16)
    cur = db.execute('INSERT INTO users(name,email,role,salt,hash,specialization,bio,office) VALUES(?,?,?,?,?,?,?,?)',
        (name, email.lower(), role, salt, password(pwd, salt), profile.get('specialization',''), profile.get('bio',''), profile.get('office','')))
    return cur.lastrowid

def generate(db, cid, shift, start, end):
    if shift not in SHIFTS: raise ValueError('Choose a valid schedule.')
    start, end = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if start < today() or end < start or (end-start).days > 90:
        raise ValueError('Choose a date range from today, up to 90 days.')
    if not db.execute("SELECT 1 FROM users WHERE id=? AND role='Counsellor' AND active=1", (cid,)).fetchone():
        raise ValueError('Active counsellor not found.')
    if db.execute('SELECT 1 FROM assignments WHERE counsellor=? AND start<=? AND end>=?', (cid,str(end),str(start))).fetchone():
        raise ValueError('This counsellor already has a schedule in that date range.')
    db.execute('INSERT INTO assignments(counsellor,shift,start,end) VALUES(?,?,?,?)',(cid,shift,str(start),str(end)))
    count = 0
    for day in range((end-start).days+1):
        date = str(start+dt.timedelta(days=day))
        for minute in range(SHIFTS[shift][0]*60, SHIFTS[shift][1]*60,30):
            db.execute('INSERT INTO slots(counsellor,date,start,end,shift) VALUES(?,?,?,?,?)',
                (cid,date,f'{minute//60:02}:{minute%60:02}',f'{(minute+30)//60:02}:{(minute+30)%60:02}',shift))
            count += 1
    return count

def init():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,role TEXT NOT NULL,salt TEXT NOT NULL,hash TEXT NOT NULL,active INTEGER DEFAULT 1,specialization TEXT DEFAULT '',bio TEXT DEFAULT '',office TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user INTEGER REFERENCES users(id),expires TEXT);
        CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY,counsellor INTEGER REFERENCES users(id),shift TEXT,start TEXT,end TEXT);
        CREATE TABLE IF NOT EXISTS slots(id INTEGER PRIMARY KEY,counsellor INTEGER REFERENCES users(id),date TEXT,start TEXT,end TEXT,shift TEXT,UNIQUE(counsellor,date,start));
        CREATE TABLE IF NOT EXISTS appointments(id INTEGER PRIMARY KEY,student INTEGER REFERENCES users(id),slot INTEGER REFERENCES slots(id),status TEXT DEFAULT 'Confirmed',channel TEXT,reason TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE UNIQUE INDEX IF NOT EXISTS one_booking_per_slot ON appointments(slot) WHERE status!='Cancelled';
        CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,user INTEGER REFERENCES users(id),message TEXT,unread INTEGER DEFAULT 1,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor INTEGER REFERENCES users(id),action TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        if db.execute('SELECT COUNT(*) FROM users').fetchone()[0]: return
        add_user(db,'Ishita Agarwal','student@csms.demo','Student')
        add_user(db,'Admissions Administrator','admin@csms.demo','Admin')
        add_user(db,'Institute Management','management@csms.demo','Management')
        counselors = [
            ('Dr. Meera Sharma','counsellor@csms.demo','Admissions & programmes','Find the right programme for your interests, strengths, and future ambitions.','Academic Block · A-102','Morning'),
            ('Prof. Arjun Mehta','arjun@csms.demo','Careers & opportunities','Explore career pathways, industry opportunities, and life after graduation.','Academic Block · B-204','Afternoon'),
            ('Dr. Nandini Rao','nandini@csms.demo','Scholarships & financial aid','Understand scholarships, eligibility, financial aid, and your next steps.','Student Centre · S-108','Evening')]
        for name,email,specialization,bio,office,shift in counselors:
            cid = add_user(db,name,email,'Counsellor',specialization=specialization,bio=bio,office=office)
            generate(db,cid,shift,str(today()),str(today()+dt.timedelta(days=13)))
        sid = db.execute("SELECT id FROM slots WHERE counsellor=4 AND date=? AND start='10:00'",(str(today()+dt.timedelta(days=1)),)).fetchone()[0]
        db.execute("INSERT INTO appointments(student,slot,channel,reason) VALUES(1,?,'Online','Programme selection and campus life')",(sid,))
        db.execute("INSERT INTO notifications(user,message) VALUES(1,'Welcome to CSMS. Your first counselling appointment is confirmed.')")

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(ROOT/'static'),**kwargs)
    def send_json(self,data,status=200,cookie=None):
        blob=json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        if cookie: self.send_header('Set-Cookie',cookie)
        self.send_header('Content-Length',str(len(blob)))
        self.end_headers(); self.wfile.write(blob)
    def do_GET(self):
        if self.path.startswith('/api/'): self.api('GET')
        else: super().do_GET()
    def do_POST(self): self.api('POST')
    def api(self,method):
        try:
            self.handle_api(method)
        except PermissionError as e: self.send_json({'error':str(e)},403)
        except (ValueError,KeyError,TypeError) as e: self.send_json({'error':str(e)},400)
        except sqlite3.IntegrityError: self.send_json({'error':'This slot is no longer available, or the email already exists. Please refresh and try again.'},409)
        except Exception as e:
            print(type(e).__name__,str(e)); self.send_json({'error':'The request could not be completed.'},500)
    def handle_api(self,method):
        path=urlparse(self.path).path
        data={}
        if method=='POST':
            if int(self.headers.get('Content-Length',0))>20000: raise ValueError('Request too large.')
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc != self.headers.get('Host'): raise PermissionError('Invalid request origin.')
            data=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or '{}')
        with connect() as db:
            if path in ('/api/login','/api/register') and method=='POST':
                email=str(data.get('email','')).strip().lower(); pwd=str(data.get('password',''))
                if path.endswith('register'):
                    name=str(data.get('name','')).strip()
                    if not name or '@' not in email or len(pwd)<8: raise ValueError('Enter your name, a valid email, and a password of at least 8 characters.')
                    add_user(db,name[:100],email,'Student',pwd)
                user=db.execute('SELECT * FROM users WHERE email=? AND active=1',(email,)).fetchone()
                if not user or not hmac.compare_digest(user['hash'],password(pwd,user['salt'])):
                    return self.send_json({'error':'Invalid email or password.'},401)
                token=secrets.token_urlsafe(32)
                db.execute('INSERT INTO sessions VALUES(?,?,?)',(token,user['id'],str(dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=12))))
                return self.send_json({'ok':True},cookie=f'csms_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200')
            cookie=SimpleCookie(); cookie.load(self.headers.get('Cookie',''))
            token=cookie['csms_session'].value if 'csms_session' in cookie else ''
            user=db.execute('SELECT u.* FROM users u JOIN sessions s ON s.user=u.id WHERE s.token=? AND s.expires>? AND u.active=1',(token,str(dt.datetime.now(dt.timezone.utc)))).fetchone()
            if not user: return self.send_json({'error':'Please sign in.'},401)
            uid,role=user['id'],user['role']
            def require(*roles):
                if role not in roles: raise PermissionError('Your role does not have access to this action.')
            def audit(action): db.execute('INSERT INTO audit(actor,action) VALUES(?,?)',(uid,action))
            def notify(aid,message):
                row=db.execute('SELECT a.student,s.counsellor FROM appointments a JOIN slots s ON s.id=a.slot WHERE a.id=?',(aid,)).fetchone()
                for recipient in (row['student'],row['counsellor']):
                    db.execute('INSERT INTO notifications(user,message) VALUES(?,?)',(recipient,f'Appointment #{aid}: {message}'))
            if path=='/api/logout' and method=='POST':
                db.execute('DELETE FROM sessions WHERE token=?',(token,)); return self.send_json({'ok':True},cookie='csms_session=; Path=/; Max-Age=0')
            if path=='/api/state' and method=='GET':
                public={k:user[k] for k in ('id','name','email','role')}
                counselors=[dict(r) for r in db.execute("SELECT id,name,specialization,bio,office,active FROM users WHERE role='Counsellor'")]
                slots=[dict(r) for r in db.execute("SELECT s.*,CASE WHEN a.id IS NULL THEN 1 ELSE 0 END available FROM slots s JOIN users u ON u.id=s.counsellor LEFT JOIN appointments a ON a.slot=s.id AND a.status!='Cancelled' WHERE s.date>=? AND u.active=1 ORDER BY s.date,s.start",(str(today()),))]
                query='SELECT a.*,s.counsellor,s.date,s.start,s.end,c.name counsellor_name,u.name student_name,u.email student_email FROM appointments a JOIN slots s ON s.id=a.slot JOIN users c ON c.id=s.counsellor JOIN users u ON u.id=a.student'
                params=()
                if role=='Student': query+=' WHERE a.student=?'; params=(uid,)
                elif role=='Counsellor': query+=' WHERE s.counsellor=?'; params=(uid,)
                apps=[dict(r) for r in db.execute(query+' ORDER BY s.date,s.start',params)]
                users=[dict(r) for r in db.execute('SELECT id,name,email,role,active FROM users')] if role=='Admin' else []
                notes=[dict(r) for r in db.execute('SELECT * FROM notifications WHERE user=? ORDER BY id DESC LIMIT 50',(uid,))]
                logs=[dict(r) for r in db.execute('SELECT a.*,u.name FROM audit a JOIN users u ON u.id=a.actor ORDER BY a.id DESC LIMIT 30')] if role=='Admin' else []
                assignments=[dict(r) for r in db.execute('SELECT * FROM assignments')]
                return self.send_json(dict(user=public,counsellors=counselors,slots=slots,appointments=apps,users=users,notifications=notes,audit=logs,assignments=assignments,today=str(today())))
            if method!='POST': return self.send_json({'error':'Not found.'},404)
            db.execute('BEGIN IMMEDIATE')
            if path=='/api/book':
                require('Student','Admin')
                student=uid if role=='Student' else int(data['student'])
                if not db.execute("SELECT 1 FROM users WHERE id=? AND role='Student' AND active=1",(student,)).fetchone(): raise ValueError('Select an active student.')
                slot=db.execute('SELECT s.* FROM slots s JOIN users u ON u.id=s.counsellor WHERE s.id=? AND u.active=1',(int(data['slot']),)).fetchone()
                self.validate_slot(slot)
                self.check_student_conflict(db,student,slot)
                cur=db.execute('INSERT INTO appointments(student,slot,channel,reason) VALUES(?,?,?,?)',(student,slot['id'],'Online' if role=='Student' else 'Offline',str(data.get('reason',''))[:1000]))
                notify(cur.lastrowid,'Booking confirmed.'); audit(f'Created appointment #{cur.lastrowid}')
            elif path in ('/api/reschedule','/api/status'):
                a=db.execute('SELECT a.*,s.counsellor FROM appointments a JOIN slots s ON s.id=a.slot WHERE a.id=?',(int(data['id']),)).fetchone()
                if not a: raise ValueError('Appointment not found.')
                if role=='Management' or (role=='Student' and a['student']!=uid) or (role=='Counsellor' and a['counsellor']!=uid): raise PermissionError('You cannot change this appointment.')
                if a['status'] not in ('Confirmed','Pending'): raise ValueError('This appointment is already closed.')
                if path.endswith('reschedule'):
                    require('Student','Admin')
                    slot=db.execute('SELECT * FROM slots WHERE id=?',(int(data['slot']),)).fetchone(); self.validate_slot(slot)
                    if slot['counsellor']!=a['counsellor']: raise ValueError('Choose another slot with the same counsellor.')
                    self.check_student_conflict(db,a['student'],slot,a['id'])
                    db.execute('UPDATE appointments SET slot=? WHERE id=?',(slot['id'],a['id']))
                    message='Rescheduled successfully.'
                else:
                    status=data['status']
                    allowed=('Cancelled',) if role=='Student' else ('Confirmed','Completed','No-show','Cancelled')
                    if status not in allowed: raise PermissionError('Invalid status change for your role.')
                    db.execute('UPDATE appointments SET status=? WHERE id=?',(status,a['id'])); message=f'Status updated to {status}.'
                notify(a['id'],message); audit(f'Appointment #{a["id"]}: {message}')
            elif path=='/api/schedule':
                require('Admin'); count=generate(db,int(data['counsellor']),data['shift'],data['from'],data['to']); audit(f'Generated {count} slots for counsellor #{data["counsellor"]}')
            elif path=='/api/profile':
                require('Admin','Counsellor'); target=uid if role=='Counsellor' else int(data['id'])
                if not db.execute("SELECT 1 FROM users WHERE id=? AND role='Counsellor'",(target,)).fetchone(): raise ValueError('Counsellor not found.')
                db.execute('UPDATE users SET specialization=?,bio=?,office=? WHERE id=?',(str(data['specialization'])[:200],str(data['bio'])[:1000],str(data['office'])[:200],target)); audit(f'Updated counsellor #{target}')
            elif path=='/api/user':
                require('Admin')
                if int(data['id'])==uid: raise ValueError('You cannot deactivate your own account.')
                db.execute('UPDATE users SET active=? WHERE id=?',(int(bool(data['active'])),int(data['id']))); audit(f'Updated account #{data["id"]}')
            elif path=='/api/read': db.execute('UPDATE notifications SET unread=0 WHERE user=?',(uid,))
            else: return self.send_json({'error':'Not found.'},404)
            self.send_json({'ok':True})
    @staticmethod
    def validate_slot(slot):
        if not slot: raise ValueError('Slot not found.')
        now=dt.datetime.now(dt.timezone(dt.timedelta(hours=5,minutes=30)))
        if slot['date']+'T'+slot['start'] <= now.strftime('%Y-%m-%dT%H:%M'): raise ValueError('Choose a future slot.')
    @staticmethod
    def check_student_conflict(db,student,slot,exclude=-1):
        if db.execute("SELECT 1 FROM appointments a JOIN slots s ON s.id=a.slot WHERE a.student=? AND a.id!=? AND a.status!='Cancelled' AND s.date=? AND s.start<? AND s.end>?",(student,exclude,slot['date'],slot['end'],slot['start'])).fetchone():
            raise ValueError('This student already has an appointment at that time.')

if __name__=='__main__':
    init()
    port=int(os.environ.get('PORT','8765'))
    print(f'CSMS running at http://127.0.0.1:{port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
