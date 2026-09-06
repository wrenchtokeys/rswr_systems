#!/usr/bin/env python
"""Regenerate the landing page's product screenshots from the real app.

    source venv/bin/activate
    python scripts/landing_shots.py            # writes static/images/landing/*.webp
    python scripts/landing_shots.py --keep     # leave the server + DB up for a look

What it does, start to finish, with no hands on it:

1. Points Django at a throwaway SQLite database, migrates it, seeds plans,
   groups and templates, then builds the fictional demo shop
   (``manage.py seed_demo_shop``).
2. Starts ``runserver`` on a spare port.
3. Launches the installed Chrome headless, talks to it over the DevTools
   protocol (tornado's websocket client — already in the venv), logs in by
   handing it a real Django session cookie, and captures each page in
   ``SHOTS`` at the device size it names.
4. Writes each capture to ``static/images/landing/<name>.webp`` and stops
   everything it started.

Why a script and not a hand-made mock (UI_MAGIC_SESSIONS S14): the mock
drifted from the real dashboard, then the real dashboard was redesigned and
the mock's error changed shape without anyone editing either file. A
screenshot cannot do that — but only if it is cheap enough to re-take, so
this is one command. Run it after any visible change to the pages it shoots
and commit the output; ``tests/test_landing_credibility.py`` checks the files
exist and that the landing page references them.

Fonts, icons and CSS are all same-origin (no CDN anywhere in this app), so a
capture needs no network beyond 127.0.0.1.
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / 'static' / 'images' / 'landing'
APP_PORT = int(os.environ.get('LANDING_SHOTS_PORT', '8765'))
CDP_PORT = int(os.environ.get('LANDING_SHOTS_CDP_PORT', '9333'))
APP = f'http://127.0.0.1:{APP_PORT}'

CHROME_CANDIDATES = [
    os.environ.get('CHROME_BIN', ''),
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    shutil.which('google-chrome') or '',
    shutil.which('chromium') or '',
    shutil.which('chromium-browser') or '',
]

# name, who is logged in, path, viewport (width, height, mobile)
DESKTOP = (1280, 800, False)
PHONE = (390, 844, True)
SHOTS = [
    # 90 days so the sparkline has a shape; "this month" on the 2nd is a flat line.
    ('owner-dashboard', 'owner', '/owner/?period=90d', DESKTOP),
    ('jobs-list', 'owner', '/tech/jobs/', DESKTOP),
    ('job-form-phone', 'owner', '/tech/jobs/new/', PHONE),
    ('customer-portal-phone', 'customer', '/app/', PHONE),
]


def log(msg):
    print(f'[landing_shots] {msg}', flush=True)


# ----------------------------------------------------------------- Django side

def prepare_database(env):
    """Migrate + seed the throwaway DB. Runs manage.py as subprocesses so the
    capture process itself never imports the project before the env is set."""
    steps = [
        ['migrate', '-v0'],
        ['seed_plans'],
        ['setup_groups'],
        ['setup_notification_templates'],
        ['seed_demo_shop', '--reset'],
    ]
    for step in steps:
        log('manage.py ' + ' '.join(step))
        subprocess.run([sys.executable, 'manage.py', *step], cwd=REPO, env=env,
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def session_cookies(env):
    """One logged-in session per persona, minted the way the app itself does.

    ``Client.force_login`` writes a real row to django_session in the same
    SQLite file the dev server reads, so the cookie value is valid there.
    """
    os.environ.update(env)
    sys.path.insert(0, str(REPO))
    import django
    django.setup()
    from django.contrib.auth.models import User
    from django.test import Client
    from apps.tenants.management.commands.seed_demo_shop import DEMO_DOMAIN, DEMO_SLUG
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.get(slug=DEMO_SLUG)
    personas = {
        'owner': User.objects.get(email=f'sam@{DEMO_DOMAIN}'),
        'customer': User.objects.get(email=f'fleet@{DEMO_DOMAIN}'),
    }
    cookies = {}
    for name, user in personas.items():
        client = Client()
        client.force_login(user)
        session = client.session
        session['tenant_id'] = tenant.id
        session.save()
        cookies[name] = client.cookies['sessionid'].value
    return cookies


def wait_for(url, timeout=30):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001 - server not up yet
            last = exc
        time.sleep(0.3)
    raise RuntimeError(f'{url} never came up: {last}')


# ----------------------------------------------------------------- Chrome side

def find_chrome():
    for path in CHROME_CANDIDATES:
        if path and Path(path).exists():
            return path
    raise RuntimeError('No Chrome/Chromium found; set CHROME_BIN.')


def launch_chrome(profile_dir):
    return subprocess.Popen([
        find_chrome(),
        '--headless=new',
        f'--remote-debugging-port={CDP_PORT}',
        f'--user-data-dir={profile_dir}',
        '--no-first-run', '--no-default-browser-check',
        '--hide-scrollbars', '--disable-gpu',
        '--force-device-scale-factor=2',
        'about:blank',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class CDP:
    """The dozen lines of DevTools protocol this needs."""

    def __init__(self, ws):
        self.ws = ws
        self.next_id = 0
        self.events = asyncio.Queue()

    @classmethod
    async def connect(cls):
        from tornado.websocket import websocket_connect
        req = urllib.request.Request(
            f'http://127.0.0.1:{CDP_PORT}/json/new?about:blank', method='PUT')
        with urllib.request.urlopen(req) as resp:
            target = json.load(resp)
        ws = await websocket_connect(target['webSocketDebuggerUrl'], max_message_size=64 * 2 ** 20)
        return cls(ws)

    async def send(self, method, **params):
        self.next_id += 1
        msg_id = self.next_id
        await self.ws.write_message(json.dumps({'id': msg_id, 'method': method, 'params': params}))
        while True:
            raw = await self.ws.read_message()
            if raw is None:
                raise RuntimeError('DevTools socket closed')
            msg = json.loads(raw)
            if msg.get('id') == msg_id:
                if 'error' in msg:
                    raise RuntimeError(f'{method}: {msg["error"]}')
                return msg.get('result', {})
            if 'method' in msg:
                await self.events.put(msg)

    async def wait_event(self, name, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = await asyncio.wait_for(self.ws.read_message(), timeout=deadline - time.time())
            if raw is None:
                raise RuntimeError('DevTools socket closed')
            msg = json.loads(raw)
            if msg.get('method') == name:
                return msg
        raise TimeoutError(name)

    async def evaluate(self, expression):
        result = await self.send('Runtime.evaluate', expression=expression,
                                 awaitPromise=True, returnByValue=True)
        return result.get('result', {}).get('value')


async def capture_all(cookies, out_dir):
    from PIL import Image
    import io

    cdp = await CDP.connect()
    await cdp.send('Page.enable')
    await cdp.send('Network.enable')
    await cdp.send('Emulation.setFocusEmulationEnabled', enabled=True)

    for name, persona, path, (width, height, mobile) in SHOTS:
        log(f'{name}: {persona} @ {path} ({width}x{height})')
        await cdp.send('Network.clearBrowserCookies')
        await cdp.send('Network.setCookie', name='sessionid', value=cookies[persona],
                       domain='127.0.0.1', path='/')
        await cdp.send('Emulation.setDeviceMetricsOverride', width=width, height=height,
                       deviceScaleFactor=2, mobile=mobile)
        if mobile:
            await cdp.send('Emulation.setTouchEmulationEnabled', enabled=True, maxTouchPoints=5)
            await cdp.send('Emulation.setUserAgentOverride', userAgent=(
                'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
                'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'))
        else:
            await cdp.send('Emulation.setTouchEmulationEnabled', enabled=False)
            await cdp.send('Emulation.setUserAgentOverride', userAgent='')

        await cdp.send('Page.navigate', url=APP + path)
        await cdp.wait_event('Page.loadEventFired')
        landed = await cdp.evaluate('location.pathname')
        if landed != path.split('?')[0]:
            raise RuntimeError(f'{name}: expected to land on {path}, got {landed} '
                               '(login cookie rejected?)')
        # Fonts + any deferred scripts, then two frames for layout to settle.
        await cdp.evaluate('document.fonts.ready.then(() => true)')
        await cdp.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        await asyncio.sleep(0.4)
        await cdp.evaluate('window.scrollTo(0, 0); true')

        shot = await cdp.send('Page.captureScreenshot', format='png',
                              captureBeyondViewport=False)
        import base64
        image = Image.open(io.BytesIO(base64.b64decode(shot['data']))).convert('RGB')
        target = out_dir / f'{name}.webp'
        image.save(target, 'WEBP', quality=88, method=6)
        log(f'  -> {target.relative_to(REPO)} {image.size[0]}x{image.size[1]} '
            f'{target.stat().st_size // 1024} KB')

    await cdp.send('Browser.close')


# --------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--keep', action='store_true',
                        help='Leave the dev server (and its DB) running afterwards.')
    parser.add_argument('--out', default=str(OUT_DIR), help='Output directory.')
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='landing_shots_'))
    db_path = work / 'shots.sqlite3'

    env = dict(os.environ)
    env.update({
        'DJANGO_SETTINGS_MODULE': 'rs_systems.settings.development',
        'LOCAL_DATABASE_URL': f'sqlite:///{db_path}',
        'USE_AWS_DB': 'false',
        'DEBUG': 'true',
        # The seeder refuses to run without DEBUG; the capture must never
        # touch a real bucket or mailbox either.
        'AWS_STORAGE_BUCKET_NAME': '',
        'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
        'PYTHONUNBUFFERED': '1',
    })

    prepare_database(env)
    cookies = session_cookies(env)

    server = subprocess.Popen(
        [sys.executable, 'manage.py', 'runserver', f'127.0.0.1:{APP_PORT}', '--noreload'],
        cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    chrome = None
    try:
        wait_for(f'{APP}/health/')
        log(f'dev server up on {APP}')
        chrome = launch_chrome(work / 'chrome-profile')
        wait_for(f'http://127.0.0.1:{CDP_PORT}/json/version')
        asyncio.run(capture_all(cookies, out_dir))
    finally:
        if chrome is not None:
            chrome.terminate()
        if args.keep:
            log(f'--keep: server still running on {APP} (pid {server.pid}); DB at {db_path}')
        else:
            server.terminate()
            server.wait(timeout=10)
            shutil.rmtree(work, ignore_errors=True)
    log('done')


if __name__ == '__main__':
    main()
