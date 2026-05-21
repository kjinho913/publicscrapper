"""
공고 첨부파일 다운로드 모듈.
- Content-Disposition 헤더에서 한글 파일명을 추출한다.
- 허용 확장자 + 최대 파일 크기를 검사한다.
- 이미 존재하는 파일은 재다운로드하지 않는다.
"""

import logging
import re
import urllib.parse
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS_DEFAULT = {
    ".pdf", ".hwp", ".hwpx", ".docx", ".xlsx", ".zip", ".pptx"
}


def download_attachments(
    urls: list[str],
    dest_dir: Path,
    session: requests.Session,
    allowed_extensions: list[str] | None = None,
    max_mb: int = 50,
) -> int:
    """
    주어진 URL 목록에서 첨부파일을 다운로드한다.

    Args:
        urls: 다운로드할 파일 URL 리스트.
        dest_dir: 저장 대상 폴더 (없으면 자동 생성).
        session: 재사용할 requests.Session.
        allowed_extensions: 허용할 파일 확장자 집합 (None이면 기본값 사용).
        max_mb: 최대 파일 크기 (MB). 초과 시 건너뜀.

    Returns:
        실제 다운로드된 파일 수.
    """
    if allowed_extensions is not None:
        allowed_ext = {e.lower() for e in allowed_extensions}
    else:
        allowed_ext = _ALLOWED_EXTENSIONS_DEFAULT

    dest_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = max_mb * 1024 * 1024
    downloaded = 0

    for url in urls:
        try:
            downloaded += _download_one(url, dest_dir, session, allowed_ext, max_bytes)
        except Exception as exc:
            logger.warning("첨부파일 다운로드 실패 %s: %s", url, exc)

    return downloaded


def _download_one(
    url: str,
    dest_dir: Path,
    session: requests.Session,
    allowed_ext: set[str],
    max_bytes: int,
) -> int:
    """단일 파일을 다운로드. 성공 시 1, 건너뜀 시 0 반환."""
    resp = session.get(url, stream=True, timeout=60)
    resp.raise_for_status()

    filename = _extract_filename(resp, url)
    ext = Path(filename).suffix.lower()

    if ext not in allowed_ext:
        logger.debug("허용되지 않은 확장자, 건너뜀: %s", filename)
        return 0

    dest_path = dest_dir / filename
    if dest_path.exists():
        logger.debug("이미 존재, 건너뜀: %s", dest_path)
        return 0

    # 크기 제한 검사 (Content-Length 헤더가 있을 때)
    content_length = resp.headers.get("Content-Length")
    if content_length and int(content_length) > max_bytes:
        logger.warning(
            "파일 크기 초과(%s MB), 건너뜀: %s",
            int(content_length) // (1024 * 1024),
            filename,
        )
        return 0

    # 스트리밍 다운로드
    total_bytes = 0
    with dest_path.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    f.close()
                    dest_path.unlink(missing_ok=True)
                    logger.warning("다운로드 중 크기 초과, 취소: %s", filename)
                    return 0
                f.write(chunk)

    logger.info("다운로드 완료 (%.1f KB): %s", total_bytes / 1024, dest_path)
    return 1


def _extract_filename(resp: requests.Response, fallback_url: str) -> str:
    """
    응답 헤더의 Content-Disposition에서 파일명을 추출한다.
    실패 시 URL 끝에서 추출하고, 그래도 실패 시 'attachment' 반환.
    """
    cd = resp.headers.get("Content-Disposition", "")

    # RFC 5987 형식: filename*=UTF-8''%ED%8C%8C%EC%9D%BC%EB%AA%85.pdf
    m = re.search(r"filename\*\s*=\s*([^;]+)", cd, re.IGNORECASE)
    if m:
        raw = m.group(1).strip().strip("'\"")
        # UTF-8''<encoded> 또는 그냥 encoded 값
        if raw.lower().startswith("utf-8''"):
            raw = raw[7:]
        try:
            return urllib.parse.unquote(raw, encoding="utf-8")
        except Exception:
            pass

    # 일반 형식: filename="파일명.pdf" 또는 filename=파일명.pdf
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
        # EUC-KR로 인코딩된 경우 처리 시도
        try:
            return urllib.parse.unquote(raw, encoding="utf-8")
        except Exception:
            try:
                return raw.encode("latin-1").decode("euc-kr")
            except Exception:
                return raw

    # URL 끝에서 추출
    path_part = urllib.parse.urlparse(fallback_url).path
    name = urllib.parse.unquote(path_part.split("/")[-1])
    return name if name else "attachment"
