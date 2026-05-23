from django import template

register = template.Library()

@register.filter
def sub(value, arg):
    """Subtract the arg from the value."""
    try:
        return int(value) - int(arg)
    except (ValueError, TypeError):
        try:
            return value - arg
        except Exception:
            return 0


@register.filter
def is_physical_reward(option):
    """Return True if the reward option is a physical (non-monetary) reward."""
    reward_type = getattr(option, 'reward_type', None)
    if reward_type is None:
        return False
    return reward_type.category in ('MERCHANDISE', 'OTHER', 'GIFT_CARD')