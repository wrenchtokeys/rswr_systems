"""
Mygrant Glass SOAP web-service client.

Spec: docs/reference/mygrant-soap-webservices-spec-rev-2025-05.pdf (rev
2025-05-05). One operation — InboundTraffic — string-in/string-out: the SOAP
body carries a CDATA-wrapped MygrantXMLOrderingSystemRequest document, and the
response wraps the same document back with <Response> elements added. The
envelope is small enough that a SOAP library would be more code than this.

Auth is two-layer: the API key goes in an AuthToken HTTP header, and the
shop's CustomerID/WebUserID/Password ride inside the request document.
The API is the only sanctioned route to Mygrant (their site ToS prohibits
scraping) and API data must never be shown outside the shop — in particular
CustomerUnitPrice stays off every customer-facing surface.

This module is quote-plumbing only for now: build/send an Inquiry and parse
the result. Orders come in a later P1 phase; Returns aren't in the API yet.
"""
import logging
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import requests

logger = logging.getLogger(__name__)

PRODUCTION_URL = 'https://webservice.mygrantglass.com/v2/CoRE650WebService.asmx'
STAGING_URL = 'https://webservice-staging.mygrantglass.com/v2/CoRE650WebService.asmx'
SOAP_ACTION = 'http://tempuri.org/InboundTraffic'
TIMEOUT_SECONDS = 20

# Known-good NAGS part from the spec's own sample (07-14 Chevy Silverado
# windshield) — used for the connection test Inquiry.
TEST_NAGS_PREFIX = 'DW'
TEST_NAGS_NUMBER = '01658'

# Request-level status codes (spec §6.1)
STATUS_SUCCESS = '0'
STATUS_NOT_AUTHENTICATED = 'E600'


class MygrantError(Exception):
    """Base error for Mygrant calls. str(exc) is safe to show a shop owner."""


class MygrantAuthError(MygrantError):
    """Mygrant rejected the credentials or API key."""


class MygrantUnavailableError(MygrantError):
    """Network failure, timeout, or a malformed/unexpected response."""


def _build_inquiry_document(config, nags_prefix, nags_number, quantity=1,
                            environment='PROD'):
    """The inner MygrantXMLOrderingSystemRequest document for a NAGS Inquiry."""
    return (
        '<MygrantXMLOrderingSystemRequest>'
        '<RequestHeader>'
        f'<EnvironmentID>{escape(environment)}</EnvironmentID>'
        f'<CustomerID>{escape(config.customer_id)}</CustomerID>'
        f'<WebUserID>{escape(config.web_user_id)}</WebUserID>'
        f'<Password>{escape(config.password)}</Password>'
        '<RequestType>Inquiry</RequestType>'
        '<VersionNumber>1.0</VersionNumber>'
        '</RequestHeader>'
        '<RequestSet>'
        '<RequestItem>'
        '<RequestItemNo>1</RequestItemNo>'
        '<RequestDetail>'
        f'<RequestNAGSPrefix>{escape(nags_prefix)}</RequestNAGSPrefix>'
        f'<RequestNAGSNumber>{escape(nags_number)}</RequestNAGSNumber>'
        f'<RequestQuantity>{int(quantity)}</RequestQuantity>'
        '</RequestDetail>'
        '</RequestItem>'
        '</RequestSet>'
        '</MygrantXMLOrderingSystemRequest>'
    )


def _wrap_soap(inner_document):
    # CDATA carries the inner document verbatim; the credentials are already
    # XML-escaped for the inner document, and CDATA has no ]]> risk because
    # escape() never emits ']]>' and the fields it interpolates are escaped.
    return (
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:tem="http://tempuri.org/">'
        '<soap:Header/>'
        '<soap:Body>'
        '<tem:InboundTraffic>'
        f'<tem:request><![CDATA[{inner_document}]]></tem:request>'
        '</tem:InboundTraffic>'
        '</soap:Body>'
        '</soap:Envelope>'
    )


def _post(config, inner_document, url):
    envelope = _wrap_soap(inner_document)
    headers = {
        'Content-Type': 'text/xml;charset=UTF-8',
        'SOAPAction': f'"{SOAP_ACTION}"',
        'AuthToken': config.api_key,
    }
    try:
        response = requests.post(
            url, data=envelope.encode('utf-8'), headers=headers,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("Mygrant request failed (tenant=%s): %s", config.tenant_id, exc)
        raise MygrantUnavailableError(
            "Could not reach Mygrant — check your connection and try again."
        ) from exc
    if response.status_code in (401, 403):
        raise MygrantAuthError(
            "Mygrant rejected the API key. Check the key, or generate a new "
            "one at MygrantGlass.com → My Account → Edit User Settings."
        )
    if response.status_code != 200:
        logger.warning(
            "Mygrant HTTP %s (tenant=%s): %s",
            response.status_code, config.tenant_id, response.text[:500],
        )
        raise MygrantUnavailableError(
            f"Mygrant returned an unexpected error (HTTP {response.status_code}). "
            "Try again in a few minutes."
        )
    return _parse_result_document(response.text)


def _parse_result_document(soap_text):
    """Pull the CDATA result document out of the SOAP response and parse it."""
    try:
        envelope = ElementTree.fromstring(soap_text)
        result_el = envelope.find('.//{http://tempuri.org/}InboundTrafficResult')
        if result_el is None or not (result_el.text or '').strip():
            raise MygrantUnavailableError(
                "Mygrant returned an empty response. Try again in a few minutes."
            )
        return ElementTree.fromstring(result_el.text.strip())
    except ElementTree.ParseError as exc:
        logger.warning("Unparseable Mygrant response: %s", soap_text[:500])
        raise MygrantUnavailableError(
            "Mygrant returned a response we couldn't read. Try again in a few minutes."
        ) from exc


def _status(document):
    code = (document.findtext('RequestStatusCode') or '').strip()
    text = (document.findtext('RequestStatusText') or '').strip()
    return code, text


def test_connection(config):
    """
    One staging Inquiry (EnvironmentID=TEST) for a known NAGS part, to prove
    the credentials and API key work. Never hits production, never orders.

    Returns the human-readable success detail; raises MygrantError otherwise.
    Callers own persisting the outcome (mark_verified/mark_verify_failed).
    """
    if not config.has_credentials:
        raise MygrantError("Enter your Customer ID, web user ID and password first.")
    if not config.api_key:
        raise MygrantError(
            "An API key is required. Generate one at MygrantGlass.com → "
            "My Account → Edit User Settings (available once Mygrant completes "
            "API onboarding for the account)."
        )
    inner = _build_inquiry_document(
        config, TEST_NAGS_PREFIX, TEST_NAGS_NUMBER, environment='TEST',
    )
    document = _post(config, inner, STAGING_URL)
    code, text = _status(document)
    if code == STATUS_SUCCESS:
        return "Connected — Mygrant accepted the credentials."
    if code == STATUS_NOT_AUTHENTICATED or text in ('NotAuthenticated', 'NotAuthorized'):
        raise MygrantAuthError(
            "Mygrant rejected the login. Check the Customer ID, web user ID "
            "and password — they're usually the MygrantGlass.com login."
        )
    # Unknown-but-answered: the account reached Mygrant, but the test part
    # lookup failed. Surface Mygrant's own words rather than guessing.
    raise MygrantError(f"Mygrant answered with: {text or code or 'an unknown status'}.")
