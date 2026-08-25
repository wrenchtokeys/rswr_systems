"""Toll-free registration resubmit for +18663115189.

create_registration_version() opens an EMPTY draft — it does not inherit the
previous version's field values. Every required field has to be re-put or the
submission is auto-denied "Missing required field" within seconds (that is
what happened to version 2). This copies version 1 wholesale, overrides the
opt-in description + screenshot, then submits.
"""
import sys, boto3

REG = 'registration-3c4aceac54424845b6d540e818f2bddb'
SHOT = sys.argv[1]
DESC = open(sys.argv[2]).read().strip()

c = boto3.client('pinpoint-sms-voice-v2', region_name='us-east-1')

att = c.create_registration_attachment(AttachmentBody=open(SHOT, 'rb').read())['RegistrationAttachmentId']
print(f'screenshot uploaded: {att}')

base = c.describe_registration_field_values(RegistrationId=REG, VersionNumber=1)['RegistrationFieldValues']
fields = {}
for f in base:
    for key in ('TextValue', 'SelectChoices', 'RegistrationAttachmentId'):
        if f.get(key):
            fields[f['FieldPath']] = {key: f[key]}
fields['messagingUseCase.optInDescription'] = {'TextValue': DESC}
fields['messagingUseCase.optInImage'] = {'RegistrationAttachmentId': att}

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
