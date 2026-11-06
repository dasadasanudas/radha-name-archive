#!/usr/bin/env python3
"""Radha.name archiver. index: discover pages and file links. download: save document files to a local folder (not git)."""
import argparse, hashlib, json, os, re, time
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = 'https://www.radha.name'
HOSTS = {'radha.name', 'www.radha.name'}
AGENT = 'RadhaArchiver/2.0 (personal archive; contact: repo owner)'
SKIP = ('/sites/', '/includes/', '/misc/', '/modules/', '/profiles/', '/scripts/', '/themes/', '/vote/', '/admin/', '/comment/', '/contact', '/logout', '/node/add/', '/search/', '/user', '/cdn-cgi/')
EXTS = ('.pdf', '.doc', '.docx', '.rtf', '.odt', '.txt', '.epub', '.mobi', '.zip', '.rar', '.7z', '.xls', '.xlsx', '.ppt', '.pptx', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.mp3', '.mp4', '.wav', '.avi', '.mov', '.m4a', '.flv', '.ogg', '.html', '.htm')
DOC_PREFIX = '/sites/default/files/documents/'
MAX_REFUSALS = 3

class Stop(Exception): pass
class Refused(Exception):
    def __init__(self, code, url): super().__init__(f'HTTP {code} for {url}'); self.code = code

class Redirects(HTTPRedirectHandler):
    def __init__(self, fx): self.fx = fx
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urlsplit(newurl)
        if p.scheme != 'https' or (p.hostname or '').lower() not in HOSTS:
            raise Stop('External or non-HTTPS redirect refused: ' + newurl)
        self.fx.wait()
        return super().redirect_request(req, fp, code, msg, headers, newurl)

class Fetcher:
    def __init__(self, delay):
        self.delay, self.last = delay, 0.0
        self.opener = build_opener(Redirects(self))
    def wait(self):
        gap = self.delay - (time.monotonic() - self.last)
        if gap > 0: time.sleep(gap)
        self.last = time.monotonic()
    def open(self, url):
        self.wait()
        try:
            return self.opener.open(Request(url, headers={'User-Agent': AGENT}), timeout=60)
        except HTTPError as e:
            if e.code == 429: raise Stop(f'HTTP 429 (rate limited) for {url}')
            if e.code in (401, 403): raise Refused(e.code, url)
            raise
    def get(self, url, cap):
        with self.open(url) as r:
            data = r.read(cap + 1)
            if len(data) > cap: raise ValueError('Response exceeds size limit')
            return data, r.headers.get_content_type()

class Links(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.items = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a' and a.get('href'): self.items.append(('href', a['href']))
        if tag in ('img', 'video', 'audio', 'source', 'embed') and a.get('src'): self.items.append(('src', a['src']))

def norm(base, link):
    try:
        u = urlsplit(urljoin(base, link.strip()))
        if u.scheme not in ('http', 'https') or (u.hostname or '').lower() not in HOSTS: return None
        return urlunsplit(('https', 'www.radha.name', quote(u.path or '/', safe="/%:@!$&'()*+,;=-._~"), u.query, ''))
    except (ValueError, TypeError): return None

def parse_robots(text):
    groups, agents, rules, delays, directed = [], [], [], [], False
    def end():
        if agents: groups.append((agents[:], rules[:], delays[:]))
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if ':' not in line: continue
        k, v = (x.strip() for x in line.split(':', 1)); k = k.lower()
        if k == 'user-agent':
            if directed: end(); agents[:] = []; rules[:] = []; delays[:] = []; directed = False
            agents.append(v.lower())
        elif agents:
            directed = True
            if k in ('allow', 'disallow') and v: rules.append((v, k == 'allow'))
            elif k == 'crawl-delay':
                try: delays.append(float(v))
                except ValueError: pass
    end()
    chosen = [g for g in groups if '*' in g[0]]
    return [r for _, rs, _ in chosen for r in rs], max([10.0] + [d for _, _, ds in chosen for d in ds])

def robots_ok(url, rules):
    u = urlsplit(url); path = u.path + ('?' + u.query if u.query else ''); hits = []
    for pat, allow in rules:
        e = pat.endswith('$'); pat = pat[:-1] if e else pat
        if re.search('^' + re.escape(pat).replace(r'\*', '.*') + ('$' if e else ''), path): hits.append((len(pat.replace('*', '')), allow))
    return max(hits)[1] if hits else True

def is_file(url):
    p = urlsplit(url).path.lower()
    return p.startswith('/sites/') or p.endswith(EXTS)

def page_ok(url, rules):
    u = urlsplit(url)
    return (u.scheme == 'https' and (u.hostname or '').lower() in HOSTS and not any(u.path.startswith(x) for x in SKIP)
            and (not u.query or bool(re.fullmatch(r'page=\d+', u.query))) and not is_file(url) and robots_ok(url, rules))

def atomic_json(path, data):
    tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'); tmp.replace(path)

def run_index(args):
    path = Path('crawl-manifest.json')
    st = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version': 2, 'visited': [], 'queue': [ROOT + '/digital-books', ROOT + '/'], 'files': {}, 'errors': []}
    for k, v in (('refused', []), ('skipped', []), ('runs', [])): st.setdefault(k, v)
    fx = Fetcher(10.0); done = 0; refused_in_row = 0; status, err = 'partial', None
    queue = deque()
    try:
        body, kind = fx.get(ROOT + '/robots.txt', 1 << 20); txt = body.decode('utf-8', 'replace')
        if kind == 'text/html' or 'user-agent:' not in txt.lower(): raise Stop('Invalid robots.txt response')
        rules, fx.delay = parse_robots(txt)
        refused = {r['url'] for r in st['refused']}
        queue = deque(sorted((u for u in st['queue'] if u not in refused), key=lambda u: 0 if urlsplit(u).path.startswith('/digital-books') else 1)); st['queue'] = []
        seen = set(st['visited']) | set(queue) | refused | {e['url'] for e in st['errors'] if 'url' in e}
        while queue and done < args.limit:
            url = queue.popleft()
            if not page_ok(url, rules): st['skipped'].append({'url': url}); continue
            done += 1
            try:
                body, kind = fx.get(url, 8 << 20)
                if kind not in ('text/html', 'application/xhtml+xml'): raise ValueError('Not HTML: ' + kind)
                lk = Links(); lk.feed(body.decode('utf-8', 'replace'))
                for src, raw in lk.items:
                    full = norm(url, raw)
                    if not full: continue
                    if is_file(full): st['files'].setdefault(full, {'first_seen_on': url, 'via': src})
                    elif src == 'href' and page_ok(full, rules) and full not in seen: seen.add(full); queue.append(full)
                st['visited'].append(url); refused_in_row = 0
                print('Indexed', url, 'files', len(st['files']), 'queued', len(queue), flush=True)
            except Refused as e:
                st['refused'].append({'url': url, 'code': e.code}); refused_in_row += 1
                print('Refused, skipping:', e, flush=True)
                if refused_in_row >= MAX_REFUSALS: raise Stop(f'{MAX_REFUSALS} refused pages in a row; stopping')
            except (HTTPError, URLError, OSError, ValueError) as e:
                st['errors'].append({'url': url, 'error': str(e)}); print('Failed:', url, e, flush=True)
        status = 'partial' if queue else 'complete_for_known_pages'
    except Stop as e:
        err, status = str(e), 'stopped'; print('Stopped:', e, flush=True)
    finally:
        st['queue'] = list(queue) + st['queue']
        st.update(crawl_status=status, scope='Page discovery only. Candidate file URLs include graphics.', updated_utc=datetime.now(timezone.utc).isoformat())
        st['runs'].append({'mode': 'index', 'attempted': done, 'status': status, 'error': err, 'at': st['updated_utc']})
        atomic_json(path, st)
    print(f"Result: {len(st['visited'])} pages, {len(st['files'])} file URLs, {len(st['queue'])} queued, {len(st['refused'])} refused; {status}", flush=True)
    return 1 if err else 0

def run_download(args):
    dest = Path(os.path.expanduser(args.dest)).resolve(); dest.mkdir(parents=True, exist_ok=True)
    mpath = Path('crawl-manifest.json')
    if not mpath.exists(): print('No crawl-manifest.json; run index first'); return 1
    urls = [u for u in json.loads(mpath.read_text(encoding='utf-8'))['files'] if urlsplit(u).path.startswith(DOC_PREFIX)]
    dpath = dest / 'downloads.json'
    ds = json.loads(dpath.read_text(encoding='utf-8')) if dpath.exists() else {}
    todo = [u for u in urls if ds.get(u, {}).get('status') != 'downloaded' and ds.get(u, {}).get('status') != 'missing'][: args.limit]
    fx = Fetcher(args.file_delay); n_ok = 0; row = 0; err = None
    try:
        for url in todo:
            rel = unquote(urlsplit(url).path[len(DOC_PREFIX):])
            target = (dest / rel).resolve()
            if dest not in target.parents: ds[url] = {'status': 'unsafe_path'}; continue
            if target.exists() and ds.get(url, {}).get('status') == 'downloaded': continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with fx.open(url) as r:
                    if r.headers.get_content_type() == 'text/html': raise Stop('Got an HTML page instead of a file (site challenge?): ' + url)
                    tmp = target.with_name(target.name + '.part'); h = hashlib.sha256(); size = 0
                    with open(tmp, 'wb') as f:
                        while True:
                            chunk = r.read(1 << 20)
                            if not chunk: break
                            size += len(chunk)
                            if size > 200 << 20: raise ValueError('File exceeds 200 MB cap')
                            h.update(chunk); f.write(chunk)
                    tmp.replace(target)
                ds[url] = {'status': 'downloaded', 'path': rel, 'bytes': size, 'sha256': h.hexdigest()}; n_ok += 1; row = 0
                print('Saved', rel, size, flush=True)
            except Refused as e:
                ds[url] = {'status': 'refused', 'code': e.code}; row += 1; print('Refused, skipping:', e, flush=True)
                if row >= MAX_REFUSALS: raise Stop(f'{MAX_REFUSALS} refused files in a row; stopping')
            except HTTPError as e:
                ds[url] = {'status': 'missing' if e.code == 404 else 'error', 'code': e.code}; print('HTTP', e.code, url, flush=True)
            except (URLError, OSError, ValueError) as e:
                ds[url] = {'status': 'error', 'error': str(e)}; print('Failed:', url, e, flush=True)
            if n_ok % 25 == 0: atomic_json(dpath, ds)
    except Stop as e:
        err = str(e); print('Stopped:', e, flush=True)
    finally:
        atomic_json(dpath, ds)
        counts = {}
        for v in ds.values(): counts[v['status']] = counts.get(v['status'], 0) + 1
        summary = {'updated_utc': datetime.now(timezone.utc).isoformat(), 'document_urls_known': len(urls), 'counts': counts, 'bytes_downloaded': sum(v.get('bytes', 0) for v in ds.values()), 'stopped': err}
        atomic_json(Path('download-summary.json'), summary)
    print('Download summary:', json.dumps(summary), flush=True)
    return 1 if err else 0

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--mode', choices=['index', 'download'], default='index')
    ap.add_argument('--limit', type=int, default=40); ap.add_argument('--dest', default='~/radha-name-files'); ap.add_argument('--file-delay', type=float, default=3.0)
    a = ap.parse_args()
    if not 1 <= a.limit <= 10000: ap.error('--limit must be 1 to 10000')
    return run_index(a) if a.mode == 'index' else run_download(a)

if __name__ == '__main__': raise SystemExit(main())
