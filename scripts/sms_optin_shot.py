#!/usr/bin/env python
"""Capture the staff SMS opt-in FLOW, start to finish, for toll-free registration.

    source venv/bin/activate
    python scripts/sms_optin_shot.py            # writes ./sms_optin.png
    python scripts/sms_optin_shot.py --out x.png --keep-frames

This is the `messagingUseCase.optInImage` for registration version 7. It drives
the real app rather than mocking it, for the reason UI_MAGIC S14 gives: a mock
drifts from what ships and nobody notices. It reuses `landing_shots.py`'s
machinery (throwaway DB, seeded demo shop, headless Chrome over CDP).

The output is ONE image of three numbered steps under an RS Systems header:

  1. Sign in at rssystems.io/login/ (signed out, RS Systems branded).
  2. Settings > Notifications, default state: the text box is UNCHECKED.
  3. The same page after the user ticks it and saves: consent recorded.

Each step is a guard against a denial that was paid for:

- **v3 "Pre-selected Opt-in"**: step 2 reads the LIVE DOM `checkbox.checked`
  and aborts if it is ticked. Step 3 is the user's own action, and is captioned so.
- **v6 "Incomplete Opt-in Example — incomplete or lacks proper branding"**: v6
  sent a crop of the consent card alone, with the page chrome cut off. Every
  frame now carries the RS Systems navbar or sign-in page, and the flow runs
  from sign-in to the saved consent. Asserted by text before saving.
- **v1-v4 brand confusion**: the demo shop is put on the Starter plan, which has
  no custom branding, so the navbar renders the platform's "RS Systems" mark — as
  it does for every shop without that feature — and the shop's own name appears
  nowhere visible. Asserted: the shop name is absent from every frame's text.

See docs/operations/SMS_REGISTRATION.md §3.7 for version 7.
"""

import argparse
import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'scripts'))

import landing_shots as ls  # noqa: E402  (shares the DB/Chrome/CDP machinery)

LOGIN = '/login/'
PATH = '/tech/notifications/preferences/'
SHOP_NAME = 'Clearview'  # seed_demo_shop's business name; must never be visible
SCALE = 2                # deviceScaleFactor
WIDTH = 1100

# Every phrase a reviewer looks for. If the frame loses one, stop.
REQUIRED_TEXT = [
    'RS Systems',
    'repair requests',
    'Message frequency varies',
    'data rates may apply',
    'Reply STOP to opt out',
    'HELP for help',
    'not a condition',
]

STEPS = [
    ('Sign in to RS Systems',
     'The opt-in lives inside the RS Systems web app, at https://rssystems.io/login/. '
     'Only RS Systems account holders (shop owners and technicians) can reach it.'),
    ('Open Settings &gt; Notifications — the text box is unchecked',
     'Default state for every user. In-app and email are on; "Text me urgent job '
     'alerts" is empty and never pre-selected. The full disclosure sits beside it.'),
    ('The user ticks the box and saves — consent is recorded',
     'Only the user can opt themselves in. The page confirms the date of consent; '
     'texts start once their mobile number is verified. Reply STOP to opt out at any time.'),
]

PREP = """
from apps.tenants.management.commands.seed_demo_shop import DEMO_SLUG
from apps.tenants.models import Tenant, SubscriptionPlan
from apps.technician_portal.models import Technician
from django.utils import timezone
t = Tenant.objects.get(slug=DEMO_SLUG)
t.plan = 'starter'
t.subscription_plan = SubscriptionPlan.objects.get(slug='starter')
t.save()
for tech in Technician.objects.filter(tenant=t, user__email__startswith='sam@'):
    tech.phone_verified = tech.email_verified = True
    tech.phone_verified_at = tech.email_verified_at = timezone.now()
    tech.save()
    # The demo domain is the shop's name; keep it out of the frame.
    tech.user.email = 'sam@example.com'
    tech.user.save()
"""


async def settle(cdp):
    await cdp.evaluate('document.fonts.ready.then(() => true)')
    # A cross-document view transition is still painting its snapshot when
    # load fires; capture then and the frame comes out squashed.
    await cdp.evaluate('new Promise(r => setTimeout(r, 900))')
    await cdp.evaluate(
        'new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')


async def goto(cdp, url):
    await cdp.send('Page.navigate', url=url)
    await cdp.wait_event('Page.loadEventFired')
    await settle(cdp)


async def visible_text(cdp):
    return await cdp.evaluate('document.body.innerText')


def assert_no_shop_brand(text, step):
    if SHOP_NAME.lower() in text.lower():
        raise RuntimeError(
            f'ABORT — step {step} shows the shop name {SHOP_NAME!r}. A shop brand on '
            'an RS Systems registration is the confusion v1-v4 were denied for.')


async def shoot(cdp, bottom=None):
    """Full-width capture from the top of the page (navbar included)."""
    await cdp.evaluate('window.scrollTo(0, 0); true')
    shot = await cdp.send('Page.captureScreenshot', format='png',
                          captureBeyondViewport=True)
    from PIL import Image
    image = Image.open(io.BytesIO(base64.b64decode(shot['data']))).convert('RGB')
    if bottom is not None:
        image = image.crop((0, 0, image.size[0], min(image.size[1], int(bottom * SCALE))))
    return image


async def consent_bottom(cdp):
    return await cdp.evaluate(
        "(() => { const c = document.querySelector('#sms-consent').closest('div.px-6');"
        " return c.getBoundingClientRect().bottom + window.scrollY + 16; })()")


async def capture(cookie, frames_dir):
    cdp = await ls.CDP.connect()
    await cdp.send('Page.enable')
    await cdp.send('Network.enable')
    await cdp.send('Network.clearBrowserCookies')
    await cdp.send('Emulation.setDeviceMetricsOverride', width=WIDTH, height=820,
                   deviceScaleFactor=SCALE, mobile=False)
    await cdp.send('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    frames = []

    # --- Step 1: signed-out sign-in page --------------------------------------
    await goto(cdp, ls.APP + LOGIN)
    text = await visible_text(cdp)
    if 'RS Systems' not in text:
        raise RuntimeError('ABORT — the sign-in page does not identify RS Systems')
    assert_no_shop_brand(text, 1)
    frames.append(await shoot(cdp, bottom=820))
    ls.log('step 1: sign-in page')

    # --- Step 2: default state, box unchecked ---------------------------------
    await cdp.send('Network.setCookie', name='sessionid', value=cookie,
                   domain='127.0.0.1', path='/')
    await goto(cdp, ls.APP + PATH)
    landed = await cdp.evaluate('location.pathname')
    if landed != PATH:
        raise RuntimeError(
            f'expected {PATH}, landed on {landed} — is the demo owner a Technician?')
    checked = await cdp.evaluate(
        "document.querySelector('#sms-consent input[type=checkbox]').checked")
    if checked:
        raise RuntimeError(
            'ABORT — the SMS consent checkbox is CHECKED by default. That is exactly '
            'what version 3 was denied for ("Pre-selected Opt-in").')
    card_text = await cdp.evaluate(
        "document.querySelector('#sms-consent').closest('div.px-6').innerText")
    missing = [t for t in REQUIRED_TEXT if t not in card_text]
    if missing:
        raise RuntimeError(f'ABORT — disclosure missing from the card: {missing}')
    nav_text = await cdp.evaluate("document.querySelector('nav').innerText")
    if 'RS Systems' not in nav_text:
        raise RuntimeError(
            f'ABORT — the navbar does not read "RS Systems" ({nav_text[:60]!r}). '
            'v6 was denied as unbranded; the brand must be in frame.')
    assert_no_shop_brand(await visible_text(cdp), 2)
    frames.append(await shoot(cdp, bottom=await consent_bottom(cdp)))
    ls.log('step 2: unchecked by default, disclosure + RS Systems navbar in frame')

    # --- Step 3: the user ticks it and saves ----------------------------------
    await cdp.evaluate(
        "document.querySelector('#sms-consent input[type=checkbox]').click(); true")
    await cdp.evaluate(
        "document.querySelector('#preferences-form button[type=submit]').click(); true")
    await cdp.wait_event('Page.loadEventFired')
    await settle(cdp)
    checked = await cdp.evaluate(
        "document.querySelector('#sms-consent input[type=checkbox]').checked")
    text = await visible_text(cdp)
    if not checked or 'You agreed to texts on' not in text:
        raise RuntimeError('ABORT — saving the opt-in did not record consent')
    assert_no_shop_brand(text, 3)
    frames.append(await shoot(cdp, bottom=await consent_bottom(cdp)))
    ls.log('step 3: consent saved and confirmed')

    paths = []
    for i, frame in enumerate(frames, 1):
        p = frames_dir / f'step{i}.png'
        frame.save(p, 'PNG')
        paths.append(p)
    return cdp, paths


def composite_html(frame_paths):
    parts = []
    for (title, body), path in zip(STEPS, frame_paths):
        n = len(parts) + 1
        data = base64.b64encode(path.read_bytes()).decode()
        parts.append(f"""
        <section>
          <h2><span>{n}</span>{title}</h2>
          <p>{body}</p>
          <img src="data:image/png;base64,{data}">
        </section>""")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      body {{ margin: 0; background: #f3f4f6; font: 16px/1.45 -apple-system, 'Helvetica Neue', Arial, sans-serif; color: #111827; }}
      header {{ background: #1e3a8a; color: #fff; padding: 22px 32px; }}
      header h1 {{ margin: 0; font-size: 26px; }}
      header p {{ margin: 6px 0 0; font-size: 15px; opacity: .9; }}
      main {{ padding: 8px 32px 32px; }}
      section {{ margin-top: 24px; }}
      h2 {{ font-size: 20px; margin: 0 0 4px; display: flex; align-items: center; gap: 10px; }}
      h2 span {{ background: #1e3a8a; color: #fff; border-radius: 50%; width: 30px; height: 30px;
                 display: inline-flex; align-items: center; justify-content: center; font-size: 16px; }}
      section p {{ margin: 0 0 10px 40px; color: #374151; font-size: 15px; }}
      img {{ width: {WIDTH}px; display: block; border: 1px solid #d1d5db; border-radius: 6px;
             box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
    </style></head><body>
      <header>
        <h1>RS Systems &mdash; text message opt-in (account notifications)</h1>
        <p>rssystems.io &middot; toll-free +1 866-311-5189 &middot; messages go only to RS Systems'
           own registered users, who opt themselves in below.</p>
      </header>
      <main>{''.join(parts)}</main>
    </body></html>"""


async def render_composite(cdp, html_path, out_path):
    from PIL import Image
    await cdp.send('Emulation.setDeviceMetricsOverride', width=WIDTH + 66, height=900,
                   deviceScaleFactor=1, mobile=False)
    await goto(cdp, html_path.as_uri())
    shot = await cdp.send('Page.captureScreenshot', format='png',
                          captureBeyondViewport=True)
    image = Image.open(io.BytesIO(base64.b64decode(shot['data']))).convert('RGB')
    image.save(out_path, 'PNG', optimize=True)
    size = out_path.stat().st_size
    ls.log(f'-> {out_path} ({image.size[0]}x{image.size[1]}, {size // 1024} KB)')
    await cdp.send('Browser.close')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', default=str(REPO / 'sms_optin.png'))
    parser.add_argument('--keep-frames', action='store_true',
                        help='Also write the three raw frames next to --out.')
    args = parser.parse_args()
    out = Path(args.out).resolve()

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
    cookie = ls.session_cookies(env)['owner']  # looks the owner up by demo email,
    subprocess.run([sys.executable, 'manage.py', 'shell', '-c', PREP], cwd=REPO,
                   env=env, check=True, stdout=subprocess.DEVNULL)  # so rename after

    server = subprocess.Popen(
        [sys.executable, 'manage.py', 'runserver',
         f'127.0.0.1:{ls.APP_PORT}', '--noreload'],
        cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    chrome = None
    try:
        ls.wait_for(f'{ls.APP}/health/')
        chrome = ls.launch_chrome(work / 'chrome-profile')
        ls.wait_for(f'http://127.0.0.1:{ls.CDP_PORT}/json/version')

        async def run():
            cdp, frames = await capture(cookie, work)
            html = work / 'composite.html'
            html.write_text(composite_html(frames))
            await render_composite(cdp, html, out)
            if args.keep_frames:
                for f in frames:
                    shutil.copy(f, out.with_name(f'{out.stem}_{f.name}'))

        asyncio.run(run())
    finally:
        if chrome is not None:
            chrome.terminate()
        server.terminate()
        server.wait(timeout=10)
        shutil.rmtree(work, ignore_errors=True)
    ls.log('done')


if __name__ == '__main__':
    main()
