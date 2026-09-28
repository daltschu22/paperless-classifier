#!/usr/bin/env python3
"""Exercise a real browser against synthetic Paperless/providers; no live writes."""
import argparse
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import uvicorn
from playwright.sync_api import sync_playwright, expect
from classifier.config import Settings
from classifier.service import Service
from classifier.store import Store
from classifier.web import create_app
from test_application import FakeGenerative, FakeJev, FakePaperless


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots",type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        listener=socket.socket();listener.bind(("127.0.0.1",0));port=listener.getsockname()[1];listener.close()
        origin=f"http://127.0.0.1:{port}"
        settings=Settings("https://paperless.example","test-paperless-token","test-key",Path(directory),origin=origin,openai_key="synthetic")
        paperless=FakePaperless()
        service=Service(settings,Store(directory),paperless,FakeJev(),FakeGenerative())
        server=uvicorn.Server(uvicorn.Config(create_app(settings,service),host="127.0.0.1",port=port,log_level="warning"))
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(.1)
            else:raise RuntimeError("Test server did not start")
            with sync_playwright() as p:
                browser=p.chromium.launch()
                context=browser.new_context(viewport={"width":1440,"height":1000})
                page=context.new_page()
                errors=[];page.on("pageerror",lambda error:errors.append(str(error)))
                page.goto(origin)
                page.get_by_label("Username").fill("owner")
                page.get_by_label("Password",exact=True).fill("pass")
                page.get_by_role("button",name="Sign in",exact=True).click()
                expect(page.get_by_role("heading",name="Your documents")).to_be_visible()
                expect(page.locator("#documents-body tr")).to_have_count(1)
                page.locator("#select-all").check()
                page.get_by_role("button",name="Classify selected").click()
                page.get_by_role("button",name="Review proposal →").click(timeout=20000)
                expect(page.locator('input[name="new-tag"]')).not_to_be_checked()
                expect(page.locator("#proposal-title")).to_have_value("Solar installation invoice")
                if args.screenshots:
                    args.screenshots.mkdir(parents=True,exist_ok=True)
                    page.screenshot(path=str(args.screenshots/"review-desktop.png"),full_page=True)
                page.set_viewport_size({"width":390,"height":844})
                if args.screenshots:page.screenshot(path=str(args.screenshots/"review-mobile.png"),full_page=True)
                self_overflow=page.evaluate("document.documentElement.scrollWidth > innerWidth")
                assert not self_overflow,"Mobile page overflows viewport"
                if args.screenshots:
                    page.locator('.new-tag').first.scroll_into_view_if_needed()
                    page.screenshot(path=str(args.screenshots/'subjects-mobile.png'),full_page=True)
                page.locator('input[name="new-tag"]').check()
                page.locator('[data-subject-name="0"]').fill("Residential Solar")
                page.locator("#proposal-title").fill("Reviewed solar invoice")
                page.get_by_role("button",name="Apply selected changes").click()
                page.locator('[data-view="history"]').click()
                expect(page.locator("#history-list .badge.applied")).to_be_visible(timeout=20000)
                assert paperless.doc["title"]=="Reviewed solar invoice"
                assert set(paperless.doc["tags"])=={1,2,3,4}
                assert paperless.tags[-1]['name']=="residential-solar"
                page.locator('[data-view="settings"]').click()
                page.locator("#definition-text").fill("Household finance documents")
                page.get_by_role("button",name="Save definition").click()
                expect(page.locator("#notice")).to_have_text("Tag definition saved for future classifications.")
                page.get_by_role("button",name="Pause processing").click()
                expect(page.locator("#paused-banner")).to_be_visible()

                # Keep one review open while a second tab regenerates the job.
                # Polling must not replace the revision bound to the open form.
                review,_=service.store.enqueue(1,{"enrich":True,"vision_fallback":True,"force_vision":False})
                service.step()
                page.reload()
                expect(page.locator('#documents-body input[data-document="1"]')).to_be_visible()
                page.locator('[data-view="review"]').click()
                page.locator(f'#review-list [data-open="{review["id"]}"]').click()
                expect(page.locator('[data-subject-name="0"]')).to_have_value("solar-energy")
                discovery=service.generative.discover

                def replacement(text):
                    result,usage=discovery(text)
                    result['subjects']=[{"name":"home-battery","definition":"Home electricity storage.","evidence":"home battery"}]
                    return result,usage

                service.generative.discover=replacement
                other=page.context.new_page()
                other.goto(origin)
                expect(other.locator('#documents-body input[data-document="1"]')).to_be_visible()
                other.evaluate('(id) => api(`/api/jobs/${id}/retry`, {force_vision:true})',review['id'])
                service.step()
                page.evaluate('refresh()')
                page.locator('input[name="new-tag"]').check()
                page.get_by_role('button',name='Apply selected changes').click()
                expect(page.locator('#dialog-message')).to_contain_text('This proposal changed')
                assert service.store.get(review['id'])['status']=='review'
                assert service.store.get(review['id'])['approval'] is None
                page.locator('#close-dialog').click()
                page.locator(f'#review-list [data-open="{review["id"]}"]').click()
                expect(page.locator('[data-subject-name="0"]')).to_have_value('home-battery')
                expect(page.locator('input[name="new-tag"]')).not_to_be_checked()
                page.locator('input[name="new-tag"]').check()
                page.locator('[data-subject-target="0"]').select_option('2')
                expect(page.locator('[data-subject-name="0"]')).to_be_disabled()
                creates=sum(w[0]=='create_tag' for w in paperless.writes)
                page.get_by_role('button',name='Apply selected changes').click()
                expect(page.locator('#review-dialog')).not_to_be_visible()
                service.step()
                applied=service.store.get(review['id'])
                assert applied['status']=='applied'
                assert applied['approval']['selected_new_tags']==[]
                assert 2 in applied['approval']['tag_ids']
                assert sum(w[0]=='create_tag' for w in paperless.writes)==creates
                service.generative.discover=discovery
                other.close()

                title="Insurance <summary> & coverage"
                paperless.doc["title"]=title
                failed,_=service.store.enqueue(73,{"enrich":True,"vision_fallback":True,"force_vision":False})
                service.store.change(failed["id"],["queued"],"error",error_code="generative_filtered",error="Review the original.")
                queued,_=service.store.enqueue(74,{"enrich":True,"vision_fallback":True,"force_vision":False})
                page.reload()
                expect(page.locator('#documents-body input[data-document="1"]')).to_be_visible()
                page.locator('[data-view="review"]').click()
                for job in (failed,queued):
                    card=page.locator("#review-list article").filter(has=page.locator(f'[data-open="{job["id"]}"]'))
                    expect(card.locator("h3")).to_have_text(title)
                    expect(card.locator("h3 summary")).to_have_count(0)
                page.locator(f'[data-open="{failed["id"]}"]').click()
                expect(page.locator("#review-title")).to_have_text(title)
                page.locator("#close-dialog").click()
                expect(page.locator("#review-count")).to_have_text("2")
                expect(page.locator("#pending-count")).to_have_text("0")
                writes=list(paperless.writes)
                for remaining,job in zip((1,0),(failed,queued)):
                    page.locator(f'[data-remove="{job["id"]}"]').click()
                    expect(page.locator(f'#review-list [data-open="{job["id"]}"]')).to_have_count(0)
                    expect(page.locator("#review-count")).to_have_text(str(remaining))
                    expect(page.locator("#notice")).to_contain_text("Removed from queue")
                    assert service.store.get(job["id"])["status"]=="rejected"
                page.locator('[data-view="history"]').click()
                expect(page.locator("#history-list .badge.rejected")).to_have_count(2)
                assert paperless.writes==writes
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"),"Queue actions overflow mobile viewport"
                assert not errors,errors
                browser.close()
                print("Browser smoke passed: login, queue, review, new-tag renaming, existing-tag reuse, stale approval across tabs, apply, history, definitions, pause, mobile layout, document names, queue removal and counts; no page errors.")
        finally:
            server.should_exit=True;thread.join(10)


if __name__=="__main__":main()
