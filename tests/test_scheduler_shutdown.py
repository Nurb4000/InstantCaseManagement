"""Q3 — the background scheduler must be reachable and shut down cleanly.

Verifies the two directions of the signal-handling guard: outside pytest a
SIGTERM/SIGINT handler is installed and the scheduler is exposed on the app;
under pytest (the normal run) no signal handlers are installed so we never
clobber the test runner's own signal handling.
"""
import signal


def _seed_env(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{tmp_path}/q3.db')
    monkeypatch.setenv('SECRET_KEY', 'b' * 40)
    monkeypatch.setenv('ADMIN_CREATE', 'false')


def test_scheduler_shutdown_wiring(app, monkeypatch, tmp_path):
    import sys
    from app import create_app

    _seed_env(monkeypatch, tmp_path)

    prev_term = signal.getsignal(signal.SIGTERM)
    prev_int = signal.getsignal(signal.SIGINT)
    apps = []
    try:
        # Direction 1: not under pytest -> signals installed + scheduler exposed.
        monkeypatch.delitem(sys.modules, 'pytest', raising=False)
        app1 = create_app(testing=False)
        apps.append(app1)
        assert getattr(app1, 'scheduler', None) is not None
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler) and handler is not signal.SIG_DFL

        # Reset to the pre-test handlers so Direction 2 starts from a clean slate.
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGINT, prev_int)

        # Direction 2: under pytest -> no signal wiring even in non-testing mode.
        monkeypatch.setitem(sys.modules, 'pytest', object())
        app2 = create_app(testing=False)
        apps.append(app2)
        assert signal.getsignal(signal.SIGTERM) == prev_term
    finally:
        for a in apps:
            sched = getattr(a, 'scheduler', None)
            if sched is not None:
                sched.shutdown(wait=False)
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGINT, prev_int)
