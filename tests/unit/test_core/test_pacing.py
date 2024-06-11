"""Tests kytos.core.pacing module."""

import asyncio
import time

import pytest

from kytos.core.pacing import Pacer, PacerWrapper


class TestPacer:
    """Pacer tests"""

    @pytest.fixture
    def pacer(self) -> Pacer:
        """Setup the pacer"""
        return Pacer("memory://")

    @pytest.fixture(
        params=[
            'fixed_window',
            pytest.param(
                'elastic_window',
                marks=pytest.mark.skip(reason='Inconsistent behaviour')
            ),
        ]
    )
    def strategy(self, request):
        """Provide a strategy for tests."""
        return request.param

    @pytest.fixture
    def configured_pacer(self, pacer: Pacer, strategy):
        """Configure the pacer to have a paced action."""
        pacer.inject_config(
            {
                "paced_action": {
                    "pace": "10/second",
                    "strategy": strategy,
                },
            }
        )
        return pacer

    @pytest.fixture
    def pacer_wrapper(self, pacer):
        """Setup a wrapper around the pacer."""
        return PacerWrapper("test_space", pacer)

    def test_check_strategies(self, pacer: Pacer):
        """Check which strategies are present."""
        assert set(pacer.sync_strategies) == {
            'fixed_window', 'elastic_window',
        }
        assert set(pacer.async_strategies) == {
            'fixed_window', 'elastic_window',
        }

    def test_missing_pace(self, pacer: Pacer):
        """Test what happens when no pace is set."""
        pacer.hit("unpaced_action")

    def test_existing_pace(self, configured_pacer: Pacer):
        """Test what happens when a pace is set"""
        configured_pacer.hit("paced_action")

    async def test_async_missing_pace(self, pacer: Pacer):
        """Test what happens when no pace is set."""
        await pacer.ahit("unpaced_action")

    async def test_async_existing_pace(self, configured_pacer: Pacer):
        """Test what happens when a pace is set"""
        await configured_pacer.ahit("paced_action")

    async def test_async_pace_limit(self, configured_pacer: Pacer):
        """Test that actions are being properly paced"""
        async def micro_task():
            await configured_pacer.ahit("paced_action")

        loop = asyncio.get_event_loop()

        start = loop.time()
        async with asyncio.timeout(5):
            await asyncio.gather(
                *[
                    micro_task()
                    for _ in range(20)
                ]
            )
        end = loop.time()

        elapsed = end - start

        assert elapsed > 1

    def test_pace_limit(self, configured_pacer: Pacer):
        """Test that actions are being properly paced"""
        actions_executed = 0

        start = time.time()

        while actions_executed < 20:
            configured_pacer.hit("paced_action")
            actions_executed = actions_executed + 1

        end = time.time()

        elapsed = end - start

        assert elapsed > 1

    def test_nonexistant_strategy(self, pacer: Pacer):
        """Make sure that nonexistant strategies raise an exception"""
        with pytest.raises(ValueError):
            pacer.inject_config(
                {
                    "paced_action": {
                        "pace": "10/second",
                        "strategy": "non-existant strategy",
                    },
                }
            )

    def test_bad_pace(self, pacer: Pacer, strategy):
        """Make sure that bad pace values raise an exception"""
        with pytest.raises(ValueError):
            pacer.inject_config(
                {
                    "paced_action": {
                        "pace": "z10/second",
                        "strategy": strategy,
                    },
                }
            )
