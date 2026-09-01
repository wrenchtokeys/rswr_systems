"""Toll-free registration resubmit for +18663115189 (RS Systems).

Two traps this script exists to defuse, both learned by being denied:

1. create_registration_version() opens an EMPTY draft — it does not inherit the
   previous version's field values. Every required field has to be re-put or the
   submission is auto-denied "Missing required field" within seconds (that is
   what happened to version 2). So we copy a known-good base version wholesale,
   apply overrides, and refuse to submit if anything REQUIRED is still empty.

2. The base version carries whatever was wrong last time. Copying v1 blindly is
   how `contactInfo.supportEmail` stayed at drake@rockstarwindshield.repair —
   inherited from the *other* (approved) registration for Rockstar Windshield
   Repair, whose domain legitimately matched its own website. On RS Systems it
   does not match the company name or rssystems.io, and v3 was denied
   "Unofficial Business Email" for exactly that. Overrides are explicit below.

Denial history for registration-3c4aceac…:
  v1  denied 2026-08-11  Unclear Opt-in Language
  v2  denied 2026-08-25  Missing required field (trap 1)
  v3  denied 2026-08-26  Unofficial Business Email + Pre-selected Opt-in

On v3's "Pre-selected Opt-in": the shipping UI was never pre-checked —
templates/billing/public_invoice_view.html renders
`<input type="checkbox" name="sms_agree" value="1" required>` with no `checked`
attribute. The old optInDescription described it as "a checked box", meaning
"a box they check", and the reviewer read that as pre-selected. The wording is
now explicit that the box is unchecked and requires an affirmative click.

Usage:
    python scripts/submit_tollfree_registration.py <screenshot.png> <description.txt>

The screenshot must show the opt-in card in its DEFAULT state with the box
visibly UNCHECKED. Regenerate it from the real template rather than hand-mocking
it — a mock that drifts from what ships is its own denial reason.
"""
import sys, boto3

REG = 'registration-3c4aceac54424845b6d540e818f2bddb'
BASE_VERSION = 3          # latest reviewed version; overrides below fix its 2 denials
SUPPORT_EMAIL = 'support@rssystems.io'   # must match companyInfo.website (rssystems.io)

SHOT = sys.argv[1]
DESC = open(sys.argv[2]).read().strip()

c = boto3.client('pinpoint-sms-voice-v2', region_name='us-east-1')

att = c.create_registration_attachment(AttachmentBody=open(SHOT, 'rb').read())['RegistrationAttachmentId']
print(f'screenshot uploaded: {att}')

base = c.describe_registration_field_values(RegistrationId=REG, VersionNumber=BASE_VERSION)['RegistrationFieldValues']
fields = {}
for f in base:
    for key in ('TextValue', 'SelectChoices', 'RegistrationAttachmentId'):
        if f.get(key):
            fields[f['FieldPath']] = {key: f[key]}

fields['contactInfo.supportEmail'] = {'TextValue': SUPPORT_EMAIL}
fields['messagingUseCase.optInDescription'] = {'TextValue': DESC}
fields['messagingUseCase.optInImage'] = {'RegistrationAttachmentId': att}

# The denial that started all this: a support email on someone else's domain.
website = fields.get('companyInfo.website', {}).get('TextValue', '')
if website and not SUPPORT_EMAIL.lower().endswith('@' + website.lower()):
    sys.exit(f'ABORT — supportEmail {SUPPORT_EMAIL} does not match website {website}')

ver = c.create_registration_version(RegistrationId=REG)['VersionNumber']
print(f'draft version {ver} opened; writing {len(fields)} fields')
for path, kwargs in sorted(fields.items()):
    c.put_registration_field_value(RegistrationId=REG, FieldPath=path, **kwargs)

missing = [d['FieldPath'] for d in c.describe_registration_field_definitions(
              RegistrationType='US_TOLL_FREE_REGISTRATION')['RegistrationFieldDefinitions']
           if d['FieldRequirement'] == 'REQUIRED' and d['FieldPath'] not in fields]
if missing:
    sys.exit(f'ABORT — required fields still empty, not submitting: {missing}')
print('all required fields present; submitting')

c.submit_registration_version(RegistrationId=REG)
for v in c.describe_registration_versions(RegistrationId=REG)['RegistrationVersions']:
    print(f"  version {v['VersionNumber']}: {v['RegistrationVersionStatus']}"
          f"{' — ' + '; '.join(r['Reason'] for r in v.get('DeniedReasons', [])) if v.get('DeniedReasons') else ''}")
