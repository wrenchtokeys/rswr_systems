"""Static files storage for production."""

from whitenoise.storage import CompressedManifestStaticFilesStorage


class ForgivingManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """Manifest storage that degrades instead of raising on a missing entry.

    With the default strict manifest, a single missing entry turns every page
    that references that asset into a 500 (July 2026 /tech/repairs/create/
    incident). Non-strict mode falls back to hashing the file on disk, so a
    stale manifest costs at worst a slower lookup or an unhashed URL — never
    a server error for an otherwise healthy page.

    Non-strict mode has its own trap: on a manifest miss Django hashes the
    original file and emits that hashed URL even though the hashed *file* was
    never written, so every asset 404s (July 2026 broken-admin incident — a
    config deploy replaced STATIC_ROOT without running collectstatic). Only
    return a name that differs from the requested one if that file actually
    exists; otherwise serve the original, which does.
    """

    manifest_strict = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._existing_stored_names = set()

    def stored_name(self, name):
        try:
            stored = super().stored_name(name)
        except ValueError:
            return name
        if stored == name or stored in self._existing_stored_names:
            return stored
        if self.exists(stored):
            self._existing_stored_names.add(stored)
            return stored
        return name
