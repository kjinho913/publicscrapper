"""
HWP/HWPX → PDF 변환 모듈 (도메인: backend/data)

한컴 한글 COM 자동화(win32com)를 사용해 .hwp/.hwpx 파일을 PDF로 변환한다.
- 이미 PDF인 파일은 변환 없이 경로를 그대로 반환한다.
- 한글 미설치 환경에서는 None을 반환하고 프로그램을 중단하지 않는다.
- Flask 등 백그라운드 스레드에서 호출될 수 있어 COM 스레드 초기화를 처리한다.
"""

import logging
import shutil
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# 이 모듈이 로드될 때 win32com 사용 가능 여부를 판단한다.
# 미설치 환경에서 import 자체를 막지 않기 위해 지연 import 방식을 사용한다.
_WIN32COM_AVAILABLE: bool | None = None  # None = 아직 검사 전


def _check_win32com() -> bool:
    """win32com 패키지 및 한글 COM 객체 사용 가능 여부를 한 번만 검사한다."""
    global _WIN32COM_AVAILABLE
    if _WIN32COM_AVAILABLE is not None:
        return _WIN32COM_AVAILABLE

    try:
        import win32com.client  # noqa: F401
        import pythoncom  # noqa: F401
        _WIN32COM_AVAILABLE = True
    except ModuleNotFoundError:
        logger.warning("pywin32가 설치되지 않아 HWP→PDF 변환을 사용할 수 없습니다.")
        _WIN32COM_AVAILABLE = False

    return _WIN32COM_AVAILABLE


def convert_to_pdf(src_path: str, dest_path: str | None = None) -> str | None:
    """
    HWP/HWPX 파일을 PDF로 변환한다.

    이미 PDF이면 변환 없이 경로를 반환한다(dest_path 지정 시 복사 후 반환).
    .docx/.xlsx 등 지원 범위 밖 형식은 None을 반환한다(향후 확장 가능).

    Args:
        src_path: 원본 파일 경로 (절대/상대 모두 가능).
        dest_path: 저장할 PDF 경로. None이면 원본과 같은 폴더에 같은 이름으로 저장.

    Returns:
        변환(또는 통과)된 PDF 파일의 절대 경로 문자열, 실패 시 None.
    """
    src = Path(src_path).resolve()
    ext = src.suffix.lower()

    # ── 확장자 분기 ─────────────────────────────────────────────────────────
    if ext == ".pdf":
        return _passthrough_pdf(src, dest_path)

    if ext not in {".hwp", ".hwpx"}:
        logger.debug(
            "지원하지 않는 형식이라 변환을 건너뜁니다 (향후 확장 예정): %s", src.name
        )
        return None

    # ── 목적지 경로 결정 ─────────────────────────────────────────────────────
    dest = Path(dest_path).resolve() if dest_path else src.with_suffix(".pdf")

    # ── 이미 PDF가 존재하면 스킵 ─────────────────────────────────────────────
    if dest.exists() and dest.stat().st_size > 0:
        logger.debug("PDF가 이미 존재합니다, 스킵: %s", dest)
        return str(dest)

    # ── win32com 사용 가능 여부 확인 ──────────────────────────────────────────
    if not _check_win32com():
        return None

    return _convert_hwp_to_pdf(src, dest)


def convert_files(paths: list[str], dest_dir: str | None = None) -> dict:
    """
    여러 파일을 일괄 변환한다.

    Args:
        paths: 변환할 파일 경로 목록.
        dest_dir: 변환된 PDF를 저장할 폴더. None이면 각 파일의 원본 폴더에 저장.

    Returns:
        {원본경로: pdf경로 또는 None} 형태의 딕셔너리.
    """
    results: dict[str, str | None] = {}
    dest_dir_path = Path(dest_dir).resolve() if dest_dir else None

    for path in paths:
        src = Path(path).resolve()
        dest_path = None
        if dest_dir_path:
            dest_dir_path.mkdir(parents=True, exist_ok=True)
            dest_path = str(dest_dir_path / src.with_suffix(".pdf").name)

        results[path] = convert_to_pdf(str(src), dest_path)

    return results


# ── 내부 구현 ────────────────────────────────────────────────────────────────

def _passthrough_pdf(src: Path, dest_path: str | None) -> str:
    """이미 PDF인 파일을 처리한다. dest_path가 지정되면 복사한다."""
    if dest_path is None:
        return str(src)

    dest = Path(dest_path).resolve()
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        logger.debug("PDF 복사 완료: %s → %s", src, dest)

    return str(dest)


def _convert_hwp_to_pdf(src: Path, dest: Path) -> str | None:
    """
    한컴 한글 COM 객체를 사용해 HWP/HWPX를 PDF로 변환하는 실제 구현.

    COM은 스레드-어파인(thread-affine) 모델이므로, 메인 스레드가 아닌 경우
    CoInitialize/CoUninitialize를 직접 호출해야 한다.
    """
    import pythoncom
    import win32com.client

    # 메인 스레드 여부 판단: threading.main_thread()와 비교
    is_main_thread = threading.current_thread() is threading.main_thread()
    com_initialized = False

    hwp = None
    try:
        # 메인 스레드가 아니면 COM을 이 스레드에 초기화한다.
        if not is_main_thread:
            pythoncom.CoInitialize()
            com_initialized = True

        dest.parent.mkdir(parents=True, exist_ok=True)

        # 한글 COM 객체 생성 (gencache 없는 late-binding으로 호환성 확보)
        try:
            hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
        except Exception as e:
            logger.warning(
                "한글 COM 객체를 생성하지 못했습니다. 한글이 설치되어 있는지 확인하세요. 오류: %s", e
            )
            return None

        # 보안 모듈 등록 — 없으면 파일 열기 시 보안 팝업이 뜨며 자동화가 멈춤
        try:
            hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception as e:
            logger.debug("보안 모듈 등록 실패(무시 가능): %s", e)

        # 파일 열기
        opened = hwp.Open(str(src), "", "")
        if not opened:
            logger.warning("한글 파일 열기 실패: %s", src)
            return None

        # PDF로 저장
        hwp.SaveAs(str(dest), "PDF", "")

        # 저장 결과 검증: 파일이 생성되었고 크기가 0보다 커야 함
        if not dest.exists() or dest.stat().st_size == 0:
            logger.warning("PDF 변환 결과물이 비어 있거나 생성되지 않았습니다: %s", dest)
            if dest.exists():
                dest.unlink(missing_ok=True)
            return None

        # PDF 시그니처(%PDF-) 확인
        with dest.open("rb") as f:
            header = f.read(5)
        if header != b"%PDF-":
            logger.warning(
                "변환된 파일이 올바른 PDF 형식이 아닙니다 (헤더: %s): %s",
                header,
                dest,
            )
            dest.unlink(missing_ok=True)
            return None

        logger.info(
            "HWP→PDF 변환 성공 (%.1f KB): %s → %s",
            dest.stat().st_size / 1024,
            src.name,
            dest,
        )
        return str(dest)

    except Exception as e:
        logger.warning("HWP→PDF 변환 중 오류 (%s): %s", src.name, e)
        # 실패한 불완전 파일은 삭제
        if dest.exists():
            try:
                dest.unlink(missing_ok=True)
            except Exception:
                pass
        return None

    finally:
        # 한글 객체 정리 — 반드시 실행해 리소스 누수를 방지한다
        if hwp is not None:
            try:
                hwp.Clear(1)  # 1 = 저장 없이 닫기
            except Exception:
                pass
            try:
                hwp.Quit()
            except Exception:
                pass

        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
