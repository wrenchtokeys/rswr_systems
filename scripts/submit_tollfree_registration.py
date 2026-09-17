"""Toll-free registration version 5 for +18663115189 (RS Systems) — STAFF SCOPE.

    python scripts/submit_tollfree_registration.py <screenshot.png>            # validate only
    python scripts/submit_tollfree_registration.py <screenshot.png> --submit   # really file it

Generate the screenshot with `python scripts/sms_optin_shot.py` — it renders the
real Settings -> Notifications page and refuses to save a checked box.

WHY VERSION 5 IS SCOPED DIFFERENTLY
-----------------------------------
Versions 1-4 were all denied, and all four described RS Systems texting a SHOP'S
CUSTOMERS on that shop's behalf. Toll-free verification registers ONE business,
and carriers require the verification and the opt-in to reflect the END business
(Twilio rejection 30506). Registrant "RS Systems" + samples branded "Hensley Auto
Glass" is a Message Use Case Mismatch no wording fixes -- that was v4's denial.

This version covers the other audience, which was never submitted: RS Systems
texting ITS OWN REGISTERED USERS -- the shop owners and technicians who hold
accounts -- about their own account activity. Registrant brand == message brand,
consent is collected on a page they log in to, and the opt-in is not circular.
That is an ordinary ACCOUNT_NOTIFICATIONS registration.

Full reasoning: docs/operations/SMS_REGISTRATION.md, section 3.5.

TRAPS THIS SCRIPT DEFUSES (all four were paid for)
--------------------------------------------------
1. create_registration_version() opens an EMPTY draft -- it inherits nothing.
   Submitting straight after auto-denied version 2 in three seconds. We copy a
   base version wholesale, apply explicit overrides, and refuse to submit while
   any REQUIRED path is empty.
2. Copying a base version copies its mistakes. v3 inherited
   drake@rockstarwindshield.repair from the *approved Rockstar* registration.
   Every override below is deliberate, and the support email is asserted against
   the website.
3. Field values are locked while the newest version is denied
   (ConflictException EDIT_REGISTRATION_FIELD_VALUES_NOT_ALLOWED) -- open the new
   version first, which create_registration_version() does.
4. NEW for v5: the schema tightened after v4 was submitted. privacyPolicyUrl and
   termsAndConditionsUrl are now REQUIRED and v4 carries neither, so a plain
   copy-forward would hit trap 1 all over again. They are set explicitly below,
   and the REQUIRED sweep re-reads the live schema rather than a hardcoded list.

THE GUARD THAT WOULD HAVE CAUGHT v4
-----------------------------------
`assert_brand_consistency` refuses to submit unless every message sample leads
with the registrant's company name. v4 failed review on precisely this and no
script checked it.
"""
import argparse
import sys

import boto3

REG = 'registration-3c4aceac54424845b6d540e818f2bddb'
BASE_VERSION = 4          # newest; overrides below re-scope it from customer -> staff
COMPANY = 'RS Systems'
WEBSITE = 'rssystems.io'
SUPPORT_EMAIL = 'support@rssystems.io'

# No sample names any company but the registrant. A shop's or a fleet's name in a
# sample is what invites the reviewer to make the association that killed v4
# ("Message Use Case Mismatch" -- registrant one brand, samples another). The unit
# number carries the same meaning to a technician without naming a third party.
SAMPLES = [
    ("RS Systems: New repair request - Unit 4821, windshield chip. "
     "View: https://rssystems.io/tech/repairs/1042/ Reply STOP to opt out."),
    ("RS Systems: Job #1042 assigned to you - 2019 F-150, chip repair, due today. "
     "https://rssystems.io/tech/repairs/1042/ Reply STOP to opt out."),
    ("RS Systems: Your verification code is 123456. It expires in 10 minutes. "
     "Reply STOP to opt out."),
]

USE_CASE_DETAILS = (
    # Cap is 500 characters, not 1500 (that is optInDescription's). Keep headroom:
    # assert_lengths() below re-reads the live cap, but an over-long string aborts
    # after the version is already open.
    "RS Systems (rssystems.io) is job-management software for auto glass shops. This "
    "registration covers messages to our OWN registered users only - the shop owners "
    "and technicians who hold RS Systems accounts - about their own account activity: "
    "a new repair request, a job assigned to them, an approval or denial, and one-time "
    "verification codes. No message goes to a third party's customers. Users opt in "
    "in-app and verify their mobile number first. Low volume, transactional, no marketing."
)

OPT_IN_DESCRIPTION = (
    "Users opt in inside the RS Systems application, at Settings > Notifications, on a "
    "page they must log in to reach. The attached screenshot shows that screen.\n\n"
    "The consent checkbox, labelled \"Text me urgent job alerts\", is EMPTY AND "
    "UNCHECKED by default and is never pre-selected. The user must click it themselves "
    "and then save. The two checkboxes above it (in-app and email) are on by default, "
    "so the screenshot shows the contrast directly: ours is the unchecked one.\n\n"
    "The checkbox label reads: \"I agree to receive automated text messages from RS "
    "Systems at the mobile number on my account - new repair requests, job assignments "
    "and approvals. Message frequency varies with job activity, typically a few "
    "messages per working day. Consent is not a condition of using RS Systems.\"\n\n"
    "Directly below it: \"Msg & data rates may apply. Reply STOP to opt out, HELP for "
    "help,\" followed by links to our text program terms (https://rssystems.io/sms/), "
    "our privacy policy and our terms.\n\n"
    "Consent is stored with a timestamp against that user's own account record, and no "
    "text is sent until the user has also verified that mobile number with a code. The "
    "screenshot shows a demonstration account rather than a real user's record, so that "
    "no personal information is included in this submission."
)

OVERRIDES = {
    'messagingUseCase.useCaseCategory': {'SelectChoices': ['ACCOUNT_NOTIFICATIONS']},
    'messagingUseCase.useCaseDetails': {'TextValue': USE_CASE_DETAILS},
    'messagingUseCase.optInType': {'SelectChoices': ['DIGITAL_FORM']},
    'messagingUseCase.optInDescription': {'TextValue': OPT_IN_DESCRIPTION},
    'messagingUseCase.monthlyMessageVolume': {'SelectChoices': ['100']},
    'messagingUseCase.privacyPolicyUrl': {'TextValue': 'https://rssystems.io/privacy/'},
    'messagingUseCase.termsAndConditionsUrl': {'TextValue': 'https://rssystems.io/terms/'},
    'messageSamples.messageSample1': {'TextValue': SAMPLES[0]},
    'messageSamples.messageSample2': {'TextValue': SAMPLES[1]},
    'messageSamples.messageSample3': {'TextValue': SAMPLES[2]},
    'contactInfo.supportEmail': {'TextValue': SUPPORT_EMAIL},
}


def assert_brand_consistency(fields):
    """v4's denial, as an assertion.

    "Message Use Case Mismatch" meant: the registrant is one brand and the samples
    are another. Every sample must lead with the company name on the registration.
    """
    company = fields['companyInfo.companyName']['TextValue']
    for path in sorted(p for p in fields if p.startswith('messageSamples.')):
        sample = fields[path]['TextValue']
        if not sample.startswith(company):
            sys.exit(
                f"ABORT - {path} does not lead with the registrant brand "
                f"{company!r}. That is exactly what version 4 was denied for "
                f"(Message Use Case Mismatch).\n  {sample[:90]}..."
            )
    first = fields['messageSamples.messageSample1']['TextValue']
    if 'STOP' not in first:
        sys.exit('ABORT - messageSample1 carries no STOP instruction.')
    print(f'brand consistency OK - every sample leads with {company!r}, sample 1 has STOP')


def assert_support_email(fields):
    website = fields.get('companyInfo.website', {}).get('TextValue', '')
    email = fields['contactInfo.supportEmail']['TextValue']
    if website and not email.lower().endswith('@' + website.lower()):
        sys.exit(f'ABORT - supportEmail {email} does not match website {website}')
    print(f'support email OK - {email} matches {website}')


def assert_lengths(client, fields):
    """Text fields have caps; optInDescription's is 1500, not the ~500 folklore."""
    for d in client.describe_registration_field_definitions(
            RegistrationType='US_TOLL_FREE_REGISTRATION')['RegistrationFieldDefinitions']:
        rules = d.get('TextValidation') or {}
        cap = rules.get('MaxLength')
        value = fields.get(d['FieldPath'], {}).get('TextValue')
        if cap and value and len(value) > cap:
            sys.exit(f"ABORT - {d['FieldPath']} is {len(value)} chars, cap is {cap}")
    desc = fields['messagingUseCase.optInDescription']['TextValue']
    print(f'lengths OK - optInDescription {len(desc)} chars')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('screenshot', help='PNG from scripts/sms_optin_shot.py')
    parser.add_argument('--submit', action='store_true',
                        help='Actually open and submit a new version. Without it, '
                             'everything is validated and nothing is written.')
    args = parser.parse_args()

    client = boto3.client('pinpoint-sms-voice-v2', region_name='us-east-1')

    base = client.describe_registration_field_values(
        RegistrationId=REG, VersionNumber=BASE_VERSION)['RegistrationFieldValues']
    fields = {}
    for f in base:
        for key in ('TextValue', 'SelectChoices', 'RegistrationAttachmentId'):
            if f.get(key):
                fields[f['FieldPath']] = {key: f[key]}
    print(f'copied {len(fields)} fields from version {BASE_VERSION}')

    fields.update(OVERRIDES)
    print(f'applied {len(OVERRIDES)} deliberate overrides (customer scope -> staff scope)')

    if fields['companyInfo.companyName']['TextValue'] != COMPANY:
        sys.exit(f"ABORT - base companyName is "
                 f"{fields['companyInfo.companyName']['TextValue']!r}, expected {COMPANY!r}")

    assert_brand_consistency(fields)
    assert_support_email(fields)
    assert_lengths(client, fields)

    required = [d['FieldPath'] for d in client.describe_registration_field_definitions(
                    RegistrationType='US_TOLL_FREE_REGISTRATION')['RegistrationFieldDefinitions']
                if d['FieldRequirement'] == 'REQUIRED']
    missing = [p for p in required if p not in fields and p != 'messagingUseCase.optInImage']
    if missing:
        sys.exit(f'ABORT - required fields empty: {missing}')
    print(f'all {len(required)} required fields present')

    if not args.submit:
        print('\n--- DRY RUN (no version opened, nothing written) ---')
        for path in sorted(OVERRIDES):
            value = OVERRIDES[path].get('TextValue') or OVERRIDES[path].get('SelectChoices')
            shown = value if isinstance(value, list) else str(value)
            print(f'\n{path}:\n  {shown if isinstance(shown, list) else shown[:300]}'
                  f"{'...' if isinstance(shown, str) and len(shown) > 300 else ''}")
        print(f'\nScreenshot to upload: {args.screenshot}')
        print('\nRe-run with --submit to file it.')
        return

    attachment = client.create_registration_attachment(
        AttachmentBody=open(args.screenshot, 'rb').read())['RegistrationAttachmentId']
    print(f'screenshot uploaded: {attachment}')
    fields['messagingUseCase.optInImage'] = {'RegistrationAttachmentId': attachment}

    version = client.create_registration_version(RegistrationId=REG)['VersionNumber']
    print(f'draft version {version} opened; writing {len(fields)} fields')
    for path, kwargs in sorted(fields.items()):
        client.put_registration_field_value(RegistrationId=REG, FieldPath=path, **kwargs)

    client.submit_registration_version(RegistrationId=REG)
    for v in client.describe_registration_versions(
            RegistrationId=REG)['RegistrationVersions']:
        reasons = '; '.join(r['Reason'] for r in v.get('DeniedReasons', []))
        print(f"  version {v['VersionNumber']}: {v['RegistrationVersionStatus']}"
              f"{' - ' + reasons if reasons else ''}")


if __name__ == '__main__':
    main()
