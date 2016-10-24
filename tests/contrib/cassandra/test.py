import unittest

from nose.tools import eq_

from ddtrace.contrib.cassandra import missing_modules
if missing_modules:
    raise unittest.SkipTest("Missing dependencies %s" % missing_modules)

from ddtrace.tracer import Tracer
from ddtrace.contrib.cassandra import get_traced_cassandra
from ddtrace.ext import net as netx, cassandra as cassx, errors as errx

from cassandra.cluster import Cluster

from ..config import CASSANDRA_CONFIG
from ...utils import get_test_tracer


class CassandraTest(unittest.TestCase):
    """
    Needs a running Cassandra
    """
    TEST_QUERY = "SELECT * from test.person"
    TEST_KEYSPACE = "test"
    TEST_PORT = str(CASSANDRA_CONFIG['port'])

    def setUp(self):
        if not Cluster:
            raise unittest.SkipTest("cassandra.cluster.Cluster is not available.")

        self.cluster = Cluster(port=CASSANDRA_CONFIG['port'])
        session = self.cluster.connect()
        session.execute("""CREATE KEYSPACE if not exists test WITH REPLICATION = {
            'class' : 'SimpleStrategy',
            'replication_factor': 1
        }""")
        session.execute("CREATE TABLE if not exists test.person (name text PRIMARY KEY, age int, description text)")
        session.execute("""INSERT INTO test.person (name, age, description) VALUES ('Cassandra', 100, 'A cruel mistress')""")

    def _assert_result_correct(self, result):
        eq_(len(result.current_rows), 1)
        for r in result:
            eq_(r.name, "Cassandra")
            eq_(r.age, 100)
            eq_(r.description, "A cruel mistress")

    def _traced_cluster(self):
        tracer = get_test_tracer()
        TracedCluster = get_traced_cassandra(tracer)
        return TracedCluster, tracer.writer


    def test_get_traced_cassandra(self):
        TracedCluster, writer = self._traced_cluster()
        session = TracedCluster(port=CASSANDRA_CONFIG['port']).connect(self.TEST_KEYSPACE)

        result = session.execute(self.TEST_QUERY)
        self._assert_result_correct(result)

        spans = writer.pop()
        assert spans

        # another for the actual query
        eq_(len(spans), 1)

        query = spans[0]
        eq_(query.service, "cassandra")
        eq_(query.resource, self.TEST_QUERY)
        eq_(query.span_type, cassx.TYPE)

        eq_(query.get_tag(cassx.KEYSPACE), self.TEST_KEYSPACE)
        eq_(query.get_tag(netx.TARGET_PORT), self.TEST_PORT)
        eq_(query.get_tag(cassx.ROW_COUNT), "1")
        eq_(query.get_tag(netx.TARGET_HOST), "127.0.0.1")

    def test_trace_with_service(self):
        """
        Tests tracing with a custom service
        """
        tracer = get_test_tracer()
        TracedCluster = get_traced_cassandra(tracer, service="custom")
        session = TracedCluster(port=CASSANDRA_CONFIG['port']).connect(self.TEST_KEYSPACE)

        session.execute(self.TEST_QUERY)
        spans = tracer.writer.pop()
        assert spans
        eq_(len(spans), 1)
        query = spans[0]
        eq_(query.service, "custom")

    def test_trace_error(self):
        TracedCluster, writer = self._traced_cluster()
        session = TracedCluster(port=CASSANDRA_CONFIG['port']).connect(self.TEST_KEYSPACE)

        with self.assertRaises(Exception):
            session.execute("select * from test.i_dont_exist limit 1")

        spans = writer.pop()
        assert spans
        query = spans[0]
        eq_(query.error, 1)
        for k in (errx.ERROR_MSG, errx.ERROR_TYPE, errx.ERROR_STACK):
            assert query.get_tag(k)

    def tearDown(self):
        self.cluster.connect().execute("DROP KEYSPACE IF EXISTS test")
