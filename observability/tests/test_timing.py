import asyncio
import time

import pytest

from observability import timed


def key(function, **extra):
    return tuple(sorted({"function": function, **extra}.items()))


def test_times_a_function_and_keeps_its_result_and_name(timings):
    @timed("t.plain", model="m")
    def add(a, b):
        time.sleep(0.01)
        return a + b

    assert add(1, 2) == 3
    assert add.__name__ == "add"
    assert list(timings()) == [key("t.plain", model="m")]
    count, seconds = timings()[key("t.plain", model="m")]
    assert count == 1 and seconds >= 0.01


def test_a_call_that_raises_is_timed_and_reraises(timings):
    @timed("t.raises")
    def boom():
        raise ValueError("bug")

    with pytest.raises(ValueError):
        boom()
    assert timings()[key("t.raises")][0] == 1


def test_times_the_await_of_a_coroutine(timings):
    @timed("t.async")
    async def slow():
        await asyncio.sleep(0.01)
        return "done"

    assert asyncio.run(slow()) == "done"
    count, seconds = timings()[key("t.async")]
    assert count == 1 and seconds >= 0.01


def test_times_the_whole_iteration_of_a_generator(timings):
    @timed("t.gen")
    def numbers():
        yield 1
        time.sleep(0.01)
        yield 2
        return "end"

    gen = numbers()
    assert timings() == {}  # not started yet
    assert list(gen) == [1, 2]
    count, seconds = timings()[key("t.gen")]
    assert count == 1 and seconds >= 0.01


def test_a_closed_generator_is_timed(timings):
    @timed("t.gen.closed")
    def numbers():
        yield 1
        yield 2

    gen = numbers()
    next(gen)
    gen.close()
    assert timings()[key("t.gen.closed")][0] == 1


def test_times_an_async_generator(timings):
    @timed("t.agen")
    async def numbers():
        yield 1
        await asyncio.sleep(0.01)
        yield 2

    async def consume():
        return [n async for n in numbers()]

    assert asyncio.run(consume()) == [1, 2]
    count, seconds = timings()[key("t.agen")]
    assert count == 1 and seconds >= 0.01


def test_needs_a_name():
    with pytest.raises(TypeError, match="needs a name"):
        @timed
        def f():
            pass
