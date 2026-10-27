"""Keeping database connections between requests. A stand-in for the SurrealDB client counts opens and closes,
so the rules are checked offline: reuse, never two callers on one connection, a connection that raised is thrown
away, a stale one is replaced, and everything can be switched off."""

import asyncio
from types import SimpleNamespace

import pytest

from app import db


class Stub:
    opened = closed = 0
    ping_fails = False
    signin_fails = False
    slow_opens = 0  # this many opens time out before one works

    def __init__(self, url):
        self.alive = False

    async def connect(self):
        if Stub.slow_opens:
            Stub.slow_opens -= 1
            raise TimeoutError("opening handshake timed out")
        Stub.opened += 1
        self.alive = True

    async def signin(self, creds):
        if Stub.signin_fails:
            raise RuntimeError("bad credentials")

    async def authenticate(self, token): ...

    async def use(self, ns, name): ...

    async def query(self, text, vars=None):
        if Stub.ping_fails and text == "RETURN 1;":  # only the check on an idle connection fails
            raise ConnectionError("the socket closed while idle")
        return [1]

    async def close(self):
        Stub.closed += 1
        self.alive = False

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()


@pytest.fixture(autouse=True)
def stub(monkeypatch):
    Stub.opened = Stub.closed = 0
    Stub.ping_fails = Stub.signin_fails = False
    Stub.slow_opens = 0
    monkeypatch.setattr(db, "AsyncSurreal", Stub)
    monkeypatch.setattr(db, "get_settings", lambda: SimpleNamespace(
        surreal_url="ws://db", surreal_token="", surreal_user="u", surreal_pass="p", surreal_auth_level="root", surreal_ns="n", surreal_db="d"))
    monkeypatch.setattr(db, "_pool", None)
    yield
    monkeypatch.setattr(db, "_pool", None)


def run(coro):
    return asyncio.run(coro)


async def use(n=1):
    for _ in range(n):
        async with db.connect() as c:
            await c.query("x")


def test_without_the_pool_every_call_opens_and_closes_its_own_connection():
    run(use(3))
    assert (Stub.opened, Stub.closed) == (3, 3)


def test_with_the_pool_calls_one_after_another_use_one_connection_and_nothing_closes_until_shutdown():
    async def go():
        db.enable_pool()
        await use(5)
        assert (Stub.opened, Stub.closed) == (1, 0)
        await db.close_pool()
    run(go())
    assert (Stub.opened, Stub.closed) == (1, 1)
    assert db._pool is None


def test_two_calls_at_the_same_time_never_share_a_connection():
    async def go():
        db.enable_pool()
        inside = []

        async def one():
            async with db.connect() as c:
                inside.append(c)
                await asyncio.sleep(0.01)  # both are inside at once
        await asyncio.gather(one(), one())
        assert inside[0] is not inside[1] and Stub.opened == 2
        await use()
        assert Stub.opened == 2  # both went back; the next call reuses one
        await db.close_pool()
    run(go())


def test_a_connection_that_raised_is_closed_and_never_handed_out_again():
    async def go():
        db.enable_pool()
        await use()
        with pytest.raises(ValueError):
            async with db.connect():
                raise ValueError("half way through a write")
        await asyncio.sleep(0)  # the background close
        assert Stub.closed == 1
        await use()
        assert Stub.opened == 2  # a new one, not the one that raised
        await db.close_pool()
    run(go())


def test_a_call_that_is_cancelled_gives_its_connection_up_too():
    async def go():
        db.enable_pool()
        started = asyncio.Event()

        async def slow():
            async with db.connect():
                started.set()
                await asyncio.sleep(10)
        task = asyncio.ensure_future(slow())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert Stub.closed == 1 and not db._pool
        await db.close_pool()
    run(go())


def test_only_a_few_idle_connections_are_kept_and_the_rest_are_closed():
    async def go():
        db.enable_pool()

        async def one():
            async with db.connect():
                await asyncio.sleep(0.01)
        await asyncio.gather(*(one() for _ in range(db.MAX_IDLE + 3)))
        await asyncio.sleep(0)
        assert Stub.opened == db.MAX_IDLE + 3 and Stub.closed == 3 and len(db._pool) == db.MAX_IDLE
        await db.close_pool()
    run(go())


def test_a_connection_idle_for_a_while_is_checked_and_replaced_if_it_went_stale():
    async def go(monkeypatch_ping_fails):
        db.enable_pool()
        await use()
        db._pool[0] = (db._pool[0][0], db._pool[0][1] - db.CHECK_AFTER_S - 1)  # it has been idle a long time
        Stub.ping_fails = monkeypatch_ping_fails
        await use()
        Stub.ping_fails = False
        await db.close_pool()
    run(go(False))
    assert Stub.opened == 1  # still fine: reused after a quick check
    Stub.opened = Stub.closed = 0
    run(go(True))
    assert Stub.opened == 2 and Stub.closed == 2  # went stale: closed, and a fresh one opened for the call


def test_a_failed_sign_in_closes_the_connection_and_says_so():
    async def go():
        db.enable_pool()
        Stub.signin_fails = True
        with pytest.raises(RuntimeError, match="bad credentials"):
            await use()
        assert Stub.opened == 1 and Stub.closed == 1 and not db._pool
        await db.close_pool()
    run(go())


def test_a_session_holds_one_connection_for_everything_inside_it_and_returns_it():
    async def go():
        db.enable_pool()
        async with db.session():
            await use(4)  # four calls, one connection
            assert Stub.opened == 1 and not db._pool  # still held
        assert len(db._pool) == 1 and Stub.closed == 0
        await db.close_pool()
    run(go())


def test_the_pool_can_be_switched_off_by_the_environment_and_shutdown_is_safe_to_repeat(monkeypatch):
    monkeypatch.setenv("SURREAL_POOL", "0")
    db.enable_pool()
    assert db._pool is None
    run(use(2))
    assert Stub.closed == 2
    run(db.close_pool())
    run(db.close_pool())


def test_one_slow_handshake_is_retried_but_a_second_one_fails_the_call():
    async def go():
        db.enable_pool()
        Stub.slow_opens = 1
        await use()  # the first try timed out, the second worked
        assert Stub.opened == 1
        await db.close_pool()
        db.enable_pool()
        Stub.slow_opens = 2
        with pytest.raises(TimeoutError):
            await use()
        await db.close_pool()
    run(go())
