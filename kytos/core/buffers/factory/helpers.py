"""Helpers for factory functions"""
from functools import reduce


def process_gen_identifiers(identifiers: list[str]):
    """
    Generate a func for getting a tuple of hashable parameters from an event
    """
    split_identifiers = [
        identifier.split('.')
        for identifier in identifiers
    ]
    return lambda event: (
        reduce(
            lambda ev, attr: getattr(
                ev,
                attr,
                'unknown',
            ),
            identifier,
            event
        )
        for identifier in split_identifiers
    )


def process_conditional(config):
    """Create condition for event."""
    return config
