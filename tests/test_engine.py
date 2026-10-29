import pathlib
import shutil
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import main


def test_detect_python():
    result = main.detect_language("def add(a, b):\n    return a + b\nprint(add(1, 2))")
    assert result["language"] == "python"
    assert result["confidence"] >= 0.70


def test_detect_javascript():
    assert main.detect_language("const answer = 42;\nconsole.log(answer);")["language"] == "javascript"


def test_detect_typescript():
    assert main.detect_language("const answer: number = 42;\nconsole.log(answer);")["language"] == "typescript"


def test_detect_go():
    code = 'package main\nimport "fmt"\nfunc main() { fmt.Println("ok") }'
    assert main.detect_language(code)["language"] == "go"


def test_detect_java():
    code = 'public class Main { public static void main(String[] args) { System.out.println("ok"); } }'
    assert main.detect_language(code)["language"] == "java"


def test_detect_c():
    assert main.detect_language('#include <stdio.h>\nint main(void) { printf("ok"); }')["language"] == "c"


def test_detect_cpp():
    assert main.detect_language('#include <iostream>\nint main() { std::cout << "ok"; }')["language"] == "cpp"


def test_ambiguous_short_code_is_unknown():
    assert main.detect_language("hello")["language"] == "unknown"


def test_unknown_runtime_fails_cleanly():
    ok, output = main.execute_in_sandbox("print('x')", "brainfuck")
    assert not ok and "Unsupported" in output


def test_python_smoke_execution():
    ok, output = main.execute_in_sandbox("print('SRE_OK')", "python")
    assert ok and output == "SRE_OK"


def test_python_runtime_error_fails():
    ok, output = main.execute_in_sandbox("print(1 / 0)", "python")
    assert not ok and "ZeroDivisionError" in output


def test_python_timeout_is_reported(monkeypatch):
    def timeout(*args, **kwargs):
        raise main.subprocess.TimeoutExpired(cmd="python3", timeout=10)
    monkeypatch.setattr(main.subprocess, "run", timeout)
    ok, output = main.execute_in_sandbox("print('never')", "python")
    assert not ok
    assert "timed out" in output.lower()


def test_tester_expected_output_passes(monkeypatch):
    monkeypatch.setattr(main, "execute_in_sandbox", lambda code, lang: (True, "42"))
    state = {"current_patch": "print(42)", "language": "python", "expected_output": "42", "test_output": "", "verification_note": "", "retries": 0, "status": "TRIAGING"}
    result = main.tester_node(state)
    assert result["status"] == "RESOLVED"
    assert "assertion passed" in result["verification_note"]
    assert result["retries"] == 1


def test_tester_expected_output_mismatch_fails(monkeypatch):
    monkeypatch.setattr(main, "execute_in_sandbox", lambda code, lang: (True, "41"))
    state = {"current_patch": "print(41)", "language": "python", "expected_output": "42", "test_output": "", "verification_note": "", "retries": 0, "status": "TRIAGING"}
    result = main.tester_node(state)
    assert result["status"] == "FAILED"
    assert "Expected-output assertion failed" in result["test_output"]


def test_health_endpoint():
    from fastapi.testclient import TestClient
    response = TestClient(main.app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_detect_language_endpoint():
    from fastapi.testclient import TestClient
    response = TestClient(main.app).post("/detect-language", json={"broken_code": "print(1)"})
    assert response.status_code == 200
    assert response.json()["language"] == "python"


def test_missing_api_key_returns_503(monkeypatch):
    monkeypatch.setattr(main, "GROQ_KEYS", [])
    monkeypatch.setattr(main, "GEMINI_API_KEY", None)
    
    from fastapi.testclient import TestClient
    response = TestClient(main.app).post("/triage", json={"language": "python", "broken_code": "print(1)", "error_log": "test error"})
    assert response.status_code == 503
    assert "AI API Keys" in response.json()["detail"]


@pytest.mark.parametrize(
    "language,code,expected",
    [
        ("javascript", "console.log('JS_OK');", "JS_OK"),
        ("typescript", "const message: string = 'TS_OK';\nconsole.log(message);", "TS_OK"),
        ("go", 'package main\nimport "fmt"\nfunc main() { fmt.Println("GO_OK") }', "GO_OK"),
        ("java", 'public class Main { public static void main(String[] args) { System.out.println("JAVA_OK"); } }', "JAVA_OK"),
        ("c", '#include <stdio.h>\nint main(void) { puts("C_OK"); return 0; }', "C_OK"),
        ("cpp", '#include <iostream>\nint main() { std::cout << "CPP_OK\\n"; return 0; }', "CPP_OK"),
    ],
)
def test_supported_language_smoke_execution(language, code, expected):
    runtimes = {
        "javascript": ["node"], "typescript": ["node", "tsc"], "go": ["go"],
        "java": ["java", "javac"], "c": ["gcc"], "cpp": ["g++"],
    }
    if language in runtimes:
        if any(shutil.which(command) is None for command in runtimes[language]):
            pytest.skip(f"Required runtime for {language} is not installed")
            
    ok, output = main.execute_in_sandbox(code, language)
    assert ok, output
    assert output.strip() == expected