

import unittest
from logging import LogRecord

import pytest

from kytos.logging.filters import RepeateMessageFilter


class TestRepeateMessageFilter:

    @pytest.fixture(
        params=[
            1.0,
            5.0,
            10.0,
        ]
    )
    def lockout_time(self, request):
        return request.param

    @pytest.fixture(
        params=[
            1,
            256,
            512,
            1024,
        ]
    )
    def cache_size(self, request):
        return request.param

    @pytest.fixture
    def message_filter(self, lockout_time, cache_size):
        return RepeateMessageFilter(lockout_time, cache_size)

    @staticmethod
    def make_record(msg, ct):
        record = LogRecord(
            "test_logger",
            0,
            "test_path",
            1337,
            msg,
            ("arg1", "arg2"),
            None
        )
        record.created = ct
        record.relativeCreated = ct
        return record

    @pytest.fixture
    def blockable_record(self):
        return self.make_record("test", 0.0)

    @pytest.fixture
    def unblockable_record(self, lockout_time):
        return self.make_record("test", lockout_time + 1)

    @pytest.fixture
    def message_filter_with_one_message(
        self,
        message_filter,
        blockable_record
    ):
        assert message_filter.filter(blockable_record)
        return message_filter

    @pytest.fixture
    def message_filter_with_one_message_and_junk(
        self,
        message_filter_with_one_message,
        cache_size
    ):
        for i in range(cache_size - 1):
            assert message_filter_with_one_message.filter(
                self.make_record(f"junk-{i}", 0.0)
            )
        return message_filter_with_one_message

    @pytest.fixture
    def last_junk_record(
        self,
        cache_size
    ):
        return self.make_record(f"junk-{cache_size - 1}", 0.0)

    def test_001_filter(
        self,
        message_filter_with_one_message,
        blockable_record,
        unblockable_record
    ):
        assert not message_filter_with_one_message.filter(blockable_record)
        assert message_filter_with_one_message.filter(unblockable_record)
        assert not message_filter_with_one_message.filter(blockable_record)
        assert not message_filter_with_one_message.filter(unblockable_record)

    def test_002_cache_eviction(
        self,
        message_filter_with_one_message_and_junk,
        blockable_record,
        last_junk_record
    ):
        assert not message_filter_with_one_message_and_junk.filter(
            blockable_record
        )
        assert message_filter_with_one_message_and_junk.filter(
            last_junk_record
        )
        assert message_filter_with_one_message_and_junk.filter(
            blockable_record
        )
