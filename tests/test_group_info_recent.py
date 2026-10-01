"""Opening a group asked the server for /group-info twice (the data note and
the @mention participants run in two threads). get_group_info_recent() lets
the second wait for the first and reuse its answer."""

import threading
import time

from main import MainWindow


class _Stub:
    get_group_info_recent = MainWindow.get_group_info_recent

    def __init__(self, answer):
        self.answer = answer
        self.requests = 0

    def get_group_info(self, jid):
        self.requests += 1
        time.sleep(0.01)
        return self.answer


def test_two_threads_opening_the_same_group_send_one_request():
    stub = _Stub({"participants": [1]})
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(stub.get_group_info_recent("g@g.us")))
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert stub.requests == 1
    assert results == [{"participants": [1]}] * 2


def test_an_old_answer_is_asked_for_again():
    stub = _Stub({"participants": [1]})
    stub.get_group_info_recent("g@g.us", max_age=0)
    stub.get_group_info_recent("g@g.us", max_age=0)
    assert stub.requests == 2


def test_an_empty_answer_is_never_reused():
    stub = _Stub({})
    stub.get_group_info_recent("g@g.us")
    stub.get_group_info_recent("g@g.us")
    assert stub.requests == 2


def test_each_group_has_its_own_answer():
    stub = _Stub({"participants": [1]})
    stub.get_group_info_recent("a@g.us")
    stub.get_group_info_recent("b@g.us")
    assert stub.requests == 2
