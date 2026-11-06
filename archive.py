#!/usr/bin/env python3
"""Bounded Radha.name discovery and an explicitly approved three-file pilot."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = 'https://www.radha.name'
HOSTS = {'radha.name', 'www.radha.name'}
AGENT = 'RadhaArchivePilot/1.0 (three-file test; respectful crawl)'
PILOT = [
    ('Divisions Of Devotion.doc', ROOT + '/sites/default/files/documents/1244/Divisions%20Of%20Devotion.doc'),
    ('Nityananda Charitamrita.pdf', ROOT + '/sites/default/files/documents/1244/Nityananda%20Charitamrita.pdf'),
    ('Japa Tips - by Umapati Swami.doc', ROOT + '/sites/default/files/documents/1357/Japa%20Tips%20-%20by%20Umapati%20Swami.doc'),
]
SKIP_PAGES = ('/sites/', '/includes/', '/misc/', '/modules/', '/profiles/', '/scripts/', '/themes/', '/vote/', '/admin/', '/comment/', '/contact', '/logout', '/node/add/', '/search/', '/user/')
EXTENSIONS = {'.pdf', '.doc', '.docx', '.rtf', '.odt', '.txt', '.epub', '.mobi', '.zip', '.rar', '.7z', '.xls', '.xlsx', '.ppt', '.pptx', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.mp3', '.mp4', '.wav', '.avi', '.mov', '.m4a', '.flv', '.ogg'}

class Blocked(Exception):
    pass

class SameSiteRedirect(HTTPRedirectHandler):
    def __init__(self, fetcher):
        super().__init__()
        self.fetcher = fetcher
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urlsplit(newurl)
        if u.scheme != 'https' or (u.hostname or '').lower() not in HOSTS:
            raise Blocked('Cross-site or non-HTTPS redirect refused: ' + newurl)
        if self.fetcher.page_rules is not None and not is_page(newurl, self.fetcher.page_rules):
            raise Blocked('Restricted page redirect refused: ' + newurl)
        self.fetcher.throttle()
        return super().redirect_request(req, fp, code, msg, headers, newurl)

class Fetcher:
    def __init__(self):
        self.last = 0.0
        self.delay = 10.0
        self.page_rules = None
        self.opener = build_opener(SameSiteRedirect(self))

    def throttle(self):
        pause = self.delay - (time.monotonic() - self.last)
        if pause > 0:
            time.sleep(pause)
        self.last = time.monotonic()

    def get(self, url, limit):
        self.throttle()
        request = Request(url, headers={'User-Agent': AGENT, 'Accept': '*/*'})
        try:
            with self.opener.open(request, timeout=35) as response:
                final = urlsplit(response.geturl())
                if final.scheme != 'https' or (final.hostname or '').lower() not in HOSTS:
                    raise Blocked('Unexpected redirect destination')
                content_type = response.headers.get_content_type()
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise ValueError('Response exceeds size limit')
                return body, content_type
        except HTTPError as exc:
            if exc.code in (401, 403, 429):
                raise Blocked(f'Site refused {url} (HTTP {exc.code}); stopped') from exc
            raise

class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            self.links.append(('href', attrs['href']))
        if tag in ('img', 'video', 'audio', 'source', 'embed') and attrs.get('src'):
            self.links.append(('src', attrs['src']))

def normalise(base, link):
    try:
        u = urlsplit(urljoin(base, link.strip()))
        if u.scheme not in ('http', 'https') or (u.hostname or '').lower() not in HOSTS:
            return None
        path = quote(u.path or '/', safe="/%:@!$&'()*+,;=-._~")
        # Collapse both site hostnames to the HTTPS canonical host and discard fragments.
        return urlunsplit(('https', 'www.radha.name', path, u.query, ''))
    except (ValueError, TypeError):
        return None

def parse_robots(text):
    groups, agents, rules, delay = [], [], [], []
    had_directive = False
    def finish():
        if agents:
            groups.append((agents[:], rules[:], delay[:]))
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if ':' not in line:
            continue
        key, val = (x.strip() for x in line.split(':', 1))
        key = key.lower()
        if key == 'user-agent':
            if had_directive:
                finish(); agents, rules, delay = [], [], []
                had_directive = False
            agents.append(val.lower())
        elif agents:
            had_directive = True
            if key in ('allow', 'disallow') and val:
                rules.append((val, key == 'allow'))
            elif key == 'crawl-delay':
                try:
                    delay.append(float(val))
                except ValueError:
                    pass
    finish()
    product = 'radhaarchivepilot'
    specific = [(a, r, d) for a, r, d in groups if any(x != '*' and x in product for x in a)]
    chosen = specific or [(a, r, d) for a, r, d in groups if '*' in a]
    return [rule for _, rs, _ in chosen for rule in rs], max([10.0] + [v for _, _, ds in chosen for v in ds])

def allowed_by_robots(url, rules):
    u = urlsplit(url)
    path = u.path + (('?' + u.query) if u.query else '')
    matches = []
    for pattern, allow in rules:
        end = pattern.endswith('$')
        if end:
            pattern = pattern[:-1]
        regex = '^' + re.escape(pattern).replace(r'\*', '.*') + ('$' if end else '')
        if re.search(regex, path):
            matches.append((len(pattern.replace('*', '')), allow))
    return max(matches)[1] if matches else True

def is_file(url):
    path = urlsplit(url).path.lower()
    return path.startswith('/sites/default/files/') or any(path.endswith(ext) for ext in EXTENSIONS)

def is_page(url, rules):
    u = urlsplit(url)
    if any(u.path.startswith(x) for x in SKIP_PAGES):
        return False
    if u.query and not re.fullmatch(r'page=\d+', u.query):
        return False
    return not is_file(url) and allowed_by_robots(url, rules)

def read_state(path):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {'version': 1, 'visited': [], 'queue': [ROOT + '/digital-books', ROOT + '/'], 'files': {}, 'pilot': {}, 'errors': []}

def save_state(path, state):
    state['updated_utc'] = datetime.now(timezone.utc).isoformat()
    state['scope'] = 'Bounded same-site HTML discovery. Only the three explicitly approved files are downloaded.'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)

def pilot_download(fetcher, state):
    folder = Path('documents')
    folder.mkdir(exist_ok=True)
    failed = False
    for name, url in PILOT:
        dest = folder / name
        prior = state['pilot'].get(name, {})
        if dest.exists() and prior.get('sha256') == hashlib.sha256(dest.read_bytes()).hexdigest():
            print('Already verified:', name, flush=True)
            continue
        try:
            data, kind = fetcher.get(url, 20 * 1024 * 1024)
            expected = b'%PDF-' if name.endswith('.pdf') else bytes.fromhex('d0cf11e0a1b11ae1')
            if kind == 'text/html' or not data.startswith(expected):
                raise ValueError('Unexpected response, not the expected PDF/Word document')
            tmp = dest.with_name(dest.name + '.part')
            tmp.write_bytes(data)
            tmp.replace(dest)
            state['pilot'][name] = {'url': url, 'status': 'downloaded', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            print(f'Downloaded: {name} ({len(data)} bytes)', flush=True)
        except Blocked as exc:
            state['pilot'][name] = {'url': url, 'status': 'blocked', 'error': str(exc)}
            raise
        except (HTTPError, URLError, OSError, ValueError) as exc:
            state['pilot'][name] = {'url': url, 'status': 'failed', 'error': str(exc)}
            print('Download failed:', name, str(exc), flush=True)
            failed = True
    return failed

def visit(fetcher, state, rules):
    url = state['queue'].pop(0)
    if not is_page(url, rules):
        state.setdefault('skipped', []).append({'url': url, 'reason': 'not allowed for page crawling'})
        print('Skipped restricted page:', url, flush=True)
        return
    try:
        fetcher.page_rules = rules
        body, kind = fetcher.get(url, 8 * 1024 * 1024)
        if kind not in ('text/html', 'application/xhtml+xml'):
            raise ValueError('Not an HTML page: ' + kind)
        parser = Links()
        parser.feed(body.decode('utf-8', errors='replace'))
        seen_pages = set(state['visited']) | set(state['queue']) | {url}
        seen_pages.update(e['url'] for e in state['errors'] if 'url' in e)
        for attr, link in parser.links:
            full = normalise(url, link)
            if not full:
                continue
            if is_file(full):
                state['files'].setdefault(full, {'first_seen_on': url, 'via': attr})
            elif attr == 'href' and is_page(full, rules) and full not in seen_pages:
                seen_pages.add(full)
                state['queue'].append(full)
        state['visited'].append(url)
        print(f"Visited {url}; {len(state['files'])} candidate file URLs; {len(state['queue'])} pages queued", flush=True)
    except Blocked:
        state['queue'].insert(0, url)
        raise
    except (HTTPError, URLError, OSError, ValueError) as exc:
        state['errors'].append({'url': url, 'error': str(exc)})
        print('Page failed:', url, str(exc), flush=True)
    finally:
        fetcher.page_rules = None

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--max-pages', type=int, default=20)
    args = p.parse_args()
    if not 1 <= args.max_pages <= 40:
        p.error('--max-pages must be between 1 and 40')
    path = Path('crawl-manifest.json')
    state = read_state(path)
    fetcher = Fetcher()
    failed = False
    try:
        robots, kind = fetcher.get(ROOT + '/robots.txt', 1024 * 1024)
        robots_text = robots.decode('utf-8', errors='replace')
        if kind == 'text/html' or 'user-agent:' not in robots_text.lower():
            raise Blocked('robots.txt was not a valid crawler-policy response; stopped')
        rules, fetcher.delay = parse_robots(robots_text)
        state['robots'] = {'url': ROOT + '/robots.txt', 'crawl_delay_seconds': fetcher.delay, 'rule_count': len(rules)}
        if state['queue']:
            visit(fetcher, state, rules)
            visited_this_run = 1
        else:
            visited_this_run = 0
        failed = pilot_download(fetcher, state)
        while state['queue'] and visited_this_run < args.max_pages:
            visit(fetcher, state, rules)
            visited_this_run += 1
        state['crawl_status'] = 'partial' if state['queue'] else ('partial_errors' if state['errors'] else 'exhausted_known_queue')
    except (Blocked, HTTPError, URLError, OSError, ValueError) as exc:
        state['crawl_status'] = 'blocked_or_failed'
        state['errors'].append({'stage': 'run', 'error': str(exc)})
        print('Stopped:', str(exc), flush=True)
        failed = True
    finally:
        save_state(path, state)
    print(f"Result: {len(state['visited'])} pages visited, {len(state['files'])} candidate URLs, {len(state['queue'])} queued; status={state['crawl_status']}", flush=True)
    return 1 if failed else 0

if __name__ == '__main__':
    raise SystemExit(main())
