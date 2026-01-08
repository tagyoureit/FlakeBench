"""
Load Pattern Generators for Performance Testing

This module provides load pattern generators that control the rate and distribution
of operations over time:
- Steady: Constant operation rate
- Burst: Periodic spikes in load
- Ramp-up: Gradual increase in load
- Realistic: Time-of-day patterns based on real usage
"""

from abc import ABC, abstractmethod
from typing import Optional
import asyncio
import time
import math
from datetime import datetime
from enum import Enum


class LoadPatternType(str, Enum):
    """Types of load patterns"""

    STEADY = "STEADY"
    BURST = "BURST"
    RAMP_UP = "RAMP_UP"
    RAMP_DOWN = "RAMP_DOWN"
    SINE_WAVE = "SINE_WAVE"
    REALISTIC = "REALISTIC"
    STEP = "STEP"


class LoadPattern(ABC):
    """
    Abstract base class for load patterns.

    Load patterns control the rate at which operations are generated
    and executed during a performance test.
    """

    def __init__(self, target_ops_per_second: float, duration_seconds: int):
        self.target_ops_per_second = target_ops_per_second
        self.duration_seconds = duration_seconds
        self.start_time: Optional[float] = None

    def start(self):
        """Mark the start of the load pattern"""
        self.start_time = time.time()

    def elapsed_seconds(self) -> float:
        """Get elapsed time since start"""
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time

    @abstractmethod
    def get_current_rate(self) -> float:
        """
        Get the current target operations per second.

        Returns:
            float: Current target ops/sec
        """
        pass

    async def throttle(self):
        """
        Async sleep to maintain target rate.

        Call this after each operation to maintain the desired rate.
        """
        current_rate = self.get_current_rate()
        if current_rate <= 0:
            return

        delay = 1.0 / current_rate
        await asyncio.sleep(delay)

    def is_complete(self) -> bool:
        """Check if the load pattern duration has elapsed"""
        return self.elapsed_seconds() >= self.duration_seconds


class SteadyLoadPattern(LoadPattern):
    """
    Steady state load pattern - maintains constant operation rate.

    This is the simplest pattern, maintaining a consistent rate throughout
    the test duration.
    """

    def get_current_rate(self) -> float:
        """Returns constant target rate"""
        return self.target_ops_per_second


class BurstLoadPattern(LoadPattern):
    """
    Burst load pattern - periodic spikes in load.

    Alternates between baseline and burst rates to simulate sudden
    increases in traffic (e.g., batch jobs, user login storms).
    """

    def __init__(
        self,
        target_ops_per_second: float,
        duration_seconds: int,
        burst_multiplier: float = 5.0,
        burst_duration_seconds: int = 10,
        burst_interval_seconds: int = 60,
    ):
        super().__init__(target_ops_per_second, duration_seconds)
        self.burst_multiplier = burst_multiplier
        self.burst_duration = burst_duration_seconds
        self.burst_interval = burst_interval_seconds

    def get_current_rate(self) -> float:
        """Returns rate based on burst cycle"""
        elapsed = self.elapsed_seconds()

        position_in_cycle = elapsed % self.burst_interval

        if position_in_cycle < self.burst_duration:
            return self.target_ops_per_second * self.burst_multiplier
        else:
            return self.target_ops_per_second


class RampUpLoadPattern(LoadPattern):
    """
    Ramp-up load pattern - gradual increase in load.

    Starts at a low rate and linearly increases to the target rate
    over the specified duration. Useful for testing system behavior
    under increasing load.
    """

    def __init__(
        self,
        target_ops_per_second: float,
        duration_seconds: int,
        start_ops_per_second: Optional[float] = None,
    ):
        super().__init__(target_ops_per_second, duration_seconds)
        self.start_rate = start_ops_per_second or (target_ops_per_second * 0.1)

    def get_current_rate(self) -> float:
        """Returns linearly increasing rate"""
        elapsed = self.elapsed_seconds()
        progress = min(elapsed / self.duration_seconds, 1.0)

        current_rate = (
            self.start_rate + (self.target_ops_per_second - self.start_rate) * progress
        )
        return current_rate


class RampDownLoadPattern(LoadPattern):
    """
    Ramp-down load pattern - gradual decrease in load.

    Starts at target rate and linearly decreases to a low rate.
    Useful for cool-down periods or testing graceful degradation.
    """

    def __init__(
        self,
        target_ops_per_second: float,
        duration_seconds: int,
        end_ops_per_second: Optional[float] = None,
    ):
        super().__init__(target_ops_per_second, duration_seconds)
        self.end_rate = end_ops_per_second or (target_ops_per_second * 0.1)

    def get_current_rate(self) -> float:
        """Returns linearly decreasing rate"""
        elapsed = self.elapsed_seconds()
        progress = min(elapsed / self.duration_seconds, 1.0)

        current_rate = (
            self.target_ops_per_second
            - (self.target_ops_per_second - self.end_rate) * progress
        )
        return current_rate


class SineWaveLoadPattern(LoadPattern):
    """
    Sine wave load pattern - smooth oscillating load.

    Load varies sinusoidally around the target rate. Creates a
    smooth, periodic variation in load useful for testing autoscaling
    and resource adaptation.
    """

    def __init__(
        self,
        target_ops_per_second: float,
        duration_seconds: int,
        amplitude_factor: float = 0.5,
        period_seconds: int = 60,
    ):
        super().__init__(target_ops_per_second, duration_seconds)
        self.amplitude = target_ops_per_second * amplitude_factor
        self.period = period_seconds

    def get_current_rate(self) -> float:
        """Returns sinusoidally varying rate"""
        elapsed = self.elapsed_seconds()

        angle = (2 * math.pi * elapsed) / self.period

        variation = self.amplitude * math.sin(angle)
        current_rate = self.target_ops_per_second + variation

        return max(0, current_rate)


class RealisticLoadPattern(LoadPattern):
    """
    Realistic load pattern - time-of-day based load.

    Simulates realistic daily usage patterns with higher load during
    business hours and lower load at night. Based on configurable
    peak and off-peak hours.
    """

    def __init__(
        self,
        target_ops_per_second: float,
        duration_seconds: int,
        peak_start_hour: int = 9,
        peak_end_hour: int = 17,
        off_peak_multiplier: float = 0.2,
    ):
        super().__init__(target_ops_per_second, duration_seconds)
        self.peak_start = peak_start_hour
        self.peak_end = peak_end_hour
        self.off_peak_multiplier = off_peak_multiplier

    def get_current_rate(self) -> float:
        """Returns rate based on simulated time of day"""
        current_hour = datetime.now().hour

        if self.peak_start <= current_hour < self.peak_end:
            return self.target_ops_per_second
        else:
            return self.target_ops_per_second * self.off_peak_multiplier


class StepLoadPattern(LoadPattern):
    """
    Step load pattern - discrete load levels at intervals.

    Steps through predefined load levels, useful for finding
    breaking points or testing behavior at different load levels.
    """

    def __init__(
        self,
        target_ops_per_second: float,
        duration_seconds: int,
        num_steps: int = 5,
        step_duration_seconds: Optional[int] = None,
    ):
        super().__init__(target_ops_per_second, duration_seconds)
        self.num_steps = num_steps
        self.step_duration = step_duration_seconds or (duration_seconds // num_steps)

        self.step_rates = [
            target_ops_per_second * (i + 1) / num_steps for i in range(num_steps)
        ]

    def get_current_rate(self) -> float:
        """Returns rate for current step"""
        elapsed = self.elapsed_seconds()

        current_step = min(int(elapsed / self.step_duration), self.num_steps - 1)

        return self.step_rates[current_step]


class CompositeLoadPattern(LoadPattern):
    """
    Composite load pattern - combines multiple patterns sequentially.

    Allows creating complex load patterns by chaining together
    different patterns (e.g., ramp-up -> steady -> burst -> ramp-down).
    """

    def __init__(self, patterns: list[tuple[LoadPattern, int]]):
        """
        Args:
            patterns: List of (pattern, duration) tuples
        """
        total_duration = sum(duration for _, duration in patterns)

        if not patterns:
            raise ValueError("Composite pattern requires at least one pattern")

        avg_rate = sum(p.target_ops_per_second for p, _ in patterns) / len(patterns)
        super().__init__(avg_rate, total_duration)

        self.patterns = patterns
        self.current_pattern_index = 0
        self.pattern_start_time = 0.0

    def start(self):
        """Start the composite pattern"""
        super().start()
        if self.patterns:
            self.patterns[0][0].start()

    def get_current_rate(self) -> float:
        """Returns rate from current active pattern"""
        if not self.patterns:
            return 0.0

        elapsed = self.elapsed_seconds()

        accumulated_time = 0.0
        for i, (pattern, duration) in enumerate(self.patterns):
            if elapsed < accumulated_time + duration:
                if i != self.current_pattern_index:
                    self.current_pattern_index = i
                    pattern.start()

                return pattern.get_current_rate()

            accumulated_time += duration

        return self.patterns[-1][0].get_current_rate()


def create_load_pattern(
    pattern_type: LoadPatternType,
    target_ops_per_second: float,
    duration_seconds: int,
    **kwargs,
) -> LoadPattern:
    """
    Factory function to create appropriate load pattern.

    Args:
        pattern_type: Type of load pattern
        target_ops_per_second: Target operations per second
        duration_seconds: Duration of the pattern
        **kwargs: Additional arguments for specific patterns

    Returns:
        LoadPattern instance
    """
    if pattern_type == LoadPatternType.STEADY:
        return SteadyLoadPattern(target_ops_per_second, duration_seconds)

    elif pattern_type == LoadPatternType.BURST:
        return BurstLoadPattern(target_ops_per_second, duration_seconds, **kwargs)

    elif pattern_type == LoadPatternType.RAMP_UP:
        return RampUpLoadPattern(target_ops_per_second, duration_seconds, **kwargs)

    elif pattern_type == LoadPatternType.RAMP_DOWN:
        return RampDownLoadPattern(target_ops_per_second, duration_seconds, **kwargs)

    elif pattern_type == LoadPatternType.SINE_WAVE:
        return SineWaveLoadPattern(target_ops_per_second, duration_seconds, **kwargs)

    elif pattern_type == LoadPatternType.REALISTIC:
        return RealisticLoadPattern(target_ops_per_second, duration_seconds, **kwargs)

    elif pattern_type == LoadPatternType.STEP:
        return StepLoadPattern(target_ops_per_second, duration_seconds, **kwargs)

    else:
        raise ValueError(f"Unknown load pattern type: {pattern_type}")


def create_standard_test_pattern(
    target_ops_per_second: float,
    test_duration_seconds: int,
    warmup_seconds: int = 30,
    cooldown_seconds: int = 30,
) -> CompositeLoadPattern:
    """
    Create a standard test pattern: warmup -> steady -> cooldown.

    Args:
        target_ops_per_second: Target rate during steady state
        test_duration_seconds: Duration of steady state
        warmup_seconds: Duration of warmup ramp-up
        cooldown_seconds: Duration of cooldown ramp-down

    Returns:
        Composite load pattern
    """
    patterns = []

    if warmup_seconds > 0:
        warmup = RampUpLoadPattern(
            target_ops_per_second,
            warmup_seconds,
            start_ops_per_second=target_ops_per_second * 0.1,
        )
        patterns.append((warmup, warmup_seconds))

    steady = SteadyLoadPattern(target_ops_per_second, test_duration_seconds)
    patterns.append((steady, test_duration_seconds))

    if cooldown_seconds > 0:
        cooldown = RampDownLoadPattern(
            target_ops_per_second,
            cooldown_seconds,
            end_ops_per_second=target_ops_per_second * 0.1,
        )
        patterns.append((cooldown, cooldown_seconds))

    return CompositeLoadPattern(patterns)
