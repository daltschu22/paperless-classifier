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
                page=browser.new_page(viewport={"width":1440,"height":1000})
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
                page.locator('input[name="new-tag"]').check()
                page.locator("#proposal-title").fill("Reviewed solar invoice")
                page.get_by_role("button",name="Apply selected changes").click()
                page.locator('[data-view="history"]').click()
                expect(page.locator("#history-list .badge.applied")).to_be_visible(timeout=20000)
                assert paperless.doc["title"]=="Reviewed solar invoice"
                assert set(paperless.doc["tags"])=={1,2,3,4}
                page.locator('[data-view="settings"]').click()
                page.locator("#definition-text").fill("Household finance documents")
                page.get_by_role("button",name="Save definition").click()
                expect(page.locator("#notice")).to_have_text("Tag definition saved for future classifications.")
                page.get_by_role("button",name="Pause processing").click()
                expect(page.locator("#paused-banner")).to_be_visible()
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
                assert not errors,errors
                browser.close()
                print("Browser smoke passed: login, queue, review, new-tag approval, apply, history, definitions, pause, mobile layout, queued/failed document names after reload; no page errors.")
        finally:
            server.should_exit=True;thread.join(10)


if __name__=="__main__":main()
