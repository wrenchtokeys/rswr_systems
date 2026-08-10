"""
Regression tests for .ebextensions cron configuration.

These guard three silent production outages discovered 2026-08-10, all of
which deployed cleanly and reported healthy while doing nothing at all:

1. `11_billing_cron.config` had two top-level `files:` keys. YAML is
   last-wins, so the cron table was discarded at parse time and
   /etc/cron.d/rs-systems-billing was never written. check_subscription_alerts,
   process_overdue_invoices, process_batch_invoices, generate_aging_report,
   expire_loyalty_points and reconcile_loyalty_balances had never run.

2. Every cron entry redirected to a bare /var/log/<name>.log. /var/log is
   root-owned and these jobs run as `webapp`; bash applies redirections
   BEFORE exec'ing the command, so each tick died with "Permission denied"
   and the management command never started. This silently disabled
   send_review_requests and reconcile_stripe_payments too -- the latter
   being the safety net for lost Stripe webhooks.

3. EB's `files:` directive leaves a `.bak` when overwriting, and cron reads
   every entry in /etc/cron.d, so each job was registered twice.

PyYAML is not a declared dependency (it arrives transitively), so these skip
rather than fail where it is absent.
"""

import glob
import os
import re
import unittest

from django.test import SimpleTestCase

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

EBEXTENSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.ebextensions'
)

# Where webapp-owned cron jobs are allowed to write. /var/log itself is
# root-owned and drwxr-xr-x; 11_billing_cron.config creates this one and
# chowns it to webapp.
WRITABLE_LOG_DIR = '/var/log/rs-systems/'

REDIRECT_RE = re.compile(r'>>\s*(/var/log/\S+)')


def _config_paths():
    return sorted(glob.glob(os.path.join(EBEXTENSIONS_DIR, '*.config')))


class _DuplicateKeyLoader(yaml.SafeLoader if yaml else object):
    """SafeLoader that raises instead of silently letting the last key win."""


def _no_duplicate_keys(loader, node, deep=False):
    seen = set()
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen.add(key)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


if yaml is not None:
    _DuplicateKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
    )


@unittest.skipIf(yaml is None, "PyYAML not installed")
class EbextensionsYamlTests(SimpleTestCase):
    """Every .ebextensions file must parse, with no duplicate keys anywhere."""

    def test_all_configs_parse_without_duplicate_keys(self):
        for path in _config_paths():
            with self.subTest(config=os.path.basename(path)):
                with open(path) as fh:
                    try:
                        yaml.load(fh, Loader=_DuplicateKeyLoader)
                    except ValueError as exc:
                        self.fail(
                            f"{os.path.basename(path)}: {exc}. YAML is last-wins, "
                            f"so a duplicate top-level key silently discards a "
                            f"whole section -- this is how the billing cron table "
                            f"went missing. Merge the sections instead."
                        )

    def test_configs_are_non_empty_mappings(self):
        """A config that parses to None is a no-op that still deploys green."""
        for path in _config_paths():
            name = os.path.basename(path)
            if name == '02_packages.config':
                continue  # intentionally empty
            with self.subTest(config=name):
                with open(path) as fh:
                    doc = yaml.load(fh, Loader=_DuplicateKeyLoader)
                self.assertIsInstance(doc, dict, f"{name} did not parse to a mapping")
                self.assertTrue(doc, f"{name} parsed to an empty mapping")


class CronLogPathTests(SimpleTestCase):
    """Cron jobs run as `webapp` and cannot create files in /var/log."""

    def test_no_cron_job_redirects_to_unwritable_log_path(self):
        offenders = []
        for path in _config_paths():
            with open(path) as fh:
                content = fh.read()
            for match in REDIRECT_RE.finditer(content):
                target = match.group(1)
                if not target.startswith(WRITABLE_LOG_DIR):
                    offenders.append(f"{os.path.basename(path)} -> {target}")
        self.assertEqual(
            offenders, [],
            "Cron jobs run as `webapp`, which cannot create files in root-owned "
            "/var/log. Bash performs the redirect before exec'ing, so the command "
            f"never runs at all. Write to {WRITABLE_LOG_DIR} instead. Offenders: "
            + ", ".join(offenders)
        )


@unittest.skipIf(yaml is None, "PyYAML not installed")
class CronInstallationTests(SimpleTestCase):
    """Cron tables must actually reach /etc/cron.d, exactly once."""

    CRON_CONFIGS = {
        '11_billing_cron.config': 'rs-systems-billing',
        '12_reviews_cron.config': 'rs-systems-reviews',
        '13_stripe_reconcile_cron.config': 'rs-systems-stripe-reconcile',
    }

    def _load(self, name):
        with open(os.path.join(EBEXTENSIONS_DIR, name)) as fh:
            return yaml.load(fh, Loader=_DuplicateKeyLoader)

    def test_each_cron_table_is_staged_and_installed_leader_only(self):
        for name, cron_name in self.CRON_CONFIGS.items():
            with self.subTest(config=name):
                doc = self._load(name)
                staged = f"/opt/rs-systems/cron/{cron_name}"
                self.assertIn(
                    staged, doc.get('files', {}),
                    f"{name} must stage its cron table at {staged}",
                )
                commands = doc.get('container_commands', {})
                self.assertTrue(commands, f"{name} has no container_commands")
                installer = next(
                    (c for c in commands.values() if cron_name in c.get('command', '')),
                    None,
                )
                self.assertIsNotNone(
                    installer, f"{name} never installs {cron_name} into /etc/cron.d"
                )
                self.assertTrue(
                    installer.get('leader_only'),
                    f"{name}: installing {cron_name} on every instance means a "
                    f"scaled-out environment runs each job once per instance. "
                    f"process_batch_invoices would double-invoice customers.",
                )

    def test_installers_purge_stale_bak_files(self):
        """EB leaves a .bak on overwrite and cron runs it as a second entry."""
        for name in self.CRON_CONFIGS:
            with self.subTest(config=name):
                doc = self._load(name)
                commands = doc.get('container_commands', {})
                self.assertTrue(
                    any('/etc/cron.d/*.bak' in c.get('command', '')
                        for c in commands.values()),
                    f"{name} must rm -f /etc/cron.d/*.bak after installing, or "
                    f"every job runs twice per tick.",
                )

    def test_billing_cron_creates_writable_log_dir(self):
        doc = self._load('11_billing_cron.config')
        commands = doc.get('commands', {})
        self.assertTrue(
            any(WRITABLE_LOG_DIR.rstrip('/') in c.get('command', '')
                and 'chown' in c.get('command', '')
                for c in commands.values()),
            f"11_billing_cron.config must mkdir + chown {WRITABLE_LOG_DIR} to "
            f"webapp, or every cron redirect fails with Permission denied.",
        )

    def test_bundlelogs_reference_the_real_log_paths(self):
        """`eb logs` must point at where the jobs actually write."""
        for name in self.CRON_CONFIGS:
            with self.subTest(config=name):
                doc = self._load(name)
                bundles = {
                    path: spec for path, spec in doc.get('files', {}).items()
                    if 'bundlelogs.d' in path
                }
                self.assertTrue(bundles, f"{name} declares no bundlelogs config")
                for path, spec in bundles.items():
                    for line in spec.get('content', '').splitlines():
                        line = line.strip()
                        if line:
                            self.assertTrue(
                                line.startswith(WRITABLE_LOG_DIR),
                                f"{name}: bundlelogs entry {line} does not match "
                                f"the actual cron log directory",
                            )
