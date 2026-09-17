#!/usr/bin/env python
"""Capture the staff SMS opt-in card for toll-free registration.

    source venv/bin/activate
    python scripts/sms_optin_shot.py            # writes /tmp/.../sms_optin.png
    python scripts/sms_optin_shot.py --out x.png

This is the `messagingUseCase.optInImage` for registration version 5. It drives
the real app rather than mocking the card, for the reason UI_MAGIC S14 gives: a
mock drifts from what ships and nobody notices. It reuses `landing_shots.py`'s
machinery (throwaway DB, seeded demo shop, headless Chrome over CDP).

Three things this script exists to guarantee, each one a denial that was paid for:

1. **The box is UNCHECKED.** Version 3 was denied "Pre-selected Opt-in" because
   the screenshot was staged with it ticked. The assertion below reads the LIVE
   DOM — `checkbox.checked` — not the template source, because what gets reviewed
   is a picture of the rendered page.

2. **The shop's branding is cropped out.** The page chrome carries the tenant's
   name and logo (it is their workspace). Versions 1-4 were denied for exactly
   this kind of brand confusion — registrant RS Systems, shop branding on the
   artifact. The crop is the delivery-channels card only, whose consent text
   names RS Systems in full.

3. **The disclosure is in frame** — message types, frequency, rates, STOP/HELP
   and the program/privacy/terms links all sit inside that one card, so the crop
   cannot accidentally omit one. Asserted below by text, before saving.

See docs/operations/SMS_REGISTRATION.md §3.5 for the version 5 scope.
"""

import argparse
import asyncio
import base64
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'scripts'))

import landing_shots as ls  # noqa: E402  (shares the DB/Chrome/CDP machinery)

PATH = '/tech/notifications/preferences/'

# Every phrase a reviewer looks for. If the crop loses one, stop.
REQUIRED_TEXT = [
    'RS Systems',
    'repair requests',
    'Message frequency varies',
    'data rates may apply',
    'Reply STOP to opt out',
    'HELP for help',
    'not a condition',
]


async def capture(cookie, out_path):
    from PIL import Image

    cdp = await ls.CDP.connect()
    await cdp.send('Page.enable')
    await cdp.send('Network.enable')
    await cdp.send('Network.clearBrowserCookies')
    await cdp.send('Network.setCookie', name='sessionid', value=cookie,
                   domain='127.0.0.1', path='/')
    await cdp.send('Emulation.setDeviceMetricsOverride', width=1100, height=1400,
                   deviceScaleFactor=2, mobile=False)

    await cdp.send('Page.navigate', url=ls.APP + PATH)
    await cdp.wait_event('Page.loadEventFired')
    landed = await cdp.evaluate('location.pathname')
    if landed != PATH:
        raise RuntimeError(
            f'expected {PATH}, landed on {landed} — is the demo owner a Technician?')

    await cdp.evaluate('document.fonts.ready.then(() => true)')
    await cdp.evaluate(
        'new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')

    # --- Guard 1: the box must be unchecked in the LIVE DOM -------------------
    checked = await cdp.evaluate(
        "document.querySelector('#sms-consent input[type=checkbox]').checked")
    if checked:
        raise RuntimeError(
            'ABORT — the SMS consent checkbox is CHECKED. That is exactly what '
            'version 3 was denied for ("Pre-selected Opt-in"). Screenshot the '
            'default state of a user who has not opted in.')
    ls.log('consent checkbox is unchecked (v3 denial guarded)')

    # --- Guard 2: the whole disclosure is inside the crop ---------------------
    card_text = await cdp.evaluate(
        "document.querySelector('#sms-consent').closest('div.px-6').innerText")
    missing = [t for t in REQUIRED_TEXT if t not in card_text]
    if missing:
        raise RuntimeError(f'ABORT — disclosure missing from the card: {missing}')
    ls.log(f'all {len(REQUIRED_TEXT)} required disclosure phrases in frame')

    # --- Crop to the delivery-channels card, leaving shop branding out -------
    # Span from the Contact Verification card (which shows the recipient's own
    # mobile and that it must be verified — evidence the consent is tied to a
    # number they proved they hold) down to the bottom of the consent card.
    # Both sit below the tenant-branded chrome, so the shop's name and logo stay
    # out of the artifact.
    box = await cdp.evaluate("""
        (() => {
          const headings = [...document.querySelectorAll('h3, h4, h5')];
          const contact = headings.find(h => h.textContent.includes('Contact Verification'));
          const card = document.querySelector('#sms-consent').closest('div.px-6');
          const top = contact ? contact.getBoundingClientRect()
                     : card.getBoundingClientRect();
          const bot = card.getBoundingClientRect();
          return JSON.stringify({
            x: Math.min(top.x, bot.x),
            y: top.y,
            w: Math.max(top.width, bot.width),
            h: (bot.y + bot.height) - top.y,
          });
        })()
    """)
    import json
    r = json.loads(box)
    await cdp.evaluate('window.scrollTo(0, 0); true')

    shot = await cdp.send('Page.captureScreenshot', format='png',
                          captureBeyondViewport=True)
    image = Image.open(io.BytesIO(base64.b64decode(shot['data']))).convert('RGB')

    scale = 2  # deviceScaleFactor
    pad = 8 * scale
    crop = (
        max(0, int(r['x'] * scale) - pad),
        max(0, int(r['y'] * scale) - pad),
        min(image.size[0], int((r['x'] + r['w']) * scale) + pad),
        min(image.size[1], int((r['y'] + r['h']) * scale) + pad),
    )
    image.crop(crop).save(out_path, 'PNG')
    ls.log(f'-> {out_path} ({crop[2]-crop[0]}x{crop[3]-crop[1]})')
    await cdp.send('Browser.close')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', default=str(REPO / 'sms_optin.png'))
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix='sms_optin_shot_'))
    env = dict(os.environ)
    env.update({
        'DJANGO_SETTINGS_MODULE': 'rs_systems.settings.development',
        'LOCAL_DATABASE_URL': f"sqlite:///{work / 'shot.sqlite3'}",
        'USE_AWS_DB': 'false',
        'DEBUG': 'true',
        'AWS_STORAGE_BUCKET_NAME': '',
        'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
        'PYTHONUNBUFFERED': '1',
    })

    ls.prepare_database(env)
    cookie = ls.session_cookies(env)['owner']

    server = subprocess.Popen(
        [sys.executable, 'manage.py', 'runserver',
         f'127.0.0.1:{ls.APP_PORT}', '--noreload'],
        cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    chrome = None
    try:
        ls.wait_for(f'{ls.APP}/health/')
        chrome = ls.launch_chrome(work / 'chrome-profile')
        ls.wait_for(f'http://127.0.0.1:{ls.CDP_PORT}/json/version')
        asyncio.run(capture(cookie, args.out))
    finally:
        if chrome is not None:
            chrome.terminate()
        server.terminate()
        server.wait(timeout=10)
        shutil.rmtree(work, ignore_errors=True)
    ls.log('done')


if __name__ == '__main__':
    main()
