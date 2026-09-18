"""Synthetic, offline integration tests; no real documents or provider calls."""
import copy
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import httpx
from PIL import Image

from classifier.config import AppError, Settings
from classifier.contracts import Approval, Options
from classifier.paperless import Paperless
from classifier.providers import Generative, Jev, clean_suggestions, render_pages
from classifier.service import Service
from classifier.store import Store
from classifier.web import create_app

TEXT = "Synthetic solar installation invoice. Rooftop solar panels and a home battery. Total due: $12000."
NEW_TAG = {"name":"solar-energy", "definition":"Documents about solar electricity systems.", "evidence":"Rooftop solar panels"}


class FakePaperless:
    def __init__(self):
        self.doc = {"id":1,"title":"scan","content":TEXT,"tags":[3],"document_type":2,"added":"2026-09-17T00:00:00Z"}
        self.tags = [{"id":1,"name":"finance"},{"id":2,"name":"home"},{"id":3,"name":"inbox","is_inbox_tag":True}]
        self.types = [{"id":1,"name":"Invoice"},{"id":2,"name":"Letter"}]
        self.writes = []
        self.fail_after_create = False
        self.fail_after_patch = False
        self.delay_tags = False

    def document(self, identifier):
        return copy.deepcopy(dict(self.doc, id=identifier))

    def documents(self, page=1, query="", tag_id=None):
        return {"count":1,"next":None,"results":[self.document(1)]}

    def all(self, kind):
        return copy.deepcopy(self.tags if kind=="tags" else self.types)

    def taxonomy(self):
        return {"tags":self.all("tags"),"types":self.all("document_types")}

    def file(self, identifier):
        return b"fake scan", "image/png"

    def login(self, username, password):
        return "test-paperless-token" if username=="owner" and password=="pass" else "other-user-token"

    def patch(self, identifier, values):
        self.writes.append(("patch",copy.deepcopy(values)))
        self.doc.update(values)
        if self.fail_after_patch:
            self.fail_after_patch=False
            raise AppError("paperless_connection","Connection lost.")

    def add_tags(self, identifier, ids):
        self.writes.append(("add_tags",sorted(ids)))
        if not self.delay_tags:
            self.doc["tags"]=sorted(set(self.doc["tags"])|set(ids))
        return {"task_id":"synthetic-task"}

    def create_tag(self, name):
        self.writes.append(("create_tag",name))
        tag={"id":max(t["id"] for t in self.tags)+1,"name":name}
        self.tags.append(tag)
        if self.fail_after_create:
            self.fail_after_create=False
            raise AppError("paperless_connection","Connection lost.")
        return copy.deepcopy(tag)


class FakeJev:
    def __init__(self):
        self.calls=0

    def classify(self,text,taxonomy,proposed):
        self.calls+=1
        answers={"tag_"+str(t["id"]):{"type":"noul","noul":.9} for t in taxonomy["tags"]}
        answers.update({"new_"+str(i):{"type":"noul","noul":.93} for i,t in enumerate(proposed)})
        if taxonomy["types"]:
            answers["document_type"]={"type":"choice","choice":"type_1","confidence":.9,"probabilities":{"type_1":.95,"type_2":.04,"unknown":.01}}
        return answers,{"model":"synthetic-jev","input_tokens":40,"output_tokens":20,"seconds":.01}


class FakeGenerative:
    def __init__(self):
        self.vision_calls=0

    def enrich(self,text,taxonomy):
        return {"text_readable":True,"title":"Solar installation invoice","new_tags":[copy.deepcopy(NEW_TAG)]},{"model":"synthetic-generator","input_tokens":50,"output_tokens":20,"seconds":.01}

    def vision(self,data,mime):
        self.vision_calls+=1
        return {"text":TEXT,"legible":True},{"model":"synthetic-vision","input_tokens":50,"output_tokens":20,"seconds":.01}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings=Settings("https://paperless.example","test-paperless-token","test-typesafe-key",Path(self.temp.name))
        self.store=Store(self.settings.data_dir)
        self.paperless=FakePaperless()
        self.jev=FakeJev()
        self.generative=FakeGenerative()
        self.service=Service(self.settings,self.store,self.paperless,self.jev,self.generative)

    def classify(self, **options):
        job,_=self.store.enqueue(1,Options(**options).model_dump())
        self.service.step()
        return self.store.get(job["id"])

    def approve(self,job,**values):
        self.service.approve(job["id"],Approval(**values))
        self.service.step()
        return self.store.get(job["id"])

    def test_classification_has_no_writes_and_excludes_control_tags(self):
        job=self.classify()
        self.assertEqual(job["status"],"review")
        self.assertEqual(self.paperless.writes,[])
        self.assertEqual({t["id"] for t in job["proposal"]["tags"]},{1,2})
        self.assertEqual(job["proposal"]["new_tags"][0]["name"],"solar-energy")

    def test_duplicate_submission_reuses_job_and_cached_retry_uses_no_provider(self):
        job=self.classify()
        duplicate,added=self.store.enqueue(1,Options().model_dump())
        self.assertFalse(added)
        self.assertEqual(job["id"],duplicate["id"])
        self.store.change(job["id"],["review"],"queued")
        self.service.step()
        self.assertTrue(self.store.get(job["id"])["proposal"]["cached"])
        self.assertEqual(self.jev.calls,1)

    def test_definition_change_invalidates_inference_cache(self):
        job=self.classify()
        self.store.define(1,"Personal finances only")
        self.store.change(job["id"],["review"],"queued")
        self.service.step()
        self.assertEqual(self.jev.calls,2)

    def test_missing_ocr_uses_vision_without_replacing_paperless_text(self):
        self.paperless.doc["content"]=""
        job=self.classify()
        self.assertEqual(job["proposal"]["source"],"vision")
        self.assertEqual(self.generative.vision_calls,1)
        self.assertEqual(self.paperless.doc["content"],"")
        self.assertEqual(self.paperless.writes,[])

    def test_missing_ocr_with_vision_disabled_fails(self):
        self.paperless.doc["content"]=""
        job=self.classify(vision_fallback=False)
        self.assertEqual(job["error_code"],"ocr_missing")
        self.assertEqual(self.jev.calls,0)

    def test_garbled_long_ocr_uses_readability_gate_and_vision(self):
        good=self.generative.enrich(TEXT,{})
        self.generative.enrich=Mock(side_effect=[({"text_readable":False,"title":"","new_tags":[]},good[1]),good])
        job=self.classify()
        self.assertEqual(job["proposal"]["source"],"vision")
        self.assertEqual(self.generative.vision_calls,1)
        self.assertEqual(self.generative.enrich.call_count,2)
        self.assertEqual(self.jev.calls,1)
        self.assertEqual(self.paperless.writes,[])

    def test_garbled_ocr_without_vision_is_a_visible_error(self):
        self.generative.enrich=Mock(return_value=({"text_readable":False,"title":"","new_tags":[]},{}))
        job=self.classify(vision_fallback=False)
        self.assertEqual(job["error_code"],"ocr_unreliable")
        self.assertEqual(self.jev.calls,0)

    def test_unreadable_vision_does_not_continue_to_classification(self):
        self.paperless.doc["content"]=""
        self.generative.vision=Mock(return_value=({"text":"[illegible]","legible":False},{}))
        job=self.classify()
        self.assertEqual(job["error_code"],"scan_unreadable")
        self.assertEqual(self.jev.calls,0)

    def test_filtered_vision_stops_before_classification_or_paperless_writes(self):
        self.paperless.doc["content"]=""
        self.generative.vision=Mock(side_effect=AppError("generative_filtered","Review the original document in Paperless."))
        job=self.classify()
        self.assertEqual(job["status"],"error")
        self.assertEqual(job["error_code"],"generative_filtered")
        self.assertIsNone(job["proposal"])
        self.assertEqual(self.jev.calls,0)
        self.assertEqual(self.paperless.writes,[])

    def test_failed_job_keeps_its_name_before_a_proposal_exists(self):
        self.paperless.doc["title"]="Example insurance statement"
        self.generative.enrich=Mock(side_effect=AppError("generative_filtered","Review the original."))
        job=self.classify()
        self.assertIsNone(job["proposal"])
        self.paperless.document=Mock(side_effect=AppError("paperless_connection","Unavailable"))
        result=self.service.jobs()[0]
        self.assertEqual(result["document_title"],"Example insurance statement")
        self.assertEqual(result["status"],"error")
        self.paperless.document.assert_not_called()
        self.assertEqual(self.jev.calls,0)
        self.assertEqual(self.paperless.writes,[])

    def test_queued_and_legacy_failed_jobs_resolve_names_without_inference(self):
        self.store.enqueue(73,Options().model_dump())
        old,_=self.store.enqueue(74,Options().model_dump())
        self.store.change(old["id"],["queued"],"error",error_code="generative_filtered")
        self.paperless.document=Mock(wraps=self.paperless.document)
        for _ in range(2):
            jobs=self.service.jobs()
            self.assertEqual({job["document_title"] for job in jobs},{"scan"})
            self.assertEqual({job["status"] for job in jobs},{"queued","error"})
        self.assertEqual(self.paperless.document.call_count,2)
        self.assertEqual(self.jev.calls,0)
        self.assertEqual(self.paperless.writes,[])

    def test_name_lookup_failure_preserves_jobs_and_recovers(self):
        job,_=self.store.enqueue(73,Options().model_dump())
        self.store.change(job["id"],["queued"],"error",error_code="generative_filtered")
        self.paperless.document=Mock(side_effect=AppError("paperless_connection","Unavailable"))
        with patch("classifier.service.time.monotonic",return_value=100):
            for _ in range(2):
                result=self.service.jobs()[0]
                self.assertEqual(result["document_title"],"")
                self.assertEqual(result["error_code"],"generative_filtered")
        self.paperless.document.assert_called_once_with(73)
        self.paperless.document.side_effect=None
        self.paperless.document.return_value={"title":"Restored document name"}
        with patch("classifier.service.time.monotonic",return_value=200):
            self.assertEqual(self.service.jobs()[0]["document_title"],"Restored document name")

    def test_apply_preserves_concurrently_added_tags(self):
        job=self.classify()
        self.paperless.doc["tags"].append(99)
        final=self.approve(job,tag_ids=[1],document_type=1,title="Reviewed title")
        self.assertEqual(final["status"],"applied")
        self.assertEqual(set(self.paperless.doc["tags"]),{1,3,99})
        self.assertFalse(any(w[0]=="create_tag" for w in self.paperless.writes))
        self.assertEqual(final["proposal"]["after"]["title"],"Reviewed title")
        with self.assertRaises(AppError): self.service.approve(job["id"],Approval())

    def test_explicit_new_tag_approval_creates_and_adds_once(self):
        job=self.classify()
        final=self.approve(job,new_tag_indices=[0,0])
        self.assertEqual(final["status"],"applied")
        self.assertEqual([w[0] for w in self.paperless.writes],["create_tag","add_tags"])
        self.assertIn(4,self.paperless.doc["tags"])
        self.assertEqual(self.store.definitions()[4],NEW_TAG["definition"])

    def test_existing_normalized_name_is_reused(self):
        job=self.classify()
        self.paperless.tags.append({"id":8,"name":"Solar Energy"})
        final=self.approve(job,new_tag_indices=[0])
        self.assertEqual(final["status"],"applied")
        self.assertEqual(self.paperless.writes,[("add_tags",[8])])

    def test_timeout_after_create_reconciles_without_duplicate(self):
        job=self.classify()
        self.paperless.fail_after_create=True
        failed=self.approve(job,new_tag_indices=[0])
        self.assertEqual(failed["status"],"apply_error")
        self.store.change(job["id"],["apply_error"],"apply_queued")
        self.service.step()
        self.assertEqual(self.store.get(job["id"])["status"],"applied")
        self.assertEqual(sum(w[0]=="create_tag" for w in self.paperless.writes),1)

    def test_timeout_after_patch_reconciles_without_second_patch(self):
        job=self.classify()
        self.paperless.fail_after_patch=True
        self.assertEqual(self.approve(job,title="Reviewed title")["status"],"apply_error")
        self.store.change(job["id"],["apply_error"],"apply_queued")
        self.service.step()
        self.assertEqual(self.store.get(job["id"])["status"],"applied")
        self.assertEqual(sum(w[0]=="patch" for w in self.paperless.writes),1)

    def test_async_acceptance_is_not_reported_as_completion(self):
        job=self.classify()
        self.paperless.delay_tags=True
        self.service.stop=Mock()
        self.service.stop.wait.return_value=False
        self.assertEqual(self.approve(job,tag_ids=[1])["error_code"],"tags_pending")
        self.paperless.doc["tags"].append(1)
        self.store.change(job["id"],["apply_error"],"apply_queued")
        self.service.step()
        self.assertEqual(self.store.get(job["id"])["status"],"applied")
        self.assertEqual(sum(w[0]=="add_tags" for w in self.paperless.writes),1)

    def test_stale_text_and_metadata_are_not_overwritten(self):
        for field,new_value,code in [("content","Replacement text","stale_document"),("title","Someone else's title","stale_metadata")]:
            with self.subTest(field=field):
                job=self.classify()
                self.paperless.doc[field]=new_value
                result=self.approve(job,title="Reviewed title")
                self.assertEqual(result["error_code"],code)
                self.assertEqual(self.paperless.writes,[])
                self.store.change(job["id"],["apply_error"],"abandoned")

    def test_renamed_taxonomy_rejects_stale_approval(self):
        job=self.classify()
        self.paperless.tags[0]["name"]="renamed"
        self.assertEqual(self.approve(job,tag_ids=[1])["error_code"],"stale_taxonomy")
        self.assertEqual(self.paperless.writes,[])

    def test_queue_removal_prevents_apply(self):
        self.store.set_setting("intake",{"tag_id":3,"enabled":True})
        self.service.poll();self.service.step()
        job=self.store.jobs()[0]
        self.paperless.doc["tags"]=[]
        self.assertEqual(self.approve(job,tag_ids=[1])["error_code"],"queue_removed")

    def test_poll_is_opt_in_deduplicated_and_paused(self):
        self.service.poll();self.assertEqual(self.store.jobs(),[])
        self.store.set_setting("intake",{"tag_id":3,"enabled":True})
        self.store.set_setting("paused",True)
        self.service.poll();self.assertEqual(self.store.jobs(),[])
        self.store.set_setting("paused",False)
        self.service.poll();self.service.poll();self.assertEqual(len(self.store.jobs()),1)
        self.assertEqual(self.paperless.writes,[])

    def test_restart_marks_ambiguous_application_for_reconciliation(self):
        job=self.classify()
        self.service.approve(job["id"],Approval(tag_ids=[1]))
        self.store.claim()
        Store(self.settings.data_dir).recover()
        self.assertEqual(self.store.get(job["id"])["status"],"apply_error")

    def test_only_one_worker_can_own_database(self):
        self.service.start()
        try:
            other=Service(self.settings,self.store,self.paperless,self.jev,self.generative)
            with self.assertRaises(RuntimeError):other.start()
            other.lock.close()
        finally:self.service.close()

    def test_sessions_origin_csrf_and_complete_review_flow(self):
        with TestClient(create_app(self.settings,self.service,worker_enabled=False)) as client:
            origin={"Origin":self.settings.origin}
            self.assertEqual(client.get("/api/state").status_code,401)
            self.assertEqual(client.post("/api/login",json={"token":self.settings.paperless_token}).status_code,403)
            self.assertEqual(client.post("/api/login",headers=origin,json={"username":"other","password":"pass"}).status_code,401)
            response=client.post("/api/login",headers=origin,json={"username":"owner","password":"pass"})
            self.assertEqual(response.status_code,200)
            csrf=self.store.authenticated(client.cookies.get("classifier_session"))
            self.assertNotIn(self.settings.paperless_token,client.get("/").text)
            self.assertEqual(client.post("/api/jobs",headers=origin,json={"document_ids":[1]}).status_code,403)
            headers={**origin,"X-CSRF-Token":csrf}
            result=client.post("/api/jobs",headers=headers,json={"document_ids":[1]})
            self.assertEqual(result.status_code,200)
            self.service.step()
            identifier=result.json()["jobs"][0]["id"]
            response=client.post(f"/api/jobs/{identifier}/apply",headers=headers,json={"tag_ids":[1],"new_tag_indices":[0],"title":"Reviewed title"})
            self.assertEqual(response.status_code,200)
            self.assertEqual(client.post(f"/api/jobs/{identifier}/apply",headers=headers,json={}).status_code,400)
            self.service.step()
            self.assertEqual(client.get("/api/state").json()["jobs"][0]["status"],"applied")
            self.assertEqual(client.post("/api/logout",headers=headers,json={}).status_code,200)
            self.assertEqual(client.get("/api/state").status_code,401)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.settings=Settings("https://paperless.example","test-token","test-key",Path("unused"))

    def test_pagination_cannot_send_token_to_external_hostname(self):
        seen=[]
        def handler(request):
            seen.append(request)
            return httpx.Response(200,json={"results":[{"id":len(seen)}],"next":"https://evil.example/api/tags/?page=2" if len(seen)==1 else None})
        with httpx.Client(base_url=self.settings.paperless_url,transport=httpx.MockTransport(handler)) as client:
            self.assertEqual(len(Paperless(self.settings,client).all("tags")),2)
        self.assertTrue(all(r.url.host=="paperless.example" for r in seen))
        self.assertTrue(all(r.headers["authorization"]=="Token test-token" for r in seen))

    def test_upstream_error_body_is_not_exposed(self):
        with httpx.Client(base_url=self.settings.paperless_url,transport=httpx.MockTransport(lambda r:httpx.Response(401,text="SECRET document text"))) as client:
            with self.assertRaises(AppError) as error:Paperless(self.settings,client).document(1)
        self.assertEqual(error.exception.code,"paperless_http")
        self.assertNotIn("SECRET",str(error.exception))

    def test_tag_write_is_additive_and_patch_fields_are_restricted(self):
        seen=[]
        def handler(request):
            seen.append(json.loads(request.content));return httpx.Response(200,json={"task_id":"test"})
        with httpx.Client(base_url=self.settings.paperless_url,transport=httpx.MockTransport(handler)) as client:
            paperless=Paperless(self.settings,client)
            paperless.add_tags(1,[2,2])
            with self.assertRaises(AppError):paperless.patch(1,{"tags":[]})
        self.assertEqual(seen,[{"documents":[1],"method":"modify_tags","parameters":{"add_tags":[2],"remove_tags":[]}}])

    def test_download_limit_is_enforced(self):
        settings=replace(self.settings,max_file_bytes=3)
        with httpx.Client(base_url=settings.paperless_url,transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b"1234"))) as client:
            with self.assertRaises(AppError) as error:Paperless(settings,client).file(1)
        self.assertEqual(error.exception.code,"file_too_large")

    def test_invalid_provider_answers_fail_closed(self):
        valid={"answers":{"tag_1":{"type":"noul","noul":.8}},"model":"test","usage":{"input_tokens":10,"output_tokens":1}}
        cases=[{}, {**valid,"answers":{}}, {**valid,"answers":{"tag_1":{"type":"noul","noul":float("nan")}}}, {**valid,"answers":{"tag_1":{"type":"noul","noul":True}}}, {**valid,"usage":{"input_tokens":-1,"output_tokens":1}}]
        for raw in cases:
            with self.subTest(raw=raw):
                client=Mock();client.system_one.return_value=raw
                with self.assertRaises(AppError) as error:Jev(self.settings,client).classify(TEXT,{"tags":[{"id":1,"name":"test"}],"types":[]},[])
                self.assertEqual(error.exception.code,"jev_failed")

    def test_empty_or_large_inputs_never_call_jev(self):
        client=Mock()
        for text in ("", "a"*60001, "😀"*30000):
            with self.assertRaises(AppError):Jev(self.settings,client).classify(text,{"tags":[{"id":1,"name":"test"}],"types":[]},[])
        client.system_one.assert_not_called()

    def test_new_tags_require_verbatim_evidence_and_deduplicate_names(self):
        result={"title":" Title ","new_tags":[NEW_TAG,{**NEW_TAG,"name":"SOLAR ENERGY"},{**NEW_TAG,"name":"finance"},{**NEW_TAG,"name":"classifier-queue"},{**NEW_TAG,"name":"fiction","evidence":"not in the document"}]}
        clean=clean_suggestions(result,{"tags":[{"name":"Finance"}]},TEXT)
        self.assertEqual(clean,{"title":"Title","new_tags":[NEW_TAG]})

    def test_vision_renders_all_frames_and_rejects_over_limit(self):
        images=[Image.new("RGB",(20,20),color=color) for color in ("red","blue")]
        output=BytesIO();images[0].save(output,format="TIFF",save_all=True,append_images=images[1:])
        self.assertEqual(len(render_pages(output.getvalue(),"image/tiff",self.settings)),2)
        with self.assertRaises(AppError) as error:render_pages(output.getvalue(),"image/tiff",replace(self.settings,max_pages=1))
        self.assertEqual(error.exception.code,"page_limit")

    def test_generative_incomplete_is_not_a_successful_empty_result(self):
        client=Mock()
        client.responses.with_raw_response.parse.return_value.http_response.json.return_value={"status":"incomplete"}
        with self.assertRaises(AppError) as error:Generative(self.settings,client).enrich(TEXT,{"tags":[]})
        self.assertEqual(error.exception.code,"generative_incomplete")


if __name__=="__main__":unittest.main()
