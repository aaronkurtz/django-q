from multiprocessing import Event, Queue, Value

import pytest

from django_q.cluster import pusher, worker, monitor
from django_q.conf import Conf
from django_q.tasks import async, result, fetch, count_group, result_group, fetch_group, delete_group, delete_cached, \
    async_iter, Chain, async_chain
from django_q.brokers import get_broker


@pytest.fixture
def broker():
    Conf.DISQUE_NODES = None
    Conf.IRON_MQ = None
    Conf.SQS = None
    Conf.ORM = None
    Conf.MONGO = None
    Conf.DJANGO_REDIS = 'default'
    return get_broker()


@pytest.mark.django_db
def test_cached(broker):
    broker.purge_queue()
    broker.cache.clear()
    group = 'cache_test'
    # queue the tests
    task_id = async('math.copysign', 1, -1, cached=True, broker=broker)
    async('math.copysign', 1, -1, cached=True, broker=broker, group=group)
    async('math.copysign', 1, -1, cached=True, broker=broker, group=group)
    async('math.copysign', 1, -1, cached=True, broker=broker, group=group)
    async('math.copysign', 1, -1, cached=True, broker=broker, group=group)
    async('math.copysign', 1, -1, cached=True, broker=broker, group=group)
    async('math.popysign', 1, -1, cached=True, broker=broker, group=group)
    iter_id = async_iter('math.floor', [i for i in range(10)], cached=True)
    # test wait on cache
    # test wait timeout
    assert result(task_id, wait=10, cached=True) is None
    assert fetch(task_id, wait=10, cached=True) is None
    assert result_group(group, wait=10, cached=True) is None
    assert result_group(group, count=2, wait=10, cached=True) is None
    assert fetch_group(group, wait=10, cached=True) is None
    assert fetch_group(group, count=2, wait=10, cached=True) is None
    # run a single inline cluster
    task_count = 17
    assert broker.queue_size() == task_count
    task_queue = Queue()
    stop_event = Event()
    stop_event.set()
    for i in range(task_count):
        pusher(task_queue, stop_event, broker=broker)
    assert broker.queue_size() == 0
    assert task_queue.qsize() == task_count
    task_queue.put('STOP')
    result_queue = Queue()
    worker(task_queue, result_queue, Value('f', -1))
    assert result_queue.qsize() == task_count
    result_queue.put('STOP')
    monitor(result_queue)
    assert result_queue.qsize() == 0
    # assert results
    assert result(task_id, wait=500, cached=True) == -1
    assert fetch(task_id, wait=500, cached=True).result == -1
    # make sure it's not in the db backend
    assert fetch(task_id) is None
    # assert group
    assert count_group(group, cached=True) == 6
    assert count_group(group, cached=True, failures=True) == 1
    assert result_group(group, cached=True) == [-1, -1, -1, -1, -1]
    assert len(result_group(group, cached=True, failures=True)) == 6
    assert len(fetch_group(group, cached=True)) == 6
    assert len(fetch_group(group, cached=True, failures=False)) == 5
    delete_group(group, cached=True)
    assert count_group(group, cached=True) is None
    delete_cached(task_id)
    assert result(task_id, cached=True) is None
    assert fetch(task_id, cached=True) is None
    # iter cached
    assert result(iter_id) is None
    assert result(iter_id, cached=True) is not None
    broker.cache.clear()


@pytest.mark.django_db
def test_iter(broker):
    broker.purge_queue()
    broker.cache.clear()
    it = [i for i in range(10)]
    it2 = [(1, -1), (2, -1), (3, -4), (5, 6)]
    it3 = (1, 2, 3, 4, 5)
    t = async_iter('math.floor', it, sync=True)
    t2 = async_iter('math.copysign', it2, sync=True)
    t3 = async_iter('math.floor', it3, sync=True)
    t4 = async_iter('math.floor', (1,), sync=True)
    result_t = result(t)
    assert result_t is not None
    task_t = fetch(t)
    assert task_t.result == result_t
    assert result(t2) is not None
    assert result(t3) is not None
    assert result(t4)[0] == 1
    # test cached iter result


@pytest.mark.django_db
def test_chain(broker):
    broker.purge_queue()
    broker.cache.clear()
    task_chain = Chain(sync=True)
    task_chain.append('math.floor', 1)
    task_chain.append('math.copysign', 1, -1)
    task_chain.append('math.floor', 2)
    assert task_chain.length() == 3
    assert task_chain.current() is None
    task_chain.run()
    r = task_chain.result(wait=1000)
    assert task_chain.current() == task_chain.length()
    assert len(r) == task_chain.length()
    t = task_chain.fetch()
    assert len(t) == task_chain.length()
    task_chain.cached = True
    task_chain.append('math.floor', 3)
    assert task_chain.length() == 4
    task_chain.run()
    r = task_chain.result(wait=1000)
    assert task_chain.current() == task_chain.length()
    assert len(r) == task_chain.length()
    t = task_chain.fetch()
    assert len(t) == task_chain.length()
    # test single
    rid = async_chain(['django_q.tests.tasks.hello', 'django_q.tests.tasks.hello'], sync=True, cached=True)
    assert result_group(rid, cached=True) == ['hello', 'hello']
