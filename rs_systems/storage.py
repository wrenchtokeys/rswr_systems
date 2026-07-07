"""Static files storage for production."""

from whitenoise.storage import CompressedManifestStaticFilesStorage


class ForgivingManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """Manifest storage that degrades instead of raising on a missing entry.

    With the default strict manifest, a single missing entry turns every page
    that references that asset into a 500 (July 2026 /tech/repairs/create/
    incident). Non-strict mode falls back to hashing the file on disk, so a
    stale manifest costs at worst a slower lookup or an unhashed URL — never
    a server error for an otherwise healthy page.
    """

    manifest_strict = False
