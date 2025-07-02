"""Methods for list of ranges [inclusive, inclusive]"""
# pylint: disable=too-many-branches
import bisect
from itertools import chain
from typing import Optional, Union

from kytos.core.exceptions import KytosInvalidTagRanges


def get_special_tags(tag_range: list[str], default) -> list[str]:
    """Get special_tags and check values"""
    # Find duplicated
    if len(tag_range) != len(set(tag_range)):
        msg = "There are duplicated values in the range."
        raise KytosInvalidTagRanges(msg)

    # Find invalid tag
    default_set = set(default)
    for tag in tag_range:
        try:
            default_set.remove(tag)
        except KeyError:
            msg = f"The tag {tag} is not supported"
            raise KytosInvalidTagRanges(msg)
    return tag_range


def map_singular_values(tag_range: Union[int, list[int]]):
    """Change integer or singular interger list to
    list[int, int] when necessary"""
    if isinstance(tag_range, int):
        tag_range = [tag_range] * 2
    elif len(tag_range) == 1:
        tag_range = [tag_range[0]] * 2
    return tag_range


def get_tag_ranges(ranges: list[list[int]]):
    """Get tag_ranges and check validity:
    - It should be ordered
    - Not unnecessary partition (eg. [[10,20],[20,30]])
    - Singular intergers are changed to ranges (eg. [10] to [[10, 10]])

    The ranges are understood as [inclusive, inclusive]"""
    if len(ranges) < 1:
        msg = "Tag range is empty"
        raise KytosInvalidTagRanges(msg)
    last_tag = 0
    ranges_n = len(ranges)
    for i in range(0, ranges_n):
        ranges[i] = map_singular_values(ranges[i])
        if ranges[i][0] > ranges[i][1]:
            msg = f"The range {ranges[i]} is not ordered"
            raise KytosInvalidTagRanges(msg)
        if last_tag and last_tag > ranges[i][0]:
            msg = f"Tag ranges are not ordered. {last_tag}"\
                     f" is higher than {ranges[i][0]}"
            raise KytosInvalidTagRanges(msg)
        if last_tag and last_tag == ranges[i][0] - 1:
            msg = f"Tag ranges have an unnecessary partition. "\
                     f"{last_tag} is before to {ranges[i][0]}"
            raise KytosInvalidTagRanges(msg)
        if last_tag and last_tag == ranges[i][0]:
            msg = f"Tag ranges have repetition. {ranges[i-1]}"\
                     f" have same values as {ranges[i]}"
            raise KytosInvalidTagRanges(msg)
        last_tag = ranges[i][1]
    if ranges[-1][1] > 4095:
        msg = "Maximum value for a tag is 4095"
        raise KytosInvalidTagRanges(msg)
    if ranges[0][0] < 1:
        msg = "Minimum value for a tag is 1"
        raise KytosInvalidTagRanges(msg)
    return ranges


def get_validated_tags(
    tags: Union[list[int], list[list[int]]]
) -> Union[list[int], list[list[int]]]:
    """Return tags which values are validated to be correct."""
    if isinstance(tags, list) and isinstance(tags[0], int):
        if len(tags) == 1:
            return [tags[0], tags[0]]
        if len(tags) == 2 and tags[0] > tags[1]:
            raise KytosInvalidTagRanges(f"Range out of order {tags}")
        if len(tags) > 2:
            raise KytosInvalidTagRanges(f"Range must have 2 values {tags}")
        return tags
    if isinstance(tags, list) and isinstance(tags[0], list):
        return get_tag_ranges(tags)
    raise KytosInvalidTagRanges(f"Value type not recognized {tags}")


def range_intersection(
    ranges_a: list[list[int]],
    ranges_b: list[list[int]],
) -> list[list[int]]:
    """Returns a list of ranges of an intersection between
    two validated list of ranges.

    Necessities:
        The lists from argument need to be ordered and validated.
        E.g. [[1, 2], [4, 60]]
        Use get_tag_ranges() for list[list[int]] or
            get_validated_tags() for also list[int]
    """
    if not ranges_a:
        return []
    if not ranges_b:
        return []

    a_bounds = (ranges_a[0][0], ranges_b[-1][1])
    b_bounds = (ranges_b[0][0], ranges_b[-1][1])

    true_bounds = max(a_bounds[0], b_bounds[0]), min(a_bounds[1], b_bounds[1])

    # Could optimize the process to only require at most 2 cuts,
    # rather than the 4 currently done.
    _, bounded_a, _ = partition_by_relevant_bounds(
        ranges_a, *true_bounds
    )

    _, bounded_b, _ = partition_by_relevant_bounds(
        ranges_b, *true_bounds
    )

    ordered_ranges = sorted(chain(
        bounded_a,
        bounded_b
    ))

    intersections = list[list[int]]()

    top = ordered_ranges[0]

    for tag_range in ordered_ranges[1:]:
        match top, tag_range:
            case [a_start, a_end], [b_start, b_end] if (
                b_start <= a_end and a_end <= b_end
            ):
                top = [a_start, b_end]
                intersections.append([b_start, a_end])
            case [a_start, a_end], [b_start, b_end] if (
                b_end < a_end
            ):
                intersections.append([b_start, b_end])
            case _, _:
                top = tag_range

    return intersections

def range_difference(
    ranges_a: list[list[int]],
    ranges_b: list[list[int]]
) -> list[list[int]]:
    """The operation is two validated list of ranges
     (ranges_a - ranges_b).
    This method simulates difference of sets.

    Necessities:
        The lists from argument need to be ordered and validated.
        E.g. [[1, 2], [4, 60]]
        Use get_tag_ranges() for list[list[int]] or
            get_validated_tags() for also list[int]
    """
    if not ranges_a:
        return ranges_a
    if not ranges_b:
        return ranges_a

    a_bounds = (ranges_a[0][0], ranges_b[-1][1])
    b_bounds = (ranges_b[0][0], ranges_b[-1][1])

    true_bounds = max(a_bounds[0], b_bounds[0]), min(a_bounds[1], b_bounds[1])

    unaffected_left, bounded_a, unaffected_right = partition_by_relevant_bounds(
        ranges_a, *true_bounds
    )

    _, bounded_b, _ = partition_by_relevant_bounds(
        ranges_b, *true_bounds
    )

    ordered_ranges = sorted(chain(
        [[*range_a, False] for range_a in bounded_a],
        [[*range_b, True] for range_b in bounded_b]
    ))

    merged_ranges = list[list[int]]()

    top = ordered_ranges[0]

    for tag_range in ordered_ranges[1:]:
        # implied a_start <= b_start
        match top, tag_range:
            case [a_start, a_end, subtract_a], [b_start, b_end, subtract_b] if (
                subtract_a and subtract_b
            ):
                top = tag_range
            # subtract_a implies not substract_b
            # subtract_b implies not subtract_a
            case [a_start, a_end, subtract_a], [b_start, b_end, subtract_b] if (
                subtract_a and b_end <= a_end
            ):
                pass
            case [a_start, a_end, subtract_a], [b_start, b_end, subtract_b] if (
                subtract_a and b_start <= a_end
            ):
                top = [a_end + 1, b_end, False]
            case [a_start, a_end, subtract_a], [b_start, b_end, subtract_b] if (
                subtract_b and a_start == b_start and a_end <= b_end
            ):
                top = tag_range
            case [a_start, a_end, subtract_a], [b_start, b_end, subtract_b] if (
                subtract_b and a_start == b_start
            ):
                top = [b_end + 1, a_end, False]
            case [a_start, a_end, subtract_a], [b_start, b_end, subtract_b] if (
                subtract_b and b_end < a_end
            ):
                merged_ranges.append([a_start, b_start - 1])
                top = [b_end + 1, a_end, False]
            case [a_start, a_end, subtract_a], [b_start, b_end, subtract_b] if (
                subtract_b and b_start <= a_end
            ):
                merged_ranges.append([a_start, b_start - 1])
                top = tag_range
            case [a_start, a_end, subtract_a], [b_start, b_end, subtract_b] if (
                not subtract_a
            ):
                merged_ranges.append([top[0], top[1]])
                top = tag_range
            case _, _:
                top = tag_range

    if not top[2]:
        merged_ranges.append([top[0], top[1]])

    return [*unaffected_left, *merged_ranges, *unaffected_right]


def range_addition(
    ranges_a: list[list[int]],
    ranges_b: list[list[int]]
) -> tuple[list[list[int]], list[list[int]]]:
    """Addition between two validated list of ranges.
     Simulates the addition between two sets.
     Return[adittion product, intersection]

     Necessities:
        The lists from argument need to be ordered and validated.
        E.g. [[1, 2], [4, 60]]
        Use get_tag_ranges() for list[list[int]] or
            get_validated_tags() for also list[int]
     """
    if not ranges_a:
        return ranges_b, []
    if not ranges_b:
        return ranges_a, []

    a_bounds = (ranges_a[0][0], ranges_b[-1][1])
    b_bounds = (ranges_b[0][0], ranges_b[-1][1])

    # Slightly adjusted to incorporate merges along boundaries e.g. [[1,2]] + [[3,4]]
    true_bounds = max(a_bounds[0], b_bounds[0]) - 1, min(a_bounds[1], b_bounds[1]) + 1

    unaffected_left_a, bounded_a, unaffected_right_a = partition_by_relevant_bounds(
        ranges_a, *true_bounds
    )

    unaffected_left_b, bounded_b, unaffected_right_b = partition_by_relevant_bounds(
        ranges_b, *true_bounds
    )

    ordered_ranges = sorted(chain(
        bounded_a,
        bounded_b
    ))

    merged_ranges = list[list[int]]()
    intersections = list[list[int]]()

    if ordered_ranges:
        top = ordered_ranges[0]

        for tag_range in ordered_ranges[1:]:
            match top, tag_range:
                case [a_start, a_end], [b_start, b_end] if (
                    a_end + 1 == b_start
                ):
                    top = [a_start, b_end]
                case [a_start, a_end], [b_start, b_end] if (
                    b_start <= a_end and a_end <= b_end
                ):
                    top = [a_start, b_end]
                    intersections.append([b_start, a_end])
                case [a_start, a_end], [b_start, b_end] if (
                    b_end < a_end
                ):
                    intersections.append([b_start, b_end])
                case _, _:
                    merged_ranges.append(top)
                    top = tag_range
        merged_ranges.append(top)

    return (
        [
            *unaffected_left_a,
            *unaffected_left_b,
            *merged_ranges,
            *unaffected_right_a,
            *unaffected_right_b,
        ],
        intersections
    )


def find_index_remove(
    available_tags: list[list[int]],
    tag_range: list[int]
) -> Optional[int]:
    """Find the index of tags in available_tags to be removed"""
    index = bisect.bisect_left(available_tags, tag_range)
    if (index < len(available_tags) and
            tag_range[0] >= available_tags[index][0] and
            tag_range[1] <= available_tags[index][1]):
        return index
    if (index - 1 > -1 and
            tag_range[0] >= available_tags[index-1][0] and
            tag_range[1] <= available_tags[index-1][1]):
        return index - 1
    return None


def find_index_add(
    available_tags: list[list[int]],
    tags: list[int]
) -> Optional[int]:
    """Find the index of tags in available_tags to be added.
    This method assumes that tags is within self.tag_ranges"""
    index = bisect.bisect_left(available_tags, tags)
    if (index == 0 or tags[0] > available_tags[index-1][1]) and \
       (index == len(available_tags) or
            tags[1] < available_tags[index][0]):
        return index
    return None


def partition_by_leftmost(
    tag_ranges: list[list[int]],
    bound: int
):
    bound_range = [bound, bound]
    index = bisect.bisect_left(tag_ranges, bound_range)
    if index == 0:
        return [], tag_ranges
    left_tags = tag_ranges[:index]
    right_tags = tag_ranges[index:]
    match left_tags, right_tags:
        case [*_, [_, a_end]], [*_] if (
            bound <= a_end
        ):
            return tag_ranges[:index - 1], tag_ranges[index - 1:]
        case [*_], [*_]:
            return left_tags, right_tags


def partition_by_rightmost(
    tag_ranges: list[list[int]],
    bound: int
):
    bound_range = [bound, bound]
    index = bisect.bisect_left(tag_ranges, bound_range)
    if index == len(tag_ranges):
        return tag_ranges, []
    left_tags = tag_ranges[:index]
    right_tags = tag_ranges[index:]
    match left_tags, right_tags:
        case [*_], [[b_start, _], *_] if (
            b_start <= bound
        ):
            return tag_ranges[:index + 1], tag_ranges[index + 1:]
        case [*_], [*_]:
            return left_tags, right_tags


def partition_by_relevant_bounds(ranges, start, end):
    left, unkwown = partition_by_leftmost(
        ranges, start
    )
    relevant, right = partition_by_rightmost(
        unkwown, end
    )
    return left, relevant, right
