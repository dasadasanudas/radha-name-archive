#!/usr/bin/env python3
"""Resume a bounded, index-only Radha.name crawl; never download files."""
import argparse,json,re,time
from collections import deque
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urljoin,urlsplit,urlunsplit
from urllib.request import HTTPRedirectHandler,Request,build_opener
ROOT='https://www.radha.name'
HOSTS={'radha.name','www.radha.name'}
AGENT='RadhaArchivePilot/1.0 (index-only)'
SKIP=('/sites/','/includes/','/misc/','/modules/','/profiles/','/scripts/','/themes/','/vote/','/admin/','/comment/','/contact','/logout','/node/add/','/search/','/user')
REFUSED={ROOT+'/images-gallery'}
EXTS=('.pdf','.doc','.docx','.rtf','.odt','.txt','.epub','.mobi','.zip','.rar','.7z','.xls','.xlsx','.ppt','.pptx','.jpg','.jpeg','.png','.gif','.webp','.svg','.mp3','.mp4','.wav','.avi','.mov','.m4a','.flv','.ogg')
class Blocked(Exception): pass
class Redirects(HTTPRedirectHandler):
 def __init__(self,fetch): self.fetch=fetch
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  p=urlsplit(newurl)
  if p.scheme!='https' or (p.hostname or '').lower() not in HOSTS: raise Blocked('External redirect refused: '+newurl)
  if self.fetch.rules is not None and not allowed(newurl,self.fetch.rules): raise Blocked('Restricted redirect refused: '+newurl)
  self.fetch.throttle()
  return super().redirect_request(req,fp,code,msg,headers,newurl)
class Fetcher:
 def __init__(self): self.last=0.;self.delay=10.;self.rules=None;self.opener=build_opener(Redirects(self))
 def throttle(self):
  delay=self.delay-(time.monotonic()-self.last)
  if delay>0: time.sleep(delay)
  self.last=time.monotonic()
 def get(self,url,cap):
  self.throttle()
  try:
   with self.opener.open(Request(url,headers={'User-Agent':AGENT}),timeout=35) as r:
    data=r.read(cap+1)
    if len(data)>cap: raise ValueError('Response exceeds size limit')
    return data,r.headers.get_content_type()
  except HTTPError as e:
   if e.code in (401,403,429): raise Blocked(f'HTTP {e.code} for {url}; stopped') from e
   raise
class Links(HTMLParser):
 def __init__(self): super().__init__(convert_charrefs=True);self.items=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='a' and a.get('href'): self.items.append(('href',a['href']))
  if tag in ('img','video','audio','source','embed') and a.get('src'): self.items.append(('src',a['src']))
def normalize(base,link):
 try:
  u=urlsplit(urljoin(base,link.strip()))
  if u.scheme not in ('http','https') or (u.hostname or '').lower() not in HOSTS: return None
  return urlunsplit(('https','www.radha.name',quote(u.path or '/',safe="/%:@!$&'()*+,;=-._~"),u.query,''))
 except (ValueError,TypeError): return None
def parse_robots(text):
 groups=[]; agents=[]; rules=[]; delays=[]; directed=False
 def finish():
  if agents: groups.append((agents[:],rules[:],delays[:]))
 for raw in text.splitlines():
  line=raw.split('#',1)[0].strip()
  if ':' not in line: continue
  key,val=(x.strip() for x in line.split(':',1));key=key.lower()
  if key=='user-agent':
   if directed: finish();agents=[];rules=[];delays=[];directed=False
   agents.append(val.lower())
  elif agents:
   directed=True
   if key in ('allow','disallow') and val: rules.append((val,key=='allow'))
   elif key=='crawl-delay':
    try: delays.append(float(val))
    except ValueError: pass
 finish();specific=[g for g in groups if any(a!='*' and a in 'radhaarchivepilot' for a in g[0])]
 chosen=specific or [g for g in groups if '*' in g[0]]
 return [r for _,rs,_ in chosen for r in rs],max([10.]+[d for _,_,ds in chosen for d in ds])
def robots_allowed(url,rules):
 u=urlsplit(url);path=u.path+('?' + u.query if u.query else '');matches=[]
 for pat,allow in rules:
  end=pat.endswith('$');pat=pat[:-1] if end else pat
  if re.search('^'+re.escape(pat).replace(r'\*','.*')+('$' if end else ''),path): matches.append((len(pat.replace('*','')),allow))
 return max(matches)[1] if matches else True
def file_url(url):
 p=urlsplit(url).path.lower()
 return p.startswith('/sites/default/files/') or p.endswith(EXTS)
def allowed(url,rules):
 u=urlsplit(url)
 return (u.scheme=='https' and (u.hostname or '').lower() in HOSTS and url not in REFUSED and not any(u.path.startswith(x) for x in SKIP) and (not u.query or bool(re.fullmatch(r'page=\d+',u.query))) and not file_url(url) and robots_allowed(url,rules))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--max-pages',type=int,default=20);args=ap.parse_args()
 if not 1<=args.max_pages<=40: ap.error('--max-pages must be between 1 and 40')
 path=Path('crawl-manifest.json')
 state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version':1,'visited':[],'queue':[ROOT+'/digital-books',ROOT+'/'],'files':{},'pilot':{},'errors':[]}
 state.setdefault('skipped',[]);state.setdefault('runs',[]);fetch=Fetcher();attempted=0;status='partial';error=None
 try:
  body,kind=fetch.get(ROOT+'/robots.txt',1024*1024);text=body.decode('utf-8',errors='replace')
  if kind=='text/html' or 'user-agent:' not in text.lower(): raise Blocked('Invalid robots.txt response; stopped')
  rules,fetch.delay=parse_robots(text);state['robots']={'url':ROOT+'/robots.txt','crawl_delay_seconds':fetch.delay,'rule_count':len(rules)}
  queue=deque(sorted(state['queue'],key=lambda u:0 if urlsplit(u).path.startswith('/digital-books') else 1));state['queue']=[]
  seen=set(state['visited'])|set(queue);seen.update(e['url'] for e in state['errors'] if 'url' in e)
  while queue and attempted<args.max_pages:
   url=queue.popleft()
   if not allowed(url,rules): state['skipped'].append({'url':url,'reason':'restricted or previously refused'});continue
   attempted+=1
   try:
    fetch.rules=rules;body,kind=fetch.get(url,8*1024*1024)
    if kind not in ('text/html','application/xhtml+xml'): raise ValueError('Not HTML: '+kind)
    links=Links();links.feed(body.decode('utf-8',errors='replace'))
    for source,raw in links.items:
     full=normalize(url,raw)
     if not full: continue
     if file_url(full): state['files'].setdefault(full,{'first_seen_on':url,'via':source})
     elif source=='href' and allowed(full,rules) and full not in seen: seen.add(full);queue.append(full)
    state['visited'].append(url);print('Indexed:',url,'candidate files:',len(state['files']),'queued:',len(queue),flush=True)
   except Blocked: queue.appendleft(url);raise
   except (HTTPError,URLError,OSError,ValueError) as e: state['errors'].append({'url':url,'error':str(e)});print('Page failed:',url,str(e),flush=True)
   finally: fetch.rules=None
  status='partial' if queue else ('partial_errors' if state['errors'] else 'exhausted_known_queue')
 except (Blocked,HTTPError,URLError,OSError,ValueError) as e:
  error=str(e);status='blocked_or_failed';state['errors'].append({'stage':'index-only','error':error});print('Stopped:',error,flush=True)
 finally:
  if 'queue' in locals(): state['queue']=list(queue)
  state['crawl_status']=status;state['scope']='Same-site HTML discovery only; no document or media file is downloaded.';state['updated_utc']=datetime.now(timezone.utc).isoformat()
  state['runs'].append({'mode':'index-only','attempted_pages':attempted,'status':status,'error':error,'at':state['updated_utc']})
  temp=path.with_suffix('.tmp');temp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temp.replace(path)
 print(f"Result: {len(state['visited'])} pages indexed, {len(state['files'])} candidate file URLs, {len(state['queue'])} pages queued; {status}",flush=True)
 return 1 if error else 0
if __name__=='__main__': raise SystemExit(main())
