import subprocess
import tempfile
import os
import sys
import re

def run_polyglot_sandbox(code_str: str, language: str = "python") -> dict:
    lang = language.lower().strip()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            if lang == "python":
                filepath = os.path.join(tmpdir, "script.py")
                with open(filepath, "w") as f:
                    f.write(code_str)
                # sys.executable Windows aur Linux dono par active python path uthata hai
                cmd = [sys.executable, filepath]

            elif lang in ["javascript", "nodejs", "node", "js"]:
                filepath = os.path.join(tmpdir, "script.js")
                with open(filepath, "w") as f:
                    f.write(code_str)
                cmd = ["node", filepath]

            elif lang == "c":
                filepath = os.path.join(tmpdir, "main.c")
                binpath = os.path.join(tmpdir, "main.exe" if os.name == "nt" else "main.out")
                with open(filepath, "w") as f:
                    f.write(code_str)
                comp = subprocess.run(["gcc", filepath, "-o", binpath], capture_output=True, text=True, timeout=5)
                if comp.returncode != 0:
                    return {"success": False, "output": None, "error": f"C Compilation Error:\n{comp.stderr.strip()}"}
                cmd = [binpath]

            elif lang in ["cpp", "c++"]:
                filepath = os.path.join(tmpdir, "main.cpp")
                binpath = os.path.join(tmpdir, "main.exe" if os.name == "nt" else "main.out")
                with open(filepath, "w") as f:
                    f.write(code_str)
                comp = subprocess.run(["g++", filepath, "-o", binpath], capture_output=True, text=True, timeout=5)
                if comp.returncode != 0:
                    return {"success": False, "output": None, "error": f"C++ Compilation Error:\n{comp.stderr.strip()}"}
                cmd = [binpath]

            elif lang == "go":
                filepath = os.path.join(tmpdir, "main.go")
                with open(filepath, "w") as f:
                    f.write(code_str)
                cmd = ["go", "run", filepath]

            elif lang == "java":
                match = re.search(r'public\s+class\s+([A-Za-z0-9_]+)', code_str)
                class_name = match.group(1) if match else "Main"
                filepath = os.path.join(tmpdir, f"{class_name}.java")
                with open(filepath, "w") as f:
                    f.write(code_str)
                comp = subprocess.run(["javac", filepath], cwd=tmpdir, capture_output=True, text=True, timeout=8)
                if comp.returncode != 0:
                    return {"success": False, "output": None, "error": f"Java Compilation Error:\n{comp.stderr.strip()}"}
                cmd = ["java", "-cp", tmpdir, class_name]

            else:
                return {"success": False, "output": None, "error": f"Unsupported language runtime: {language}"}

            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            if res.returncode == 0:
                return {"success": True, "output": res.stdout.strip(), "error": None}
            else:
                return {"success": False, "output": None, "error": res.stderr.strip() or f"Process exited with code {res.returncode}"}

        except subprocess.TimeoutExpired:
            return {"success": False, "output": None, "error": "Execution Timeout (5s limit exceeded)"}
        except Exception as e:
            return {"success": False, "output": None, "error": f"Runtime Exception: {str(e)}"}