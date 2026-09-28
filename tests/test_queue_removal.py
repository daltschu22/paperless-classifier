"""Queue removal and provider/writer races, using synthetic adapters only."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient

from classifier.config import AppError, Settings
from classifier.contracts import Approval, Options, metadata
from classifier.service import Service
from classifier.store import Store
from classifier.web import create_app
from test_application import FakeGenerative, FakeJev, FakePaperless


class QueueRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings("https://paperless.example", "test-token", "test-key", Path(self.temp.name))
        self.store = Store(self.temp.name)
        self.paperless = FakePaperless()
        self.service = Service(self.settings, self.store, self.paperless, FakeJev(), FakeGenerative())
        self.client = TestClient(create_app(self.settings, self.service, worker_enabled=False))
        self.addCleanup(self.client.close)
        self.headers = {"Origin": self.settings.origin}
        self.assertEqual(self.client.post('/api/login', headers=self.headers,
                                         json={"token": self.settings.paperless_token}).status_code, 200)
        self.headers['X-CSRF-Token'] = self.store.authenticated(self.client.cookies.get('classifier_session'))

    def enqueue(self, identifier=1):
        return self.store.enqueue(identifier, Options().model_dump())[0]

    def remove(self, job, action='reject'):
        return self.client.post(f'/api/jobs/{job["id"]}/{action}', headers=self.headers, json={})

    def ready(self):
        job = self.enqueue()
        self.service.step()
        return self.store.get(job['id'])

    def test_removal_archives_jobs_and_allows_manual_requeue_without_writes(self):
        for identifier, status in enumerate(('queued', 'review', 'deferred', 'error'), 1):
            with self.subTest(status=status):
                job = self.enqueue(identifier)
                if status != 'queued':
                    self.store.change(job['id'], ['queued'], status)
                self.assertEqual(self.remove(job).status_code, 200)
                self.assertEqual(self.store.get(job['id'])['status'], 'rejected')
        self.assertFalse(self.service.step())
        restored = Store(self.temp.name)
        self.assertTrue(all(job['status'] == 'rejected' for job in restored.jobs()))
        fresh, added = self.store.enqueue(1, Options().model_dump())
        self.assertTrue(added)
        self.assertEqual(fresh['status'], 'queued')
        self.assertEqual(self.paperless.writes, [])

    def test_removal_cancels_approved_changes_before_the_writer_claims_them(self):
        job = self.ready()
        self.service.approve(job['id'], Approval(proposal_revision=job['proposal_revision'], title='Approved title', tag_ids=[1]))
        self.assertEqual(self.remove(job).status_code, 200)
        self.assertFalse(self.service.step())
        removed = self.store.get(job['id'])
        self.assertEqual(removed['status'], 'rejected')
        self.assertEqual(removed['approval']['title'], 'Approved title')
        self.assertEqual(self.paperless.doc['title'], 'scan')
        self.assertEqual(self.paperless.writes, [])

    def test_removal_cannot_interrupt_an_active_writer(self):
        job = self.ready()
        self.service.approve(job['id'], Approval(proposal_revision=job['proposal_revision'], title='Approved title'))
        self.assertEqual(self.store.claim()['status'], 'applying')
        response = self.remove(job)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'state_conflict')
        self.assertEqual(self.store.get(job['id'])['status'], 'applying')

    def test_removal_during_enrichment_stops_jev_and_cannot_replace_a_new_job(self):
        job = self.enqueue()
        enrich = self.service.generative.discover
        replacement = []

        def finish_after_removal(*args):
            self.assertEqual(self.remove(job).status_code, 200)
            replacement.append(self.enqueue())
            return enrich(*args)

        self.service.generative.discover = Mock(side_effect=finish_after_removal)
        self.service.step()
        self.assertEqual(self.service.jev.calls, 0)
        self.assertEqual(self.store.get(job['id'])['status'], 'rejected')
        self.assertIsNone(self.store.get(job['id'])['proposal'])
        self.assertNotEqual(replacement[0]['id'], job['id'])
        self.assertEqual(self.store.get(replacement[0]['id'])['status'], 'queued')
        self.assertEqual(self.paperless.writes, [])

    def test_late_jev_success_or_failure_does_not_resurrect_removed_jobs(self):
        for fails in (False, True):
            with self.subTest(fails=fails):
                job = self.enqueue()
                self.service.jev = FakeJev()
                classify = self.service.jev.classify

                def finish_after_removal(*args):
                    result = classify(*args)
                    self.assertEqual(self.remove(job).status_code, 200)
                    if fails:
                        raise AppError('jev_failed', 'Synthetic failure')
                    return result

                self.service.jev.classify = Mock(side_effect=finish_after_removal)
                self.service.step()
                removed = self.store.get(job['id'])
                self.assertEqual(removed['status'], 'rejected')
                self.assertIsNone(removed['proposal'])
                self.assertIsNone(removed['error_code'])
        self.assertEqual(self.paperless.writes, [])

    def test_closing_failed_application_keeps_partial_changes_and_audit_history(self):
        job = self.ready()
        self.paperless.fail_after_patch = True
        self.service.approve(job['id'], Approval(proposal_revision=job['proposal_revision'], title='Already updated title'))
        self.service.step()
        self.assertEqual(self.store.get(job['id'])['status'], 'apply_error')
        before = copy.deepcopy(self.paperless.doc)
        writes = copy.deepcopy(self.paperless.writes)
        self.assertEqual(self.remove(job, 'abandon').status_code, 200)
        closed = self.store.get(job['id'])
        self.assertEqual(closed['status'], 'abandoned')
        self.assertEqual(closed['proposal']['observed_after_error'], metadata(before))
        self.assertEqual(closed['approval']['title'], 'Already updated title')
        self.assertEqual(self.paperless.doc, before)
        self.assertEqual(self.paperless.writes, writes)


if __name__ == '__main__':
    unittest.main()
