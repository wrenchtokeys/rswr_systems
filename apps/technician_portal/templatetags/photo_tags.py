"""
Photo URLs for templates — the route, never the storage URL (P8).

`{{ repair.damage_photo_before.url }}` was the S3 address of a customer's
damage photo, readable by anyone who guessed it. These tags give a template
the app route for the surface it is rendering on, gated like everything
else on that surface. Load with {% load photo_tags %} — after
{% extends %}, at the top of an include.

    {% shop_photo_url repair 'damage_photo_before' as before_url %}
    {% customer_photo_url replacement 'damage_photo_after' %}
    {% crop_thumb_url crop %}

Each returns '' when the job has no such photo, so a guarded block renders
nothing rather than a broken image. The public invoice page has no tag: its
URLs carry the invoice token and are built in `rs_systems.views`.
"""
from django import template

from apps.technician_portal.services import photo_serving

register = template.Library()


@register.simple_tag
def shop_photo_url(job, field_name):
    """The shop-side route for one of a job's photos."""
    return photo_serving.shop_photo_url(job, field_name)


@register.simple_tag
def customer_photo_url(job, field_name):
    """The customer-portal route for one of a job's photos."""
    return photo_serving.customer_photo_url(job, field_name)


@register.simple_tag
def crop_thumb_url(crop):
    """The shop-side route for a crop's saved close-up."""
    return photo_serving.shop_crop_url(crop)
