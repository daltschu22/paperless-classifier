"""Synthetic Responses API fixtures; no provider calls or real documents."""
import json
from pathlib import Path
import unittest

import httpx2
from openai import OpenAI

from classifier.config import AppError, Settings
from classifier.contracts import VisionText
from classifier.providers import Generative


class GenerativeResponseTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings("https://paperless.example", "test-token", "test-key", Path("unused"))
        self.requests = []

    def provider(self, body):
        def handle(request):
            self.requests.append(json.loads(request.content))
            return httpx2.Response(200, json=body)
        client = OpenAI(api_key="synthetic-key", max_retries=0,
                        http_client=httpx2.Client(transport=httpx2.MockTransport(handle)))
        self.addCleanup(client.close)
        return Generative(self.settings, client)

    def response(self, status="completed", reason=None, text='{"text":"Synthetic scan text","legible":true}', refusal=False):
        content = {"type": "refusal", "refusal": "SECRET synthetic refusal"} if refusal else {
            "type": "output_text", "text": text, "annotations": []}
        return {"id": "resp_synthetic", "object": "response", "created_at": 0,
                "model": "synthetic-model", "status": status,
                "incomplete_details": {"reason": reason} if reason else None,
                "output": [{"id": "msg_synthetic", "type": "message", "role": "assistant",
                            "status": status, "content": [content]}],
                "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}}

    def call(self, provider):
        return provider.call(VisionText, "Transcribe the scan.", [{"type": "input_text", "text": "synthetic"}])

    def test_incomplete_json_preserves_provider_reason_without_replay(self):
        for reason, code in (("content_filter", "generative_filtered"),
                             ("max_output_tokens", "generative_output_limit"),
                             (None, "generative_incomplete")):
            with self.subTest(reason=reason):
                self.requests.clear()
                provider = self.provider(self.response(status="incomplete", reason=reason,
                                                       text='{"text":"SECRET unfinished scan'))
                with self.assertRaises(AppError) as error:
                    self.call(provider)
                self.assertEqual(error.exception.code, code)
                self.assertNotIn("SECRET", str(error.exception))
                self.assertNotIn("credentials", str(error.exception))
                self.assertEqual(len(self.requests), 1)

    def test_refusal_is_distinct_from_an_empty_or_malformed_result(self):
        with self.assertRaises(AppError) as error:
            self.call(self.provider(self.response(refusal=True)))
        self.assertEqual(error.exception.code, "generative_refused")
        self.assertNotIn("SECRET", str(error.exception))
        self.assertEqual(len(self.requests), 1)

    def test_completed_but_invalid_schema_is_not_a_credentials_error(self):
        with self.assertRaises(AppError) as error:
            self.call(self.provider(self.response(text='{"text":"SECRET", "legible":"invalid boolean"}')))
        self.assertEqual(error.exception.code, "generative_invalid_response")
        self.assertNotIn("SECRET", str(error.exception))

    def test_complete_result_still_uses_sdk_schema_validation_and_usage(self):
        result, usage = self.call(self.provider(self.response()))
        self.assertEqual(result, {"text": "Synthetic scan text", "legible": True})
        self.assertEqual(usage["input_tokens"], 12)
        self.assertEqual(usage["output_tokens"], 8)
        self.assertEqual(usage["model"], "synthetic-model")
        self.assertFalse(self.requests[0]["store"])
        self.assertTrue(self.requests[0]["text"]["format"]["strict"])

    def test_timeout_is_reported_without_exposing_request_details(self):
        def handle(request):
            raise httpx2.ReadTimeout("SECRET request details", request=request)
        client = OpenAI(api_key="synthetic-key", max_retries=0,
                        http_client=httpx2.Client(transport=httpx2.MockTransport(handle)))
        self.addCleanup(client.close)
        with self.assertRaises(AppError) as error:
            self.call(Generative(self.settings, client))
        self.assertEqual(error.exception.code, "generative_timeout")
        self.assertNotIn("SECRET", str(error.exception))


if __name__ == "__main__":
    unittest.main()
