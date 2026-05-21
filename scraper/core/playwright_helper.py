"""
Playwright 브라우저 컨텍스트 관리 모듈.
JS 렌더링이 필요한 상세 페이지 수집에 사용한다.

사용 방법:
    with PlaywrightBrowser() as browser:
        html = browser.get_html("https://example.com")
"""

import logging
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


class PlaywrightBrowser:
    """스크래퍼 1회 실행 동안 유지되는 Chromium 브라우저 인스턴스."""

    def __init__(self, headless: bool = True, timeout: int = 30_000):
        self._headless = headless
        self._timeout = timeout
        self._pw = None
        self._browser = None
        self._ctx = None

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._ctx = self._browser.new_context(
            user_agent=_UA,
            locale="ko-KR",
        )
        self._ctx.set_default_timeout(self._timeout)
        return self

    def __exit__(self, *_):
        for obj, method in [
            (self._ctx, "close"),
            (self._browser, "close"),
            (self._pw, "stop"),
        ]:
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception as exc:
                    logger.debug("PlaywrightBrowser 정리 중 오류: %s", exc)

    def get_html(self, url: str, wait_until: str = "networkidle") -> str:
        """URL을 탐색하고 JS 렌더링 완료 후 HTML을 반환한다."""
        page = self._ctx.new_page()
        try:
            page.goto(url, wait_until=wait_until)
            return page.content()
        except Exception as exc:
            logger.warning("[Playwright] get_html 실패 %s: %s", url, exc)
            return ""
        finally:
            page.close()

    def get_frame_html(self, url: str, frame_url_fragment: str) -> str:
        """
        페이지를 탐색한 뒤 URL에 fragment가 포함된 frame의 HTML을 반환한다.
        frame을 찾지 못하면 메인 페이지 HTML을 반환한다.
        """
        page = self._ctx.new_page()
        try:
            page.goto(url, wait_until="networkidle")
            for frame in page.frames():
                if frame_url_fragment in (frame.url or ""):
                    return frame.content()
            return page.content()
        except Exception as exc:
            logger.warning("[Playwright] get_frame_html 실패 %s: %s", url, exc)
            return ""
        finally:
            page.close()

    def post_html(self, url: str, form_data: dict) -> str:
        """
        JavaScript form submit으로 POST 요청을 보낸 뒤 응답 HTML을 반환한다.
        ETRI 팝업 상세 페이지 수집에 사용된다.
        """
        page = self._ctx.new_page()
        try:
            fields = "".join(
                f'<input type="hidden" name="{k}" value="{v}">'
                for k, v in form_data.items()
            )
            page.set_content(
                f'<form id="f" method="post" action="{url}" accept-charset="euc-kr">'
                f"{fields}</form>"
                f"<script>document.getElementById('f').submit();</script>"
            )
            page.wait_for_load_state("networkidle")
            return page.content()
        except Exception as exc:
            logger.warning("[Playwright] post_html 실패 %s: %s", url, exc)
            return ""
        finally:
            page.close()

    def sync_cookies_to_session(self, session) -> None:
        """Playwright 컨텍스트 쿠키를 requests.Session에 복사한다."""
        for cookie in self._ctx.cookies():
            session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain", ""),
            )
