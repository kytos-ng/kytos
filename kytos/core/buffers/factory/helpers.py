"""Helpers for factory functions"""
import re
from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import Any, Callable, Generic, TypeVar, Union

from kytos.core.events import KytosEvent

T = TypeVar('T')
U = TypeVar('U')
V = TypeVar('V')


class ExtractDirective(Enum):
    """Directives for the chain extractor"""
    FROM_DICT = 'dict'
    FROM_ATTR = 'attr'


@dataclass
class ChainExtractor:
    """
    Callable for extracting a value through a series of getattrs
    and key lookups.
    """
    directives: tuple[tuple[ExtractDirective, str], ...]
    default_val: Any

    def __call__(self, item):
        try:
            result = item
            for directive, key in self.directives:
                if directive == ExtractDirective.FROM_DICT:
                    result = result[key]
                elif directive == ExtractDirective.FROM_ATTR:
                    result = getattr(result, key)
                else:
                    return self.default_val
            return result
        except KeyError:
            return self.default_val
        except AttributeError:
            return self.default_val

@dataclass
class IdentifierGenerator:
    """
    Callable for getting a tuple of values from a given KytosEvent
    """
    extractors: tuple[Callable[[KytosEvent], Any], ...]

    def __call__(self, event: KytosEvent):
        return (
            extractor(event) for extractor in self.extractors
        )


TOKEN_SPEC = (
    ('WORD',            r'\w+'),
    ('BRACKET_START',   r'\['),
    ('BRACKET_END',     r'\]'),
    ('NEXT_ATTR',       r'\.'),
    ('MISMATCH',        '.'),
)


TOKEN_REGEX = re.compile(
    '|'.join(f'(?P<{kind}>{value})' for kind, value in TOKEN_SPEC)
)


def tokens_to_directives_iter(tokens: list[tuple[str, str]]):
    """Generate a series of directives for the ChainExtractor"""
    position = 0
    try:
        while position < len(tokens):
            curr_kind, _, _, _ = tokens[position]
            if curr_kind in {'NEXT_ATTR', 'START'}:
                next_kind, next_value, _, _ = tokens[position + 1]
                if next_kind == 'WORD':
                    yield (ExtractDirective.FROM_ATTR, next_value)
                    position += 2
                    continue
            if curr_kind == 'BRACKET_START':
                next_kind, next_value, _, _ = tokens[position + 1]
                further_kind, _, _, _ = tokens[position + 2]
                if next_kind == 'WORD' and further_kind == 'BRACKET_END':
                    yield (ExtractDirective.FROM_DICT, next_value)
                    position += 3
                    continue
            if curr_kind == 'START':
                next_kind, next_value, _, _ = tokens[position + 1]
                if next_kind == 'BRACKET_START':
                    position += 1
                    continue
            raise ValueError(
                f'Unexpected token while parsing. '
                f'Remaining tokens are {tokens[position:]}'
            )
    except IndexError as exc:
        raise ValueError(
            f'Expected more tokens to process than available. '
            f'Remaining tokens are {tokens[position:]}'
        ) from exc


def process_value_extractor(config: str):
    """Evaluate a string into a ChainExtractor"""

    tokens = [
        ('START', '', None, config),
        *(
            (mo.lastgroup, mo.group(), mo.start(), config)
            for mo in TOKEN_REGEX.finditer(config)
        )
    ]

    return ChainExtractor(
        tuple(tokens_to_directives_iter(tokens)),
        'unknown'
    )


@dataclass
class AndCondition(Generic[T]):
    """
    Callable which checks if all conditions
    are true for a given value
    """

    conditions: tuple[Callable[[T], bool], ...]

    def __call__(self, value: T):
        return all(
            map(
                lambda condition: condition(value),
                self.conditions
            )
        )


@dataclass
class OrCondition(Generic[T]):
    """
    Callable which checks if any condition
    is true for a given value
    """

    conditions: list[Callable[[T], bool]]

    def __call__(self, value: T):
        return any(
            map(
                lambda condition: condition(value),
                self.conditions
            )
        )


@dataclass
class NotCondition(Generic[T]):
    """
    Callable which checks if a condition is not true
    for a given value
    """

    condition: Callable[[T], bool]

    def __call__(self, value: T):
        return not self.condition(value)


@dataclass
class MatchRegex:
    """
    Callable which checks if the regex matches the
    given string
    """

    pattern: re.Pattern

    def __call__(self, item: str) -> bool:
        return self.pattern.match(item)


@dataclass
class InSet(Generic[T]):
    """
    Callable which checks if the set contains
    the given value
    """

    items: frozenset[T]

    def __call__(self, item: T):
        return item in self.items


@dataclass
class ExtractTest(Generic[T, U]):
    """
    Callable which extracts a value from the given item
    then performs a test upon it
    """
    value_extractor: Callable[[T], U]
    test: Callable[[U], bool]

    def __call__(self, event: T) -> bool:
        return self.test(
            self.value_extractor(event)
        )


def process_extract_test(config: dict):
    """
    Convert config into ExtractTest
    """
    args = {}
    args['value_extractor'] = process_value_extractor(
        config['value_extractor']
    )
    args['test'] = process_conditional(
        config['test']
    )

    return ExtractTest(**args)


def and_or_processor(cls: type, config: dict):
    """
    Convert config into and/or Condition
    """
    args = {}
    args['conditions'] = (
        process_conditional(condition_config)
        for condition_config in config['conditions']
    )
    return cls(**args)


def process_not(config: dict):
    """
    Convert config into NotCondition
    """
    args = {}
    args['condition'] = process_conditional(
        config['condition']
    )
    return NotCondition(**args)


def process_regex(config: dict):
    """
    Convert config into MatchRegex
    """
    args = {}

    args['pattern'] = re.compile(
        config['pattern']
    )
    return MatchRegex(**args)


def process_in_set(config: dict):
    """
    Convert config into InSet
    """

    args = {}

    args['items'] = frozenset(
        config['items']
    )

    return InSet(**args)


tests = {
    'and': partial(and_or_processor, AndCondition),
    'or': partial(and_or_processor, OrCondition),
    'not': process_not,
    'transform': process_extract_test,
    'regex': process_regex,
    'in_set': process_in_set,
}


def process_conditional(
    config: dict
) -> Callable[[KytosEvent], bool]:
    """Create conditional for event."""
    return tests[config['type']](config)


def process_gen_identifiers(
    identifiers: list[str]
) -> Callable[[KytosEvent], tuple]:
    """
    Generate a func for getting a tuple of hashable parameters from an event
    """
    attr_extractors = (
        process_value_extractor(identifier)
        for identifier in identifiers
    )

    return IdentifierGenerator(attr_extractors)
