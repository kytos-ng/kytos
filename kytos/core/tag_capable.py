"""Module for adding tag capabilities"""

from copy import deepcopy
from threading import Lock
from typing import Union

from kytos.core.events import KytosEvent
from kytos.core.exceptions import (KytosInvalidTagRanges,
                                   KytosNoTagAvailableError,
                                   KytosSetTagRangeError,
                                   KytosTagsAreNotAvailable,
                                   KytosTagsNotInTagRanges,
                                   KytosTagtypeNotSupported)
from kytos.core.tag_ranges import (find_index_remove, get_validated_tags,
                                   range_addition, range_difference)


class TAGCapable:
    """
    Class which adds capabilities for tracking tag usage.

    Add this as a super class, and make sure to call
    this class's initializer.
    """

    __slots__ = (
        "available_tags",
        "tag_ranges",
        "default_tag_ranges",
        "special_available_tags",
        "special_tags",
        "default_special_tags",
        "tag_lock",
    )

    available_tags: dict[str, list[list[int]]]
    tag_ranges: dict[str, list[list[int]]]
    default_tag_ranges: dict[str, list[list[int]]]

    special_available_tags: dict[str, list[str]]
    special_tags: dict[str, list[str]]
    default_special_tags: dict[str, list[str]]

    tag_lock: Lock

    def __init__(
        self,
        default_tag_ranges: dict,
        default_special_tags: dict,
    ):
        self.default_tag_ranges = deepcopy(default_tag_ranges)
        self.tag_ranges = deepcopy(default_tag_ranges)
        self.available_tags = deepcopy(default_tag_ranges)

        self.default_special_tags = deepcopy(default_special_tags)
        self.special_tags = deepcopy(default_special_tags)
        self.special_available_tags = deepcopy(default_special_tags)

        self.tag_lock = Lock()

    def notify_tag_listeners(self, controller):
        """Notify changes to tags"""
        controller.buffers.app.put(
            KytosEvent(
                name="kytos/core.generic_tags",
                content={"generic": self}
            )
        )

    def set_available_tags_tag_ranges(
        self,
        available_tag: dict[str, list[list[int]]],
        tag_ranges: dict[str, list[list[int]]],
        default_tag_ranges: dict[str, list[list[int]]],
        special_available_tags: dict[str, list[str]],
        special_tags: dict[str, list[str]],
        default_special_tags: dict[str, list[str]],
    ):
        """
        Set the range of tags to be used by this device.
        """
        self.available_tags = deepcopy(available_tag)
        self.tag_ranges = deepcopy(tag_ranges)
        self.default_tag_ranges = deepcopy(default_tag_ranges)
        self.special_available_tags = deepcopy(special_available_tags)
        self.special_tags = deepcopy(special_tags)
        self.default_special_tags = deepcopy(default_special_tags)

    def all_tags_available(self) -> bool:
        """
        Return True if all tags are avaiable (no tags used),
        False otherwise.
        """
        if self.available_tags != self.tag_ranges:
            return False
        for field, ranges in self.special_tags.items():
            if set(ranges) != set(self.special_tags[field]):
                return False
        return True

    def get_inactive_tags(self, tag_type: str) -> list[list[int]]:
        """
        Get the set of tags from default_tags that are not available
        for use in tag_ranges in use.
        """
        return range_difference(
            self.default_tag_ranges[tag_type],
            self.tag_ranges[tag_type],
        )

    def get_used_tags(self, tag_type: str) -> list[list[int]]:
        """
        Get the set of tags from tag_ranges that are currently in use.
        """
        return range_difference(
            self.tag_ranges[tag_type],
            self.available_tags[tag_type],
        )

    def get_inactive_special_tags(self, tag_type: str) -> list[list[int]]:
        """
        Get the set of tags from default_tags that are not available
        for use in tag_ranges in use.
        """
        full_set = frozenset(self.default_special_tags[tag_type])
        active_set = frozenset(self.special_tags[tag_type])
        return full_set - active_set

    def get_used_special_tags(self, tag_type: str) -> frozenset[str]:
        """
        Get the set of tags from special_tags that are currently in use.
        """
        old_set = frozenset(self.special_tags[tag_type])
        available_set = frozenset(self.special_available_tags[tag_type])
        return old_set - available_set

    def is_tag_type_supported(self, tag_type: str) -> bool:
        """
        Check if the given tag type is supported.
        """
        return tag_type in self.default_tag_ranges

    def is_tag_available(self, tag_type: str, tag: int) -> bool:
        """
        Check if the given tag is available for use.
        """
        index = find_index_remove(
            self.available_tags[tag_type],
            [tag, tag]
        )
        return index is not None

    def assert_tag_type_supported(self, tag_type: str):
        """
        Assert that a given tag type is supported,
        if not raise a KytosTagtypeNotSupported exception.
        """
        if not self.is_tag_type_supported(tag_type):
            raise KytosTagtypeNotSupported(
                f"Tag type {tag_type} is not supported"
            )

    def set_default_tag_ranges(
        self,
        tag_type: str,
        tag_ranges: list[list[int]],
        ignore_missing: bool = False
    ):
        """
        Set the default tag ranges.
        """
        if not tag_ranges and not self.is_tag_type_supported(tag_type):
            return
        if not self.is_tag_type_supported(tag_type):
            self.default_tag_ranges[tag_type] = tag_ranges
            self.tag_ranges[tag_type] = tag_ranges
            self.available_tags[tag_type] = tag_ranges
            return

        inactive_tags = self.get_inactive_tags(tag_type)
        new_active_tags = range_difference(tag_ranges, inactive_tags)

        self.set_tag_ranges(
            tag_type,
            new_active_tags,
            ignore_missing
        )

        if not tag_ranges:
            del self.default_tag_ranges[tag_type]
            del self.tag_ranges[tag_type]
            del self.available_tags[tag_type]
            return

        self.default_tag_ranges = tag_ranges

    def set_tag_ranges(
        self,
        tag_type: str,
        tag_ranges: list[list[int]],
        ignore_missing: bool = False,
        validate_with_default: bool = True,
    ):
        """Set new restriction, tag_ranges."""
        self.assert_tag_type_supported(tag_type)

        used_tags = self.get_used_tags(tag_type)

        if validate_with_default:
            default_ranges = self.default_tag_ranges[tag_type]
            invalid = range_difference(
                tag_ranges,
                default_ranges
            )
            if invalid:
                raise KytosInvalidTagRanges(
                    f"The tags {invalid} are not supported"
                )

        if not ignore_missing:
            missing = range_difference(used_tags, tag_ranges)
            if missing:
                raise KytosSetTagRangeError(
                    f"Missing tags in tag_range: {missing}"
                )

        new_available_tags = range_difference(tag_ranges, used_tags)
        self.available_tags[tag_type] = new_available_tags
        self.tag_ranges[tag_type] = tag_ranges

    def reset_tag_ranges(self, tag_type: str):
        """Sets tag_ranges[tag_type] to default_tag_ranges[tag_type]"""
        self.assert_tag_type_supported(tag_type)

        self.set_tag_ranges(
            tag_type,
            self.default_tag_ranges[tag_type],
            True
        )

    def remove_tag_ranges(self, tag_type: str):
        """Clear tag_ranges[tag_type]"""
        self.set_tag_ranges(
            tag_type,
            [],
            True
        )

    def set_default_special_tags(
        self,
        tag_type: str,
        special_tags: list[str],
        ignore_missing: bool = False
    ):
        """
        Set the default special tag ranges.
        """
        if not special_tags and not self.is_tag_type_supported(tag_type):
            return
        if not self.is_tag_type_supported(tag_type):
            self.default_special_tags[tag_type] = special_tags
            self.special_tags[tag_type] = special_tags
            self.special_available_tags[tag_type] = special_tags
            return

        inactive_tags = self.get_inactive_special_tags(tag_type)
        new_active_tags = frozenset(special_tags) - inactive_tags

        self.set_special_tags(
            tag_type,
            list(new_active_tags),
            ignore_missing,
            False
        )

        if not special_tags:
            del self.default_tag_ranges[tag_type]
            del self.tag_ranges[tag_type]
            del self.available_tags[tag_type]
            return

        self.default_special_tags = special_tags

    def set_special_tags(
        self,
        tag_type: str,
        special_tags: list[str],
        ignore_missing: bool = False,
        validate_with_default: bool = True,
    ):
        """Set new restriction, special_tags"""
        self.assert_tag_type_supported(tag_type)

        used_set = self.get_used_special_tags(tag_type)
        incoming_set = frozenset(special_tags)

        if len(incoming_set) < len(special_tags):
            raise KytosInvalidTagRanges(
                "There are duplicated values in the range."
            )

        if validate_with_default:
            default_set = frozenset(self.default_special_tags[tag_type])
            invalid = incoming_set - default_set
            if invalid:
                raise KytosInvalidTagRanges(
                    f"The tags {invalid} are not supported"
                )

        if not ignore_missing:
            missing = used_set - incoming_set
            if missing:
                raise KytosSetTagRangeError(
                    f"Missing tags in tag_range: {missing}"
                )

        new_available_set = incoming_set - used_set

        self.special_available_tags[tag_type] = list(new_available_set)

        self.special_tags[tag_type] = list(incoming_set)

    def reset_special_tags(self, tag_type: str):
        """Sets special_tags[tag_type] to default_special_tags[tag_type]"""
        self.assert_tag_type_supported(tag_type)

        self.set_special_tags(
            tag_type,
            self.default_special_tags[tag_type],
            True
        )

    def remove_special_tags(self, tag_type: str):
        """Clear tag_ranges[tag_type]"""
        self.set_special_tags(tag_type, [], True)

    def _use_tag_ranges(self, tag_type: str, tag_ranges: list[list[int]]):
        available_tags = self.available_tags[tag_type]
        missing = range_difference(tag_ranges, available_tags)
        if missing:
            raise KytosTagsAreNotAvailable(missing, self)
        new_available = range_difference(available_tags, tag_ranges)
        self.available_tags[tag_type] = new_available

    def _use_special_tag(self, tag_type: str, special_tag: str):
        scratch_set = set(self.special_available_tags[tag_type])
        try:
            scratch_set.remove(special_tag)
        except KeyError as exc:
            raise KytosTagsAreNotAvailable(
                special_tag,
                self
            ) from exc
        self.special_available_tags[tag_type] = list(scratch_set)

    def use_tags(
        self,
        tag_type: str,
        tags: Union[
            str,
            int,
            list[int],
            list[list[int]],
        ],
        check_order: bool = True,
    ):
        """Remove a specific tag from available_tags if it is there.
        Exception raised in case the tags were not able to be removed.

        Args:
            tags: value to be removed, multiple types for compatibility:
                (str): Special vlan, "untagged" or "vlan"
                (int): Single tag
                (list[int]): Single range of tags
                (list[list[int]]): List of ranges of tags
            tag_type: TAG type value
            check_order: Boolean to whether validate tags(list). Check order,
                type and length. Set to false when invocated internally.

        Exceptions:
            KytosTagsAreNotAvailable if tags can't be acquired.
        """
        self.assert_tag_type_supported(tag_type)

        # This kind of validation seems out of place here,
        # the ranges should already be valid before reaching this point.
        if check_order and isinstance(tags, list):
            tags = get_validated_tags(tags)

        match tags:
            case str(special_tag):
                self._use_special_tag(
                    tag_type,
                    special_tag
                )
            case int(tag_value):
                self._use_tag_ranges(
                    tag_type,
                    [[tag_value, tag_value]]
                )
            case [[*_], *_] as tag_ranges:
                self._use_tag_ranges(
                    tag_type,
                    tag_ranges
                )
            case [int(), int()] as tag_range:
                self._use_tag_ranges(
                    tag_type,
                    [tag_range]
                )
            case _:
                # NOTE: Maybe add some kind of exception here?
                pass

    def get_next_available_tag(
        self,
        tag_type: str,
        take_last: bool = False,
        try_avoid_value: int = None,
    ) -> int:
        """Return the next available tag if exists. By default this
         method returns the smallest tag available. Apply options to
         change behavior.
         Options:
           - take_last (bool): Choose the largest tag available.
           - try_avoid_value (int): Avoid given tag if possible. Otherwise
             return what is available.
        """
        self.assert_tag_type_supported(tag_type)
        available_tags = self.available_tags[tag_type]

        if take_last:
            available_tags = reversed(available_tags)

        best_value = None

        for tag_range in available_tags:
            match tag_range, take_last:
                case [range_start, range_end], _ if (
                    range_start == range_end
                    and range_start == try_avoid_value
                ):
                    best_value = range_start
                    continue
                case [range_start, range_end], False if (
                    range_start == try_avoid_value
                ):
                    best_value = range_start + 1
                    break
                case [range_start, range_end], True if (
                    range_end == try_avoid_value
                ):
                    best_value = range_end - 1
                    break
                case [range_start, range_end], False:
                    best_value = range_start
                    break
                case [range_start, range_end], True:
                    best_value = range_end
                    break

        if best_value is None:
            raise KytosNoTagAvailableError(self)

        self._use_tag_ranges(
            tag_type,
            [[best_value, best_value]]
        )

        return best_value

    def _make_tag_ranges_available(
        self,
        tag_type: str,
        tag_ranges: list[list[int]]
    ) -> list[list[int]]:
        allocatable_tags = self.tag_ranges[tag_type]

        unfreeable = range_difference(tag_ranges, allocatable_tags)

        if unfreeable:
            raise KytosTagsNotInTagRanges(unfreeable, self)

        free_tags = self.available_tags[tag_type]

        new_free, already_freed = range_addition(free_tags, tag_ranges)

        self.available_tags[tag_type] = new_free

        return already_freed

    def _make_special_tag_available(self, tag_type: str, special_tag: str):
        if special_tag not in self.special_tags[tag_type]:
            raise KytosTagsNotInTagRanges(special_tag, self)
        if special_tag not in self.special_available_tags[tag_type]:
            self.special_available_tags[tag_type].append(special_tag)
            return None
        return special_tag

    def make_tags_available(
        self,
        tag_type: str,
        tags: Union[
            str,
            int,
            list[int],
            list[list[int]],
        ],
        check_order: bool = True,
    ):
        """Add a tags in available_tags.

        Args:
            tags: value to be added, multiple types for compatibility:
                (str): Special vlan, "untagged" or "vlan"
                (int): Single tag
                (list[int]): Single range of tags
                (list[list[int]]): List of ranges of tags
            tag_type: TAG type value
            check_order: Boolean to whether validate tags(list). Check order,
                type and length. Set to false when invocated internally.

        Return:
            conflict: Return any values that were not added.

        Exeptions:
            KytosTagsNotInTagRanges if tag is not an active tag.
        """
        self.assert_tag_type_supported(tag_type)

        if check_order and isinstance(tags, list):
            tags = get_validated_tags(tags)

        match tags:
            case str(special_tag):
                return self._make_special_tag_available(
                    tag_type,
                    special_tag
                )
            case int(tag_value):
                return self._make_tag_ranges_available(
                    tag_type,
                    [[tag_value, tag_value]]
                )
            case [[*_], *_] as tag_ranges:
                return self._make_tag_ranges_available(
                    tag_type,
                    tag_ranges
                )
            case [int(), int()] as tag_range:
                return self._make_tag_ranges_available(
                    tag_type,
                    [tag_range]
                )
            case _:
                return tags
