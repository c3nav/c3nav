from django import template

register = template.Library()


@register.filter
def negate(value):
    return -value


@register.filter
def subtract(value, arg):
    return value - arg
