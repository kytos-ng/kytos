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

    @pytest.fixture(params=['fixed_window', 'elastic_window'])
    def configured_pacer(self, pacer: Pacer, request):
        """Configure the pacer to have a paced action."""
        pacer.inject_config(
            {
                "paced_action": {
                    "pace": "10/second",
                    "strategy": request.param,
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

    @pytest.mark.skip(reason="Inconsistent behaviour with elastic_window")
    async def test_async_pace_limit(self, configured_pacer: Pacer):
        """Test that actions are being properly paced"""
        async def micro_task():
            await configured_pacer.ahit("paced_action")

        async with asyncio.timeout(20):
            await asyncio.gather(
                *[
                    micro_task()
                    for _ in range(50)
                ]
            )

    async def test_async_pace_limit_exceeded(self, configured_pacer: Pacer):
        """Test that actions are being properly paced"""
        async def micro_task():
            await configured_pacer.ahit("paced_action")

        with pytest.raises(TimeoutError):
            async with asyncio.timeout(9):
                await asyncio.gather(
                    *[
                        micro_task()
                        for _ in range(100)
                    ]
                )

    def test_pace_limit(self, configured_pacer: Pacer):
        """Test that actions are being properly paced"""
        actions_executed = 0

        start = time.time()

        while actions_executed < 50:
            configured_pacer.hit("paced_action")
            actions_executed = actions_executed + 1

        end = time.time()

        elapsed = end - start

        assert elapsed > 4
