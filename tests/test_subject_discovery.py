"""Open vocabulary discovery, matching and reviewed writes with synthetic providers."""
import copy
from unittest import TestCase
from unittest.mock import Mock

from classifier.config import AppError
from classifier.contracts import Approval, Options, SubjectChoice
from classifier.providers import Jev
import test_application as fixtures


BATTERY = {'name': 'home-battery', 'definition': 'Home electricity storage systems.', 'evidence': 'home battery'}
FINANCE = {'name': 'finance', 'definition': 'Financial documents.', 'evidence': 'Total due: $12000'}


class SubjectDiscoveryTests(TestCase):
    setUp = fixtures.ServiceTests.setUp
    classify = fixtures.ServiceTests.classify
    approve = fixtures.ServiceTests.approve

    def discover(self, subjects):
        self.generative.discover = Mock(return_value=(
            {'text_readable': True, 'title': 'Synthetic invoice', 'subjects': copy.deepcopy(subjects)},
            {'model': 'synthetic-discovery', 'input_tokens': 30, 'output_tokens': 20, 'seconds': .01}))

    def matching_provider(self, choices):
        def result(**request):
            return {'model': 'synthetic-matcher', 'usage': {'input_tokens': 20, 'output_tokens': 10},
                    'answers': {key: {'type': 'choice', 'choice': choices[key], 'confidence': .8,
                                     'probabilities': {option: float(option == choices[key]) for option in question.criteria}}
                                for key, question in request['questions'].items()}}
        client = Mock()
        client.system_one.side_effect = result
        self.jev.reconcile = Mock(wraps=Jev(self.settings, client).reconcile)
        return client

    def test_broad_high_scoring_tags_do_not_hide_a_distinct_subject(self):
        self.discover([FINANCE, BATTERY])
        matcher = self.matching_provider({'subject_1': 'distinct'})
        job = self.classify()
        self.generative.discover.assert_called_once_with(fixtures.TEXT)
        p = job['proposal']
        self.assertEqual([s['existing_tag_id'] for s in p['subjects']], [1, None])
        self.assertTrue(all(t['probability'] >= .9 for t in p['tags']))
        self.assertEqual(p['new_tags'][0]['name'], 'home-battery')
        self.assertEqual(p['new_tags'][0]['subject_index'], 1)
        self.assertEqual(p['subjects'][1]['probability'], .93)
        self.assertIn('jev_matching', {u['provider'] for u in p['usage']})
        self.assertEqual(matcher.system_one.call_count, 1)
        self.assertEqual(self.paperless.writes, [])
        self.assertEqual(self.approve(job, new_tag_indices=[0])['status'], 'applied')
        self.assertIn(('create_tag', 'home-battery'), self.paperless.writes)

    def test_synonym_is_visible_and_can_reuse_existing_id_without_definition_changes(self):
        self.paperless.tags.append({'id': 8, 'name': 'energy-storage'})
        self.store.define(8, 'Curated electricity storage definition.')
        self.discover([BATTERY])
        self.matching_provider({'subject_0': 'tag_8'})
        job = self.classify()
        self.assertEqual(job['proposal']['new_tags'], [])
        subject = job['proposal']['subjects'][0]
        self.assertEqual(subject['existing_tag_id'], 8)
        self.assertEqual(subject['match_answer']['choice'], 'tag_8')
        self.assertEqual(subject['match_answer']['confidence'], .8)
        self.assertEqual(subject['probability'], .93)
        final = self.approve(job, subject_choices=[SubjectChoice(index=0, existing_tag_id=8)])
        self.assertEqual(final['status'], 'applied')
        self.assertEqual(self.paperless.writes, [('add_tags', [8])])
        self.assertEqual(self.store.definitions()[8], 'Curated electricity storage definition.')

    def test_reviewer_can_override_a_semantic_match_and_rename_a_new_tag(self):
        self.discover([BATTERY])
        self.matching_provider({'subject_0': 'tag_2'})
        job = self.classify()
        original = copy.deepcopy(job['proposal'])
        final = self.approve(job, subject_choices=[SubjectChoice(index=0, name='Residential Storage')])
        self.assertEqual(final['status'], 'applied')
        self.assertIn(('create_tag', 'residential-storage'), self.paperless.writes)
        self.assertEqual(final['approval']['selected_new_tags'][0]['name'], 'residential-storage')
        self.assertEqual(final['proposal']['subjects'], original['subjects'])
        self.assertEqual(final['approval']['proposal_revision'], job['proposal_revision'])

    def test_renaming_to_an_existing_tag_reuses_it(self):
        self.discover([BATTERY])
        job = self.classify()
        self.store.define(2, 'Curated household definition.')
        # Changing a definition requires a fresh proposal before application.
        self.store.change(job['id'], ['review'], 'queued')
        self.service.step()
        job = self.store.get(job['id'])
        final = self.approve(job, subject_choices=[SubjectChoice(index=0, name='HOME')])
        self.assertEqual(final['status'], 'applied')
        self.assertEqual(self.paperless.writes, [('add_tags', [2])])
        self.assertEqual(self.store.definitions()[2], 'Curated household definition.')

    def test_newly_approved_tag_is_available_to_later_documents(self):
        self.discover([BATTERY])
        matcher = self.matching_provider({'subject_0': 'distinct'})
        first = self.classify()
        self.assertEqual(self.approve(first, subject_choices=[SubjectChoice(index=0)])['status'], 'applied')
        second = self.classify()
        self.assertEqual(second['proposal']['subjects'][0]['existing_tag_id'], 4)
        self.assertEqual(second['proposal']['subjects'][0]['match_method'], 'name')
        self.assertEqual(second['proposal']['new_tags'], [])
        self.assertIn(4, {t['id'] for t in second['proposal']['taxonomy']['tags']})
        self.assertEqual(matcher.system_one.call_count, 1)

    def test_invalid_matching_answer_stops_before_relevance_or_writes(self):
        self.discover([BATTERY])
        self.matching_provider({'subject_0': 'tag_999'})
        job = self.classify()
        self.assertEqual(job['error_code'], 'jev_failed')
        self.assertIsNone(job['proposal'])
        self.assertEqual(self.jev.calls, 0)
        self.assertEqual(self.paperless.writes, [])

    def test_reserved_subjects_and_unsupported_quotes_are_removed_before_matching(self):
        self.paperless.tags.append({'id': 8, 'name': 'workflow-private', 'is_inbox_tag': True})
        self.discover([{**BATTERY, 'name': 'workflow-private'}, {**BATTERY, 'evidence': 'invented quote'}, BATTERY])
        self.jev.reconcile = Mock(wraps=self.jev.reconcile)
        job = self.classify()
        subjects, taxonomy = self.jev.reconcile.call_args.args
        self.assertEqual(subjects, [BATTERY])
        self.assertNotIn(8, {t['id'] for t in taxonomy['tags']})
        self.assertEqual(len(job['proposal']['subjects']), 1)

    def test_subject_approval_rejects_reserved_invalid_and_duplicate_selections(self):
        job = self.classify()
        cases = [
            [SubjectChoice(index=0, name='needs-tags')],
            [SubjectChoice(index=0, name='---')],
            [SubjectChoice(index=0, existing_tag_id=3)],
            [SubjectChoice(index=0, existing_tag_id=999)],
            [SubjectChoice(index=0, existing_tag_id=1, name='different')],
            [SubjectChoice(index=99)],
            [SubjectChoice(index=0), SubjectChoice(index=0)],
        ]
        for selections in cases:
            with self.subTest(selections=selections), self.assertRaises(AppError):
                self.service.approve(job['id'], Approval(proposal_revision=job['proposal_revision'], subject_choices=selections))
            self.assertEqual(self.store.get(job['id'])['status'], 'review')
        self.assertEqual(self.paperless.writes, [])

    def test_six_subjects_are_visible_but_at_most_three_tags_can_be_created(self):
        self.discover([{**BATTERY, 'name': 'subject-' + str(i)} for i in range(6)])
        job = self.classify()
        self.assertEqual(len(job['proposal']['subjects']), 6)
        with self.assertRaises(AppError) as error:
            self.approve(job, subject_choices=[SubjectChoice(index=i) for i in range(4)])
        self.assertEqual(error.exception.code, 'too_many_new_tags')
        final = self.approve(job, subject_choices=[SubjectChoice(index=i, existing_tag_id=1 if i >= 3 else None) for i in range(6)])
        self.assertEqual(final['status'], 'applied')
        self.assertEqual(sum(w[0] == 'create_tag' for w in self.paperless.writes), 3)

    def test_unselected_subjects_do_not_create_tags(self):
        job = self.classify()
        self.assertEqual(self.approve(job, tag_ids=[1])['status'], 'applied')
        self.assertEqual(self.paperless.writes, [('add_tags', [1])])

    def test_cache_reuses_discovery_matching_and_relevance_together(self):
        self.discover([BATTERY])
        matcher = self.matching_provider({'subject_0': 'distinct'})
        job = self.classify()
        self.store.change(job['id'], ['review'], 'queued')
        self.service.step()
        cached = self.store.get(job['id'])
        self.assertTrue(cached['proposal']['cached'])
        self.assertNotEqual(job['proposal_revision'], cached['proposal_revision'])
        self.assertEqual(cached['proposal']['subjects'], job['proposal']['subjects'])
        self.assertEqual(self.generative.discover.call_count, 1)
        self.assertEqual(matcher.system_one.call_count, 1)
        self.assertEqual(self.jev.calls, 1)

    def test_removal_during_matching_stops_relevance_and_keeps_replacement_job(self):
        job, _ = self.store.enqueue(1, Options().model_dump())
        reconcile = self.jev.reconcile

        def removed(*args):
            self.store.change(job['id'], ['running'], 'rejected')
            self.store.enqueue(1, Options().model_dump())
            return reconcile(*args)

        self.jev.reconcile = Mock(side_effect=removed)
        self.service.step()
        self.assertEqual(self.store.get(job['id'])['status'], 'rejected')
        self.assertEqual(self.jev.calls, 0)
        self.assertEqual(self.paperless.writes, [])
        self.assertEqual(sum(j['status'] == 'queued' for j in self.store.jobs()), 1)

    def test_jev_only_mode_does_not_discover_or_match_subjects(self):
        self.generative.discover = Mock(side_effect=AssertionError('Unexpected discovery'))
        self.jev.reconcile = Mock(side_effect=AssertionError('Unexpected matching'))
        job = self.classify(enrich=False, vision_fallback=False)
        self.assertEqual(job['status'], 'review')
        self.assertEqual(job['proposal']['subjects'], [])
        self.assertEqual(self.jev.calls, 1)

    def test_empty_taxonomy_and_exact_names_need_no_semantic_call(self):
        client = Mock()
        matcher = Jev(self.settings, client)
        result, usage = matcher.reconcile([BATTERY], {'tags': [], 'types': []})
        self.assertIsNone(result[0]['existing_tag_id'])
        self.assertIsNone(usage)
        result, usage = matcher.reconcile([BATTERY], {'tags': [{'id': 9, 'name': 'HOME BATTERY'}]})
        self.assertEqual(result[0]['existing_tag_id'], 9)
        self.assertIsNone(usage)
        client.system_one.assert_not_called()

    def test_existing_tag_limit_includes_manual_subject_matches(self):
        self.paperless.tags = [{'id': i, 'name': 'tag-' + str(i)} for i in range(1, 131)]
        job = self.classify()
        with self.assertRaises(AppError) as error:
            self.approve(job, tag_ids=list(range(1, 129)), subject_choices=[SubjectChoice(index=0, existing_tag_id=129)])
        self.assertEqual(error.exception.code, 'invalid_tags')
        self.assertEqual(self.store.get(job['id'])['status'], 'review')
        self.assertEqual(self.paperless.writes, [])

    def test_oversized_matching_taxonomy_fails_before_provider_call(self):
        client = Mock()
        matcher = Jev(self.settings, client)
        taxonomy = {'tags': [{'id': i, 'name': 'tag-' + str(i)} for i in range(255)]}
        with self.assertRaises(AppError) as error:
            matcher.reconcile([BATTERY], taxonomy)
        self.assertEqual(error.exception.code, 'taxonomy_too_large')
        client.system_one.assert_not_called()

    def test_duplicate_normalized_names_cannot_be_resolved_arbitrarily(self):
        client = Mock()
        matcher = Jev(self.settings, client)
        taxonomy = {'tags': [{'id': 1, 'name': 'Home Battery'}, {'id': 2, 'name': 'home-battery'}]}
        with self.assertRaises(AppError) as error:
            matcher.reconcile([BATTERY], taxonomy)
        self.assertEqual(error.exception.code, 'duplicate_tag')
        client.system_one.assert_not_called()
