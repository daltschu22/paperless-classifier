"""Review identity and recovery regressions. Only synthetic, local adapters."""
import copy
from unittest import TestCase
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from classifier.config import AppError
from classifier.contracts import Approval, Options, SubjectChoice
from classifier.web import create_app
import test_application as fixtures
from test_application import NEW_TAG


class ReviewSafetyTests(TestCase):
    setUp = fixtures.ServiceTests.setUp
    classify = fixtures.ServiceTests.classify
    approve = fixtures.ServiceTests.approve

    def reconcile(self, job):
        self.store.change(job['id'], ['apply_error'], 'apply_queued')
        self.service.step()
        return self.store.get(job['id'])

    def test_old_browser_approval_cannot_select_a_replacement_suggestion(self):
        old = self.classify()
        with TestClient(create_app(self.settings, self.service, worker_enabled=False)) as client:
            headers = {'Origin': self.settings.origin}
            client.post('/api/login', headers=headers, json={'token': self.settings.paperless_token})
            headers['X-CSRF-Token'] = self.store.authenticated(client.cookies.get('classifier_session'))
            enrich = self.generative.discover

            def replacement(*args):
                result, usage = enrich(*args)
                result['subjects'] = [{**NEW_TAG, 'name': 'home-battery', 'evidence': 'home battery'}]
                return result, usage

            self.generative.discover = replacement
            client.post(f"/api/jobs/{old['id']}/retry", headers=headers, json={'force_vision': True})
            self.service.step()
            fresh = self.store.get(old['id'])
            self.assertNotEqual(fresh['proposal_revision'], old['proposal_revision'])
            for revision in (None, old['proposal_revision']):
                response = client.post(f"/api/jobs/{old['id']}/apply", headers=headers,
                                       json={'proposal_revision': revision, 'new_tag_indices': [0]})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['code'], 'stale_proposal')
            self.assertEqual(self.paperless.writes, [])
            self.assertEqual(self.store.get(old['id'])['status'], 'review')
            response = client.post(f"/api/jobs/{old['id']}/apply", headers=headers,
                                   json={'proposal_revision': fresh['proposal_revision'], 'new_tag_indices': [0]})
            self.assertEqual(response.status_code, 200)
            approved = self.store.get(old['id'])['approval']
            self.assertEqual(approved['selected_new_tags'][0]['name'], 'home-battery')
            self.service.step()
            self.assertIn(('create_tag', 'home-battery'), self.paperless.writes)

    def test_revision_check_and_approval_transition_are_atomic(self):
        job = self.classify()
        approve = self.store.approve

        def concurrent_replacement(identifier, revision, approval):
            replacement = copy.deepcopy(job['proposal'])
            replacement['new_tags'][0]['name'] = 'home-battery'
            self.store.change(identifier, ['review'], 'review', proposal=replacement)
            return approve(identifier, revision, approval)

        with patch.object(self.store, 'approve', side_effect=concurrent_replacement):
            with self.assertRaises(AppError) as error:
                self.service.approve(job['id'], Approval(proposal_revision=job['proposal_revision'], new_tag_indices=[0]))
        self.assertEqual(error.exception.code, 'stale_proposal')
        self.assertIsNone(self.store.get(job['id'])['approval'])

    def test_renamed_or_deleted_confirmed_tag_is_not_created_again(self):
        for deleted in (False, True):
            with self.subTest(deleted=deleted):
                self.paperless.doc['title'] = 'scan'
                job = self.classify()
                self.paperless.fail_after_patch = True
                self.assertEqual(self.approve(job, new_tag_indices=[0], title='Reviewed title')['status'], 'apply_error')
                recorded = self.store.operations(job['id'])['tag:0']
                self.assertTrue(recorded['complete'])
                created = self.paperless.tags[-1]
                if deleted:
                    self.paperless.tags.remove(created)
                else:
                    created['name'] = 'solar-power'
                writes = copy.deepcopy(self.paperless.writes)
                self.assertEqual(self.reconcile(job)['error_code'], 'write_conflict')
                self.assertEqual(self.paperless.writes, writes)
                self.assertEqual(self.store.operations(job['id'])['tag:0'], recorded)
                self.store.change(job['id'], ['apply_error'], 'abandoned')
                if not deleted:
                    self.paperless.tags.remove(created)

    def test_completed_title_is_not_replayed_after_manual_reversion(self):
        job = self.classify()
        self.paperless.delay_tags = True
        self.service.stop = Mock()
        self.service.stop.wait.return_value = False
        self.assertEqual(self.approve(job, title='Reviewed title', tag_ids=[1])['error_code'], 'tags_pending')
        recorded = self.store.operations(job['id'])['metadata']
        self.paperless.doc['title'] = job['proposal']['before']['title']
        writes = copy.deepcopy(self.paperless.writes)
        self.assertEqual(self.reconcile(job)['error_code'], 'write_conflict')
        self.assertEqual(self.paperless.writes, writes)
        self.assertEqual(self.store.operations(job['id'])['metadata'], recorded)

    def test_confirmed_tag_addition_is_not_replayed_after_removal(self):
        job = self.classify()
        change = self.store.change

        def interrupted_commit(identifier, expected, status, **values):
            if status == 'applied':
                raise RuntimeError('Synthetic interruption after journal commit')
            return change(identifier, expected, status, **values)

        with patch.object(self.store, 'change', side_effect=interrupted_commit):
            self.assertEqual(self.approve(job, tag_ids=[1])['status'], 'apply_error')
        self.assertTrue(self.store.operations(job['id'])['tags']['complete'])
        self.paperless.doc['tags'].remove(1)
        writes = copy.deepcopy(self.paperless.writes)
        self.assertEqual(self.reconcile(job)['error_code'], 'write_conflict')
        self.assertEqual(self.paperless.writes, writes)

    def test_unconfirmed_creation_without_a_match_requires_fresh_review(self):
        job = self.classify()
        self.paperless.create_tag = Mock(side_effect=AppError('paperless_connection', 'Synthetic timeout'))
        self.assertEqual(self.approve(job, new_tag_indices=[0])['status'], 'apply_error')
        self.assertEqual(self.reconcile(job)['error_code'], 'tag_creation_uncertain')
        self.assertEqual(self.paperless.create_tag.call_count, 1)

    def test_tag_reuse_and_recovery_preserve_curated_definitions(self):
        job = self.classify()
        self.paperless.tags.append({'id': 8, 'name': 'Solar Energy'})
        self.store.define(8, 'Purchase agreements only.')
        self.paperless.fail_after_patch = True
        self.assertEqual(self.approve(job, new_tag_indices=[0], title='Reviewed title')['status'], 'apply_error')
        self.assertEqual(self.store.definitions()[8], 'Purchase agreements only.')
        self.store.define(8, 'Manually refined definition.')
        self.assertEqual(self.reconcile(job)['error_code'], 'stale_tags')
        self.assertEqual(self.store.definitions()[8], 'Manually refined definition.')

    def test_definition_edited_after_creation_survives_recovery(self):
        job = self.classify()
        self.paperless.fail_after_patch = True
        self.approve(job, new_tag_indices=[0], title='Reviewed title')
        identifier = self.paperless.tags[-1]['id']
        self.store.define(identifier, 'Reviewed definition.')
        self.assertEqual(self.reconcile(job)['status'], 'applied')
        self.assertEqual(self.store.definitions()[identifier], 'Reviewed definition.')

    def test_active_reviews_survive_the_history_limit_and_can_be_applied(self):
        active = self.classify()
        for identifier in range(2, 203):
            job, _ = self.store.enqueue(identifier, Options().model_dump())
            self.store.change(job['id'], ['queued'], 'rejected')
        jobs = self.service.jobs()
        self.assertEqual(len(jobs), 201)
        self.assertIn(active['id'], {j['id'] for j in jobs})
        existing, added = self.store.enqueue(1, Options().model_dump())
        self.assertFalse(added)
        self.assertIn(existing['id'], {j['id'] for j in jobs})
        self.assertEqual(self.approve(active, tag_ids=[1])['status'], 'applied')

    def test_weak_ocr_never_reaches_jev_when_vision_is_disabled(self):
        self.paperless.doc['content'] = '\ufffd' * 200 + ' invoice'
        for enrich in (False, True):
            job = self.classify(enrich=enrich, vision_fallback=False)
            self.assertEqual(job['error_code'], 'ocr_unreliable')
            self.assertEqual(self.jev.calls, 0)
            self.store.change(job['id'], ['error'], 'rejected')
        job = self.classify(enrich=False, vision_fallback=True)
        self.assertEqual(job['status'], 'review')
        self.assertEqual(job['proposal']['source'], 'vision')
        self.assertEqual(self.jev.calls, 1)

    def test_pre_revision_approvals_can_still_be_reconciled(self):
        job = self.classify()
        self.store.change(job['id'], ['review'], 'apply_queued', approval={'tag_ids': [1], 'new_tag_indices': [0]})
        self.service.step()
        self.assertEqual(self.store.get(job['id'])['status'], 'applied')
        self.assertIn(('create_tag', 'solar-energy'), self.paperless.writes)

    def test_older_saved_proposal_can_be_reviewed_without_database_migration(self):
        job = self.classify()
        legacy = copy.deepcopy(job['proposal'])
        for key in ('subjects', 'revision', 'prompt_version'):
            legacy.pop(key)
        legacy['schema_version'] = 1
        legacy['new_tags'] = [{**NEW_TAG, 'probability': .93}]
        self.store.change(job['id'], ['review'], 'review', proposal=legacy)
        stored = self.store.get(job['id'])
        self.assertIsNotNone(stored['proposal_revision'])
        final = self.approve(stored, subject_choices=[SubjectChoice(index=0, name='residential-solar')])
        self.assertEqual(final['status'], 'applied')
        self.assertIn(('create_tag', 'residential-solar'), self.paperless.writes)
