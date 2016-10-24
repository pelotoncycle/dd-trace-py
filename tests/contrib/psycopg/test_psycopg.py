# stdlib
import time

# 3p
import psycopg2
from nose.tools import eq_

# project
from ddtrace import Tracer
from ddtrace.contrib.psycopg import connection_factory

# testing
from ..config import POSTGRES_CONFIG
from ...utils import get_test_tracer


TEST_PORT = str(POSTGRES_CONFIG['port'])


def test_wrap():
    tracer = get_test_tracer()

    services = ["db", "another"]
    for service in services:
        conn_factory = connection_factory(tracer, service=service)
        db = psycopg2.connect(connection_factory=conn_factory, **POSTGRES_CONFIG)

        # Ensure we can run a query and it's correctly traced
        q = "select 'foobarblah'"
        start = time.time()
        cursor = db.cursor()
        cursor.execute(q)
        rows = cursor.fetchall()
        end = time.time()
        eq_(rows, [('foobarblah',)])
        assert rows
        spans = tracer.writer.pop()
        assert spans
        eq_(len(spans), 1)
        span = spans[0]
        eq_(span.name, "postgres.query")
        eq_(span.resource, q)
        eq_(span.service, service)
        eq_(span.meta["sql.query"], q)
        eq_(span.error, 0)
        eq_(span.span_type, "sql")
        assert start <= span.start <= end
        assert span.duration <= end - start

        # run a query with an error and ensure all is well
        q = "select * from some_non_existant_table"
        cur = db.cursor()
        try:
            cur.execute(q)
        except Exception:
            pass
        else:
            assert 0, "should have an error"
        spans = tracer.writer.pop()
        assert spans, spans
        eq_(len(spans), 1)
        span = spans[0]
        eq_(span.name, "postgres.query")
        eq_(span.resource, q)
        eq_(span.service, service)
        eq_(span.meta["sql.query"], q)
        eq_(span.error, 1)
        eq_(span.meta["out.host"], "localhost")
        eq_(span.meta["out.port"], TEST_PORT)
        eq_(span.span_type, "sql")

    # ensure we have the service types
    services = tracer.writer.pop_services()
    expected = {
        "db" : {"app":"postgres", "app_type":"db"},
        "another" : {"app":"postgres", "app_type":"db"},
    }
    eq_(services, expected)
