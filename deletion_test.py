from dtest import Tester

import time
from jmxutils import make_mbean, JolokiaAgent, remove_perf_disable_shared_mem
from tools import known_failure


class TestDeletion(Tester):

    @known_failure(failure_source='test',
                   jira_url='https://issues.apache.org/jira/browse/CASSANDRA-11364',
                   flaky=True,
                   notes='flaked with "unable to connect" on 3.0')
    def gc_test(self):
        """ Test that tombstone are fully purge after gc_grace """
        cluster = self.cluster

        cluster.populate(1).start()
        [node1] = cluster.nodelist()

        time.sleep(.5)
        session = self.patient_cql_connection(node1)
        self.create_ks(session, 'ks', 1)
        self.create_cf(session, 'cf', gc_grace=0, key_type='int', columns={'c1': 'int'})

        session.execute('insert into cf (key, c1) values (1,1)')
        session.execute('insert into cf (key, c1) values (2,1)')
        node1.flush()

        result = list(session.execute('select * from cf;'))
        assert len(result) == 2 and len(result[0]) == 2 and len(result[1]) == 2, result

        session.execute('delete from cf where key=1')
        result = list(session.execute('select * from cf;'))

        node1.flush()
        time.sleep(.5)
        node1.compact()
        time.sleep(.5)

        result = list(session.execute('select * from cf;'))
        assert len(result) == 1 and len(result[0]) == 2, result

    def tombstone_size_test(self):
        self.cluster.populate(1)
        node1 = self.cluster.nodelist()[0]

        remove_perf_disable_shared_mem(node1)

        self.cluster.start(wait_for_binary_proto=True)
        [node1] = self.cluster.nodelist()
        session = self.patient_cql_connection(node1)
        self.create_ks(session, 'ks', 1)
        session.execute('CREATE TABLE test (i int PRIMARY KEY)')

        stmt = session.prepare('DELETE FROM test where i = ?')
        for i in range(100):
            session.execute(stmt, [i])

        self.assertEqual(memtable_count(node1, 'ks', 'test'), 100)
        self.assertGreater(memtable_size(node1, 'ks', 'test'), 0)


def memtable_size(node, keyspace, table):
    return table_metric(node, keyspace, table, 'MemtableOnHeapSize')


def memtable_count(node, keyspace, table):
    return table_metric(node, keyspace, table, 'MemtableColumnsCount')


def table_metric(node, keyspace, table, name):
    version = node.get_cassandra_version()
    typeName = "ColumnFamily" if version <= '2.2.X' else 'Table'
    with JolokiaAgent(node) as jmx:
        mbean = make_mbean('metrics', type=typeName,
                           name=name, keyspace=keyspace, scope=table)
        value = jmx.read_attribute(mbean, 'Value')

    return value
