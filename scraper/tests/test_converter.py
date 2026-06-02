"""
converter.py 독립 검증 스크립트 (ADR-004 1단계)

실행:  python -m pytest scraper/tests/test_converter.py -v   (프로젝트 루트에서)
       또는: python scraper/tests/test_converter.py          (직접 실행)
"""

import logging
import os
import sys
import threading
import time
from pathlib import Path

# ── 프로젝트 루트를 sys.path에 추가 ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scraper"))

from core.converter import convert_to_pdf, convert_files, _check_win32com

# ── 로깅 설정 ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_converter")

# ── 테스트에 사용할 실제 파일 ────────────────────────────────────────────────
OUTPUT_DIR = PROJECT_ROOT / "scraper" / "output"

# 각 2개씩 고정
HWP_FILES = [
    OUTPUT_DIR / "NIA" / "29454" / "[사전규격공개]_제안요청서_글로벌_AI·디지털_규범_네트워크_구축(한-싱가포르_국제_공동연구).hwp",
    OUTPUT_DIR / "NIA" / "29455" / "(제안요청서)인공지능_동향_조사_및_분석_기반_용어집_제작.hwp",
]
HWPX_FILES = [
    OUTPUT_DIR / "NIA" / "29457" / "1._공모공고서(NIA2026-060).hwpx",
    OUTPUT_DIR / "NIA" / "29457" / "2._공모안내서(NIA2026-060).hwpx",
]

# 임시 PDF 저장 폴더
TEMP_DIR = PROJECT_ROOT / "scraper" / "tests" / "_converter_test_output"

# ── 결과 집계 ────────────────────────────────────────────────────────────────
_results: list[tuple[str, bool, str]] = []  # (test_name, passed, detail)


def record(name: str, passed: bool, detail: str = "") -> bool:
    status = "PASS" if passed else "FAIL"
    _results.append((name, passed, detail))
    print(f"  [{status}] {name}" + (f" - {detail}" if detail else ""))
    return passed


def pdf_valid(path: Path) -> tuple[bool, str]:
    """파일이 존재하고 크기>0이며 %PDF- 시그니처를 가지는지 검사."""
    if not path.exists():
        return False, "파일 없음"
    size = path.stat().st_size
    if size == 0:
        return False, "크기=0"
    with path.open("rb") as f:
        header = f.read(5)
    if header != b"%PDF-":
        return False, f"헤더={header!r}"
    return True, f"{size / 1024:.1f} KB, 헤더=b'%PDF-'"


# ════════════════════════════════════════════════════════════════════════════
# 섹션 1: 정적 검증 (코드 읽기)
# ════════════════════════════════════════════════════════════════════════════

def test_static_extension_routing():
    """convert_to_pdf: .pdf/.hwp/.hwpx/.docx 분기 코드가 존재하는지 소스로 확인."""
    src = PROJECT_ROOT / "scraper" / "core" / "converter.py"
    code = src.read_text(encoding="utf-8")

    # PDF 통과 분기
    has_pdf_passthrough = 'ext == ".pdf"' in code or "ext==\".pdf\"" in code
    record("정적/PDF-통과-분기", has_pdf_passthrough, ".pdf 패스스루 분기 확인")

    # HWP/HWPX 처리 분기
    has_hwp = '".hwp"' in code and '".hwpx"' in code
    record("정적/HWP-HWPX-분기", has_hwp, ".hwp/.hwpx 처리 분기 확인")

    # 지원 외 형식 None 반환
    has_none_return = "return None" in code
    record("정적/미지원형식-None반환", has_none_return, "None 반환 코드 존재")

    # dest=None 시 동일 폴더 .pdf
    has_same_dir = 'with_suffix(".pdf")' in code
    record("정적/dest-미지정-동일폴더", has_same_dir, "src.with_suffix('.pdf') 패턴 확인")

    # 보안 모듈 등록
    has_security = 'RegisterModule("FilePathCheckDLL"' in code
    record("정적/보안모듈-등록", has_security, "RegisterModule FilePathCheckDLL 확인")

    # COM 스레드 처리
    has_coinit = "CoInitialize" in code and "CoUninitialize" in code
    record("정적/COM-CoInitialize", has_coinit, "CoInitialize/CoUninitialize 코드 존재")

    # try/finally 리소스 정리
    has_finally = "finally:" in code
    record("정적/try-finally", has_finally, "finally 블록 존재")

    # hwp.Quit() 정리
    has_quit = "hwp.Quit()" in code
    record("정적/hwp-Quit", has_quit, "hwp.Quit() 호출 확인")

    # 예외 캐치 후 None 반환 (중단 안 함)
    has_except_none = "except Exception" in code and "return None" in code
    record("정적/예외시-None-반환", has_except_none, "예외 캐치 후 None 반환 패턴 존재")

    # convert_files 반환값 dict 타입
    has_dict_return = "results[path]" in code
    record("정적/convert_files-dict-반환", has_dict_return, "results dict 매핑 패턴 확인")


# ════════════════════════════════════════════════════════════════════════════
# 섹션 2: 동작 검증 (실제 실행)
# ════════════════════════════════════════════════════════════════════════════

def test_win32com_available():
    """pywin32 패키지 사용 가능 여부 확인."""
    available = _check_win32com()
    record("동작/win32com-사용가능", available, "pywin32 import 성공" if available else "pywin32 미설치")
    return available


def test_hwp_conversion():
    """HWP 파일 2개 실제 변환 검증."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    for hwp in HWP_FILES:
        if not hwp.exists():
            record(f"동작/HWP-변환/{hwp.name}", False, "원본 파일 없음")
            continue
        dest = TEMP_DIR / (hwp.stem + "_test.pdf")
        if dest.exists():
            dest.unlink()

        result = convert_to_pdf(str(hwp), str(dest))

        if result is None:
            record(f"동작/HWP-변환/{hwp.name}", False, "convert_to_pdf 반환 None")
            continue

        ok, detail = pdf_valid(Path(result))
        record(f"동작/HWP-변환/{hwp.name}", ok, detail)


def test_hwpx_conversion():
    """HWPX 파일 2개 실제 변환 검증."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    for hwpx in HWPX_FILES:
        if not hwpx.exists():
            record(f"동작/HWPX-변환/{hwpx.name}", False, "원본 파일 없음")
            continue
        dest = TEMP_DIR / (hwpx.stem + "_test.pdf")
        if dest.exists():
            dest.unlink()

        result = convert_to_pdf(str(hwpx), str(dest))

        if result is None:
            record(f"동작/HWPX-변환/{hwpx.name}", False, "convert_to_pdf 반환 None")
            continue

        ok, detail = pdf_valid(Path(result))
        record(f"동작/HWPX-변환/{hwpx.name}", ok, detail)


def test_pdf_passthrough():
    """이미 PDF인 입력 → 한글 없이 즉시 통과 검증."""
    # 더미 PDF 파일 생성
    dummy_pdf = TEMP_DIR / "dummy_input.pdf"
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy content for passthrough test")

    import win32com.client as _  # 임포트 여부 추적용
    # 실제로 한글이 열리지 않는지는 프로세스 수로 간접 확인
    import subprocess
    before = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Hwp.exe", "/NH"],
        capture_output=True, text=True
    ).stdout.strip()

    result = convert_to_pdf(str(dummy_pdf))

    after = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Hwp.exe", "/NH"],
        capture_output=True, text=True
    ).stdout.strip()

    passed = result == str(dummy_pdf) and before == after
    record(
        "동작/PDF-패스스루",
        passed,
        f"반환={result!r}, Hwp.exe 변화={'없음' if before == after else '증가(문제!)'}",
    )


def test_unsupported_format():
    """지원 외 형식(.docx) → None + 로그 검증."""
    dummy_docx = TEMP_DIR / "fake.docx"
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    dummy_docx.write_bytes(b"PK dummy docx")

    result = convert_to_pdf(str(dummy_docx))
    record("동작/미지원형식-None", result is None, f"반환={result!r}")


def test_nonexistent_path():
    """존재하지 않는 경로 → None + 크래시 없음."""
    fake_path = str(TEMP_DIR / "does_not_exist.hwp")
    try:
        result = convert_to_pdf(fake_path)
        # 파일이 없으면 한글이 열기 실패하거나 None 반환해야 함
        record(
            "견고성/존재하지않는경로",
            result is None,
            f"반환={result!r} (크래시 없음)"
        )
    except Exception as e:
        record("견고성/존재하지않는경로", False, f"예외 발생(크래시): {e}")


def test_background_thread_com():
    """백그라운드 스레드에서 COM 초기화가 정상 동작하는지 검증 (Flask 연동 선결 조건)."""
    hwp_file = None
    for f in HWP_FILES:
        if f.exists():
            hwp_file = f
            break
    if hwp_file is None:
        record("동작/백그라운드스레드-COM", False, "테스트 HWP 파일 없음")
        return

    dest = TEMP_DIR / (hwp_file.stem + "_bgthread.pdf")
    if dest.exists():
        dest.unlink()

    thread_result = [None]
    thread_error = [None]

    def worker():
        try:
            thread_result[0] = convert_to_pdf(str(hwp_file), str(dest))
        except Exception as e:
            thread_error[0] = e

    t = threading.Thread(target=worker, name="converter-bg-thread")
    t.start()
    t.join(timeout=120)  # HWP 변환은 최대 2분

    if t.is_alive():
        record("동작/백그라운드스레드-COM", False, "스레드 타임아웃(120s)")
        return

    if thread_error[0]:
        record("동작/백그라운드스레드-COM", False, f"스레드 예외: {thread_error[0]}")
        return

    if thread_result[0] is None:
        record("동작/백그라운드스레드-COM", False, "변환 결과 None (COM 초기화 실패 가능)")
        return

    ok, detail = pdf_valid(Path(thread_result[0]))
    record("동작/백그라운드스레드-COM", ok, f"백그라운드 스레드 변환 성공: {detail}")


def test_hwp_process_cleanup():
    """변환 후 Hwp.exe 좀비 프로세스가 남지 않는지 확인."""
    import subprocess

    # 변환 전 Hwp.exe 수
    def count_hwp():
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Hwp.exe", "/NH"],
            capture_output=True, text=True
        ).stdout
        lines = [l for l in out.splitlines() if "Hwp.exe" in l]
        return len(lines)

    hwp_file = None
    for f in HWP_FILES:
        if f.exists():
            hwp_file = f
            break
    if hwp_file is None:
        record("동작/Hwp.exe-정리", False, "테스트 HWP 파일 없음")
        return

    dest = TEMP_DIR / (hwp_file.stem + "_cleanup_test.pdf")
    if dest.exists():
        dest.unlink()

    before = count_hwp()
    convert_to_pdf(str(hwp_file), str(dest))
    time.sleep(2)  # COM 객체 해제 후 프로세스 종료 대기
    after = count_hwp()

    passed = after <= before
    record(
        "동작/Hwp.exe-정리",
        passed,
        f"변환 전={before}, 변환 후={after}" + (" (좀비 없음)" if passed else " (좀비 남음!)")
    )


def test_convert_files_batch():
    """convert_files: 여러 파일 일괄 변환 및 반환값 형식 검증."""
    files = [str(f) for f in HWP_FILES + HWPX_FILES if f.exists()]
    if not files:
        record("동작/convert_files-일괄변환", False, "테스트 파일 없음")
        return

    batch_dir = TEMP_DIR / "batch"
    batch_dir.mkdir(parents=True, exist_ok=True)

    results = convert_files(files, str(batch_dir))

    # 반환값이 dict인지 확인
    is_dict = isinstance(results, dict)
    record("동작/convert_files-dict형식", is_dict, f"타입={type(results).__name__}")

    # 키 수 일치
    keys_match = len(results) == len(files)
    record("동작/convert_files-키수", keys_match, f"입력={len(files)}, 결과키={len(results)}")

    # 각 결과 검증
    for src_path, pdf_path in results.items():
        name = Path(src_path).name
        if pdf_path is None:
            record(f"동작/convert_files/{name}", False, "None 반환")
        else:
            ok, detail = pdf_valid(Path(pdf_path))
            record(f"동작/convert_files/{name}", ok, detail)


# ════════════════════════════════════════════════════════════════════════════
# 실행 진입점
# ════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 70)
    print("  converter.py 검증 시작 (ADR-004 1단계)")
    print("=" * 70)

    print("\n[섹션 1] 정적 검증 (소스코드 분석)")
    print("-" * 50)
    test_static_extension_routing()

    print("\n[섹션 2-0] win32com 사용 가능 여부")
    print("-" * 50)
    available = test_win32com_available()

    print("\n[섹션 2-1] 동작: HWP 변환")
    print("-" * 50)
    test_hwp_conversion()

    print("\n[섹션 2-2] 동작: HWPX 변환")
    print("-" * 50)
    test_hwpx_conversion()

    print("\n[섹션 2-3] 동작: PDF 패스스루 (한글 미실행)")
    print("-" * 50)
    test_pdf_passthrough()

    print("\n[섹션 2-4] 동작: 미지원 형식 (.docx → None)")
    print("-" * 50)
    test_unsupported_format()

    print("\n[섹션 2-5] 동작: 백그라운드 스레드 COM 초기화")
    print("-" * 50)
    test_background_thread_com()

    print("\n[섹션 2-6] 동작: Hwp.exe 프로세스 정리")
    print("-" * 50)
    test_hwp_process_cleanup()

    print("\n[섹션 2-7] 동작: convert_files 일괄 변환")
    print("-" * 50)
    test_convert_files_batch()

    print("\n[섹션 3] 견고성")
    print("-" * 50)
    test_nonexistent_path()

    # ── 최종 집계 ─────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  최종 결과 요약")
    print("=" * 70)
    passed = [r for r in _results if r[1]]
    failed = [r for r in _results if not r[1]]

    for name, ok, detail in _results:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f"  ({detail})" if detail else ""))

    print(f"\n  총 {len(_results)}개 항목: PASS {len(passed)}, FAIL {len(failed)}")

    if failed:
        print("\n  --- 실패 항목 ---")
        for name, _, detail in failed:
            print(f"  - {name}: {detail}")

    print("=" * 70)
    return len(failed) == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
