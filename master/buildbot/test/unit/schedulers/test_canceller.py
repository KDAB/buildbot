# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

from parameterized import parameterized

from twisted.internet import defer
from twisted.trial import unittest

from buildbot.schedulers.canceller import OldBuildCanceller
from buildbot.schedulers.canceller import _FilterCallable
from buildbot.schedulers.canceller import _FilterCombined
from buildbot.schedulers.canceller import _FilterExactMatch
from buildbot.schedulers.canceller import _FilterRegex
from buildbot.schedulers.canceller import _FilterRegexInverse
from buildbot.schedulers.canceller import _OldBuildFilterSet
from buildbot.schedulers.canceller import _OldBuildTracker
from buildbot.schedulers.canceller import extract_filter_values
from buildbot.test import fakedb
from buildbot.test.fake import fakemaster
from buildbot.test.util.config import ConfigErrorsMixin
from buildbot.test.util.misc import TestReactorMixin


class TestFilters(unittest.TestCase):

    def test_extract_filter_values(self):
        self.assertEqual(extract_filter_values([]), [])
        self.assertEqual(extract_filter_values(['value']), ['value'])
        self.assertEqual(extract_filter_values('value'), ['value'])

        with self.assertRaises(ValueError):
            extract_filter_values({'value'})
        with self.assertRaises(ValueError):
            extract_filter_values([{'value'}])

    @parameterized.expand([
        ('no_props', {}, False, False),
        ('no_prop', {'other_prop': 'prop'}, False, False),
        ('prop_wrong_value', {'prop': 'value_other'}, False, False),
        ('prop_value1', {'prop': 'value1'}, False, True),
        ('prop_value1', {'prop': 'value2'}, False, True),
        ('inverse_no_props', {}, True, False),
        ('inverse_no_prop', {'other_prop': 'prop'}, True, False),
        ('inverse_prop_wrong_value', {'prop': 'value_other'}, True, True),
        ('inverse_prop_value1', {'prop': 'value1'}, True, False),
        ('inverse_prop_value1', {'prop': 'value2'}, True, False),
    ])
    def test_exact_match(self, name, props, inverse, expected):
        filter = _FilterExactMatch('prop', ['value1', 'value2'], inverse=inverse)
        self.assertEqual(filter.is_matched(None, props), expected)

    @parameterized.expand([
        ('no_props', {}, False),
        ('no_prop', {'other_prop': 'prop'}, False),
        ('prop_wrong_value', {'prop': 'value_other'}, False),
        ('prop_value1', {'prop': 'value1_smth'}, True),
        ('prop_value1', {'prop': 'value2_smth'}, True),
    ])
    def test_regex(self, name, props, expected):
        filter = _FilterRegex('prop', ['value1.*', 'value2.*'])
        self.assertEqual(filter.is_matched(None, props), expected)

    @parameterized.expand([
        ('no_props', {}, False),
        ('no_prop', {'other_prop': 'prop'}, False),
        ('prop_wrong_value', {'prop': 'value_other'}, True),
        ('prop_value1', {'prop': 'value1_smth'}, False),
        ('prop_value1', {'prop': 'value2_smth'}, False),
    ])
    def test_regex_inverse(self, name, props, expected):
        filter = _FilterRegexInverse('prop', ['value1.*', 'value2.*'])
        self.assertEqual(filter.is_matched(None, props), expected)

    def test_callable_not_callable(self):
        with self.assertRaises(ValueError):
            _FilterCallable('not_callable')

    @parameterized.expand([
        ('is_matched_nothing', {'prop1': 'value_other', 'prop2': 'value_other'}, False),
        ('is_matched_single', {'prop1': 'value1', 'prop2': 'value_other'}, False),
        ('is_matched_all', {'prop1': 'value1', 'prop2': 'value2'}, True),
    ])
    def test_combined(self, name, props, expected):
        filter = _FilterCombined()
        filter.add_subfilter(_FilterExactMatch('prop1', ['value1'], inverse=False))
        filter.add_subfilter(_FilterExactMatch('prop2', ['value2'], inverse=False))
        self.assertEqual(filter.is_matched(None, props), expected)


class TestFilterSet(unittest.TestCase):

    def test_empty_filter(self):
        filter = _OldBuildFilterSet()
        self.assertFalse(filter.is_matched('builder', {'prop': 'value'}))

    @parameterized.expand([
        ('other_builder', 'builder2', {'prop1': 'value1', 'prop2': 'value2'}, False),
        ('nothing', 'builder1', {'prop1': 'value_other', 'prop2': 'value_other'}, False),
        ('single1', 'builder1', {'prop1': 'value1', 'prop2': 'value_other'}, True),
        ('single2', 'builder1', {'prop1': 'value_other', 'prop2': 'value2'}, True),
        ('all', 'builder1', {'prop1': 'value1', 'prop2': 'value2'}, True),
    ])
    def test_multiple_filters_on_builder(self, name, builder, props, expected):
        filter = _OldBuildFilterSet()
        filter.add_filter(['builder1'], _FilterExactMatch('prop1', ['value1']))
        filter.add_filter(['builder1'], _FilterExactMatch('prop2', ['value2']))

        self.assertEqual(filter.is_matched(builder, props), expected)


class TestOldBuildTracker(unittest.TestCase):

    def setUp(self):
        filter = _OldBuildFilterSet()

        combined_filter = _FilterCombined()
        combined_filter.add_subfilter(_FilterExactMatch('codebase', ['cb1', 'cb2']))
        combined_filter.add_subfilter(_FilterExactMatch('repository', ['rp1', 'rp2']))
        combined_filter.add_subfilter(_FilterExactMatch('branch', ['br1', 'br2']))
        filter.add_filter(['bldr1', 'bldr2'], combined_filter)
        self.cancellations = []
        self.tracker = _OldBuildTracker(filter, self.on_cancel)

    def on_cancel(self, id_tuple):
        is_build, id = id_tuple
        self.cancellations.append(('build' if is_build else 'breq', id))

    def assert_cancelled(self, cancellations):
        self.assertEqual(self.cancellations, cancellations)
        self.cancellations = []

    def create_ss_dict(self, project, codebase, repository, branch):
        # Changes have the same structure for the attributes that we're using, so we reuse this
        # function for changes.
        return {
            'project': project,
            'codebase': codebase,
            'repository': repository,
            'branch': branch,
        }

    def test_unknown_branch_not_tracked(self):
        ss_dicts = [self.create_ss_dict('pr1', 'cb1', 'rp1', None)]

        self.tracker.on_new_build(1, 'bldr1', ss_dicts)
        self.assertFalse(self.tracker.is_build_tracked(1))

        self.tracker.on_new_buildrequest(10, 'bldr1', ss_dicts)
        self.assertFalse(self.tracker.is_buildrequest_tracked(10))

    def test_multi_codebase_unknown_branch_not_tracked(self):
        ss_dicts = [self.create_ss_dict('pr1', 'cb1', 'rp1', None),
                    self.create_ss_dict('pr2', 'cb2', 'rp2', 'br2')]

        self.tracker.on_new_build(1, 'bldr1', ss_dicts)
        self.assertFalse(self.tracker.is_build_tracked(1))

        self.tracker.on_new_buildrequest(10, 'bldr1', ss_dicts)
        self.assertFalse(self.tracker.is_buildrequest_tracked(10))

    def test_unmatched_ss_not_tracked(self):
        ss_dicts = [self.create_ss_dict('pr1', 'cb1', 'rp1', 'untracked')]

        self.tracker.on_new_build(1, 'bldr1', ss_dicts)
        self.assertFalse(self.tracker.is_build_tracked(1))

        self.tracker.on_new_buildrequest(10, 'bldr1', ss_dicts)
        self.assertFalse(self.tracker.is_buildrequest_tracked(10))

    def test_multi_codebase_unmatched_ss_not_tracked(self):
        ss_dicts = [self.create_ss_dict('pr1', 'cb1', 'rp1', 'untracked'),
                    self.create_ss_dict('pr2', 'cb2', 'rp2', 'untracked')]

        self.tracker.on_new_build(1, 'bldr1', ss_dicts)
        self.assertFalse(self.tracker.is_build_tracked(1))

        self.tracker.on_new_buildrequest(10, 'bldr1', ss_dicts)
        self.assertFalse(self.tracker.is_buildrequest_tracked(10))

    def test_multi_codebase_tracks_if_at_least_one_ss_match(self):
        ss_dicts = [self.create_ss_dict('pr1', 'cb1', 'rp1', 'untracked'),
                    self.create_ss_dict('pr2', 'cb2', 'rp2', 'br2')]

        self.tracker.on_new_build(1, 'bldr1', ss_dicts)

        self.assertTrue(self.tracker.is_build_tracked(1))

        self.tracker.on_new_buildrequest(10, 'bldr1', ss_dicts)
        self.assertTrue(self.tracker.is_buildrequest_tracked(10))

    def test_cancel_build(self):
        ss_dict = self.create_ss_dict('pr1', 'cb1', 'rp1', 'br1')
        not_matching_ss_dict = self.create_ss_dict('pr1', 'cb1', 'rp1', 'br2')

        self.tracker.on_new_build(1, 'bldr1', [ss_dict])
        self.assertTrue(self.tracker.is_build_tracked(1))

        self.tracker.on_change(not_matching_ss_dict)
        self.assert_cancelled([])
        self.assertTrue(self.tracker.is_build_tracked(1))

        self.tracker.on_change(ss_dict)
        self.assert_cancelled([('build', 1)])
        self.assertFalse(self.tracker.is_build_tracked(1))

        self.tracker.on_change(ss_dict)
        self.assert_cancelled([])

    def test_not_cancel_finished_build(self):
        ss_dict = self.create_ss_dict('pr1', 'cb1', 'rp1', 'br1')

        self.tracker.on_new_build(1, 'bldr1', [ss_dict])
        self.assertTrue(self.tracker.is_build_tracked(1))

        self.tracker.on_finished_build(1)
        self.assertFalse(self.tracker.is_build_tracked(1))

        self.tracker.on_change(ss_dict)
        self.assert_cancelled([])
        self.assertFalse(self.tracker.is_build_tracked(1))

    def test_cancel_buildrequest(self):
        ss_dict = self.create_ss_dict('pr1', 'cb1', 'rp1', 'br1')
        not_matching_ss_dict = self.create_ss_dict('pr1', 'cb1', 'rp1', 'br2')

        self.tracker.on_new_buildrequest(1, 'bldr1', [ss_dict])
        self.assertTrue(self.tracker.is_buildrequest_tracked(1))

        self.tracker.on_change(not_matching_ss_dict)
        self.assert_cancelled([])
        self.assertTrue(self.tracker.is_buildrequest_tracked(1))

        self.tracker.on_change(ss_dict)
        self.assert_cancelled([('breq', 1)])
        self.assertFalse(self.tracker.is_buildrequest_tracked(1))

        self.tracker.on_change(ss_dict)
        self.assert_cancelled([])

    def test_not_cancel_finished_buildrequest(self):
        ss_dict = self.create_ss_dict('pr1', 'cb1', 'rp1', 'br1')

        self.tracker.on_new_buildrequest(1, 'bldr1', [ss_dict])
        self.assertTrue(self.tracker.is_buildrequest_tracked(1))

        self.tracker.on_complete_buildrequest(1)
        self.assertFalse(self.tracker.is_buildrequest_tracked(1))

        self.tracker.on_change(ss_dict)
        self.assert_cancelled([])
        self.assertFalse(self.tracker.is_buildrequest_tracked(1))

    @parameterized.expand([
        ('first', True),
        ('second', False),
    ])
    def test_cancel_multi_codebase_build(self, name, cancel_first_ss):
        ss_dict1 = self.create_ss_dict('pr1', 'cb1', 'rp1', 'br1')
        ss_dict2 = self.create_ss_dict('pr2', 'cb2', 'rp2', 'br2')
        not_matching_ss_dict = self.create_ss_dict('pr1', 'cb1', 'rp1', 'br2')

        self.tracker.on_new_build(1, 'bldr1', [ss_dict1, ss_dict2])
        self.assertTrue(self.tracker.is_build_tracked(1))

        self.tracker.on_change(not_matching_ss_dict)
        self.assert_cancelled([])
        self.assertTrue(self.tracker.is_build_tracked(1))

        self.tracker.on_change(ss_dict1 if cancel_first_ss else ss_dict2)
        self.assert_cancelled([('build', 1)])
        self.assertFalse(self.tracker.is_build_tracked(1))

        self.tracker.on_change(ss_dict1)
        self.tracker.on_change(ss_dict2)
        self.assert_cancelled([])

    def test_cancel_multi_codebase_build_ignores_non_matching_change_in_tracked_build(self):
        ss_dict1 = self.create_ss_dict('pr1', 'cb1', 'rp1', 'br1')
        non_matched_ss_dict = self.create_ss_dict('pr1', 'cb1', 'rp1', 'brZ')

        self.tracker.on_new_build(1, 'bldr1', [ss_dict1, non_matched_ss_dict])
        self.assertTrue(self.tracker.is_build_tracked(1))

        self.tracker.on_change(non_matched_ss_dict)
        self.assert_cancelled([])
        self.assertTrue(self.tracker.is_build_tracked(1))

    def test_cancel_multiple_builds(self):
        ss_dict = self.create_ss_dict('pr1', 'cb1', 'rp1', 'br1')
        not_matching_ss_dict = self.create_ss_dict('pr1', 'cb1', 'rp1', 'br2')

        self.tracker.on_new_build(1, 'bldr1', [ss_dict])
        self.tracker.on_new_build(2, 'bldr1', [ss_dict])
        self.assertTrue(self.tracker.is_build_tracked(1))
        self.assertTrue(self.tracker.is_build_tracked(2))

        self.tracker.on_change(not_matching_ss_dict)
        self.assert_cancelled([])
        self.assertTrue(self.tracker.is_build_tracked(1))
        self.assertTrue(self.tracker.is_build_tracked(2))

        self.tracker.on_change(ss_dict)
        self.assert_cancelled([('build', 1), ('build', 2)])
        self.assertFalse(self.tracker.is_build_tracked(1))
        self.assertFalse(self.tracker.is_build_tracked(2))

        self.tracker.on_change(ss_dict)
        self.assert_cancelled([])

    def test_cancel_multi_codebase_multiple_builds(self):
        ss_dict1 = self.create_ss_dict('pr1', 'cb1', 'rp1', 'br1')
        ss_dict2 = self.create_ss_dict('pr2', 'cb2', 'rp2', 'br2')
        ss_dict3 = self.create_ss_dict('pr3', 'cb3', 'rp3', 'br3')

        self.tracker.on_new_build(1, 'bldr1', [ss_dict1, ss_dict2])
        self.tracker.on_new_build(2, 'bldr1', [ss_dict1, ss_dict3])
        self.tracker.on_new_build(3, 'bldr1', [ss_dict2, ss_dict3])
        self.assertTrue(self.tracker.is_build_tracked(1))
        self.assertTrue(self.tracker.is_build_tracked(2))
        self.assertTrue(self.tracker.is_build_tracked(3))
        self.assert_cancelled([])

        self.tracker.on_change(ss_dict1)
        self.assert_cancelled([('build', 1), ('build', 2)])
        self.assertFalse(self.tracker.is_build_tracked(1))
        self.assertFalse(self.tracker.is_build_tracked(2))
        self.assertTrue(self.tracker.is_build_tracked(3))

        self.tracker.on_change(ss_dict1)
        self.assert_cancelled([])


class TestOldBuildCancellerUtils(ConfigErrorsMixin, unittest.TestCase):

    @parameterized.expand([
        ('only_builder', [{'builders': ['bldr']}]),
        ('with_codebase', [{'builders': ['bldr'], 'codebase_eq': ['value']}]),
        ('with_repository', [{'builders': ['bldr'], 'repository_eq': ['value']}]),
        ('with_branch', [{'builders': ['bldr'], 'branch_eq': ['value']}]),
        ('all', [{
            'builders': ['bldr'],
            'codebase_eq': ['v1', 'v2'],
            'repository_eq': ['v1', 'v2'],
            'branch_eq': ['v1', 'v2'],
        }]),
    ])
    def test_check_filters_valid(self, name, filters):
        OldBuildCanceller.check_filters(filters)

    @parameterized.expand([
        ('dict', {}),
        ('list_list', [[]]),
    ])
    def test_check_filters_not_dict(self, name, value):
        with self.assertRaisesConfigError('The filters argument must be a list of dictionaries'):
            OldBuildCanceller.check_filters(value)

    def test_check_filters_no_builders(self):
        with self.assertRaisesConfigError('The filters must include builders field'):
            OldBuildCanceller.check_filters([{}])

    def test_check_filters_invalid_key(self):
        with self.assertRaisesConfigError('Unknown filter key invalid'):
            OldBuildCanceller.check_filters([{'builders': [], 'invalid': []}])

    @parameterized.expand([
        ('dict', {}, 'Filter values must be list of strings or a string'),
        ('list_int', [1], 'Filter value must be string'),
    ])
    def test_check_filters_keys_not_list(self, name, value, error):
        with self.assertRaisesConfigError(error):
            OldBuildCanceller.check_filters([{'builders': value}])


class TestOldBuildCanceller(TestReactorMixin, unittest.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        self.setUpTestReactor()
        self.master = fakemaster.make_master(self, wantMq=True, wantData=True, wantDb=True)
        self.master.mq.verifyMessages = False

        self.insert_test_data()
        self._cancelled_build_ids = []

        yield self.master.startService()

    def tearDown(self):
        return self.master.stopService()

    def create_ss_dict(self, project, codebase, repository, branch):
        # Changes have the same structure for the attributes that we're using, so we reuse this
        # function for changes.
        return {
            'project': project,
            'codebase': codebase,
            'repository': repository,
            'branch': branch,
        }

    def insert_test_data(self):
        self.master.db.insertTestData([
            fakedb.Master(id=92),
            fakedb.Worker(id=13, name='wrk'),
            fakedb.Builder(id=79, name='builder1'),
            fakedb.Builder(id=80, name='builder2'),

            fakedb.Buildset(id=98, results=None, reason="reason98"),
            fakedb.BuildsetSourceStamp(buildsetid=98, sourcestampid=234),
            fakedb.SourceStamp(id=234, revision='revision1', project='project1',
                               codebase='codebase1', repository='repository1', branch='branch1'),
            fakedb.BuildRequest(id=10, buildsetid=98, builderid=79),
            fakedb.Build(id=19, number=1, builderid=79, buildrequestid=10, workerid=13,
                         masterid=92, results=None, state_string="state1"),

            fakedb.Buildset(id=99, results=None, reason="reason99"),
            fakedb.BuildsetSourceStamp(buildsetid=99, sourcestampid=235),
            fakedb.SourceStamp(id=235, revision='revision2', project='project2',
                               codebase='codebase2', repository='repository2', branch='branch2'),
            fakedb.BuildRequest(id=11, buildsetid=99, builderid=80),
            fakedb.Build(id=20, number=1, builderid=80, buildrequestid=11, workerid=13,
                         masterid=92, results=None, state_string="state2"),
        ])

    @defer.inlineCallbacks
    def setup_canceller_with_filters(self):
        self.canceller = OldBuildCanceller('canceller', [
            {'builders': ['builder1'], 'branch_eq': ['branch1']},
            {'builders': ['builder2'], 'branch_eq': ['branch2']},
        ])
        yield self.canceller.setServiceParent(self.master)

    @defer.inlineCallbacks
    def setup_canceller_with_no_filters(self):
        self.canceller = OldBuildCanceller('canceller', [])
        yield self.canceller.setServiceParent(self.master)

    def assert_cancelled(self, cancellations):
        expected_productions = []
        for kind, id in cancellations:
            if kind == 'build':
                expected_productions.append(
                    (('control', 'builds', str(id), 'stop'),
                     {'reason': 'Build has been obsoleted by a newer commit'}))
            elif kind == 'breq':
                expected_productions.append(
                    (('control', 'buildrequests', str(id), 'cancel'),
                     {'reason': 'Build request has been obsoleted by a newer commit'}))
            else:
                raise Exception(f"Unknown cancellation type {kind}")

        self.master.mq.assertProductions(expected_productions)

    @defer.inlineCallbacks
    def test_cancel_build_after_new_commit(self):
        yield self.setup_canceller_with_filters()

        ss_dict = self.create_ss_dict('project1', 'codebase1', 'repository1', 'branch1')

        self.master.mq.callConsumer(('changes', '123', 'new'), ss_dict)
        self.assert_cancelled([('build', 19)])

        self.master.mq.callConsumer(('changes', '124', 'new'), ss_dict)
        self.assert_cancelled([])

    @defer.inlineCallbacks
    def test_build_finished_then_new_commit_no_cancel(self):
        yield self.setup_canceller_with_filters()

        ss_dict = self.create_ss_dict('project1', 'codebase1', 'repository1', 'branch1')

        self.master.mq.callConsumer(('builds', '19', 'finished'), {'buildid': 19})
        self.master.mq.callConsumer(('changes', '123', 'new'), ss_dict)
        self.assert_cancelled([])

    @defer.inlineCallbacks
    def test_reconfig_no_longer_matched_tracked_build_cancelled(self):
        yield self.setup_canceller_with_filters()

        ss_dict = self.create_ss_dict('project1', 'codebase1', 'repository1', 'branch1')

        yield self.canceller.reconfigService('canceller', [])

        self.master.mq.callConsumer(('changes', '123', 'new'), ss_dict)
        self.assert_cancelled([('build', 19)])

        self.master.mq.callConsumer(('changes', '124', 'new'), ss_dict)
        self.assert_cancelled([])

    @defer.inlineCallbacks
    def test_reconfig_defers_finished_builds_to_after_registration(self):
        # We need to make sure that during reconfiguration any finished build messages are not
        # acted before the build is tracked

        yield self.setup_canceller_with_no_filters()

        ss_dict1 = self.create_ss_dict('project1', 'codebase1', 'repository1', 'branch1')
        ss_dict2 = self.create_ss_dict('project2', 'codebase2', 'repository2', 'branch2')

        # Setup controllable blocking wait on canceller._on_build_new, _on_buildrequest_new
        on_build_new_d = defer.Deferred()
        on_build_new_original = self.canceller._on_build_new
        on_build_new_build_ids = []

        on_buildrequest_new_d = defer.Deferred()
        on_buildrequest_new_original = self.canceller._on_buildrequest_new
        on_buildrequest_new_breq_ids = []

        @defer.inlineCallbacks
        def waiting_on_build_new(key, build):
            on_build_new_build_ids.append(build['buildid'])
            if not on_build_new_d.called:
                yield on_build_new_d
            yield on_build_new_original(key, build)

        self.canceller._on_build_new = waiting_on_build_new

        @defer.inlineCallbacks
        def waiting_on_buildrequest_new(key, breq):
            on_buildrequest_new_breq_ids.append(breq['buildrequestid'])
            if not on_buildrequest_new_d.called:
                yield on_buildrequest_new_d
            yield on_buildrequest_new_original(key, breq)

        self.canceller._on_buildrequest_new = waiting_on_buildrequest_new

        # Start reconfig. We verify that we actually blocked in on_build_new
        d = self.canceller.reconfigService('canceller', [
            {'builders': ['builder1'], 'branch_eq': ['branch1']},
            {'builders': ['builder2'], 'branch_eq': ['branch2']},
        ])

        self.assertEqual(on_build_new_build_ids, [])
        self.assertEqual(on_buildrequest_new_breq_ids, [10])
        self.assertFalse(d.called)

        # The build finish messages should be queued
        self.master.mq.callConsumer(('builds', '19', 'finished'), {'buildid': 19})
        self.master.mq.callConsumer(('builds', '20', 'finished'), {'buildid': 20})
        self.master.mq.callConsumer(('buildrequests', '10', 'complete'), {'buildrequestid': 10})
        self.master.mq.callConsumer(('buildrequests', '11', 'complete'), {'buildrequestid': 11})

        # Unblock reconfigService
        on_build_new_d.callback(None)
        on_buildrequest_new_d.callback(None)
        yield d
        self.assertEqual(on_build_new_build_ids, [19, 20])
        self.assertEqual(on_buildrequest_new_breq_ids, [10, 11])

        self.assertFalse(self.canceller._build_tracker.is_build_tracked(19))
        self.assertFalse(self.canceller._build_tracker.is_build_tracked(20))

        self.assertFalse(self.canceller._build_tracker.is_buildrequest_tracked(10))
        self.assertFalse(self.canceller._build_tracker.is_buildrequest_tracked(11))

        self.master.mq.callConsumer(('changes', '123', 'new'), ss_dict1)
        self.master.mq.callConsumer(('changes', '124', 'new'), ss_dict2)
        self.assert_cancelled([])
