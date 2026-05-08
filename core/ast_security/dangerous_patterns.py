"""
DangerousPatterns — complete threat pattern catalog for Nexus BNL AST Security Engine.

This module contains NO logic — only data structures.
Every detector imports from here to avoid pattern duplication.

Risk points are additive: each finding adds its risk value to the total.
BLACKLISTED score threshold: any single finding with blacklist=True → instant block.
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple


# ── Risk levels ────────────────────────────────────────────────────────────────

class RiskLevel:
    SAFE        = "SAFE"        # 0
    LOW         = "LOW"         # 1–20
    MEDIUM      = "MEDIUM"      # 21–50
    HIGH        = "HIGH"        # 51–75
    CRITICAL    = "CRITICAL"    # 76–90
    BLACKLISTED = "BLACKLISTED" # 91–100 or any blacklist=True finding

RISK_THRESHOLDS = {
    RiskLevel.SAFE:        (0,  0),
    RiskLevel.LOW:         (1,  20),
    RiskLevel.MEDIUM:      (21, 50),
    RiskLevel.HIGH:        (51, 75),
    RiskLevel.CRITICAL:    (76, 90),
    RiskLevel.BLACKLISTED: (91, 100),
}


@dataclass
class ThreatPattern:
    """A single detectable threat pattern."""
    id:           str
    category:     str
    name:         str
    description:  str
    risk_score:   int
    blacklisted:  bool = False
    confidence:   float = 1.0   # 0.0–1.0
    cwe:          Optional[str] = None  # CWE reference
    remediation:  str = ""


# ── Dangerous imports ──────────────────────────────────────────────────────────

DANGEROUS_IMPORTS: Dict[str, ThreatPattern] = {
    "ctypes": ThreatPattern(
        "IMP001", "import", "ctypes import",
        "Low-level C API access — can call arbitrary system functions",
        risk_score=30, cwe="CWE-676",
    ),
    "ctypes.windll": ThreatPattern(
        "IMP002", "import", "Windows API access via ctypes",
        "Direct Windows API call capability", risk_score=35,
    ),
    "socket": ThreatPattern(
        "IMP003", "import", "socket import",
        "Raw network socket access", risk_score=15,
    ),
    "subprocess": ThreatPattern(
        "IMP004", "import", "subprocess import",
        "Shell command execution capability", risk_score=25,
    ),
    "multiprocessing": ThreatPattern(
        "IMP005", "import", "multiprocessing import",
        "Process spawning capability", risk_score=15,
    ),
    "pickle": ThreatPattern(
        "IMP006", "import", "pickle import",
        "Arbitrary object deserialization — RCE risk", risk_score=40,
        blacklisted=False, cwe="CWE-502",
    ),
    "marshal": ThreatPattern(
        "IMP007", "import", "marshal import",
        "Python bytecode manipulation — often used in obfuscation",
        risk_score=45, cwe="CWE-502",
    ),
    "importlib": ThreatPattern(
        "IMP008", "import", "importlib import",
        "Dynamic module loading — can load arbitrary code",
        risk_score=25,
    ),
    "pty": ThreatPattern(
        "IMP009", "import", "pty import",
        "Pseudo-terminal — common in reverse shells",
        risk_score=50, blacklisted=False,
    ),
    "winreg": ThreatPattern(
        "IMP010", "import", "winreg import",
        "Windows Registry access — persistence mechanism",
        risk_score=45,
    ),
    "_winapi": ThreatPattern(
        "IMP011", "import", "_winapi import",
        "Internal Windows API — not for normal use",
        risk_score=40,
    ),
    "mmap": ThreatPattern(
        "IMP012", "import", "mmap import",
        "Memory mapping — can be used for shellcode injection",
        risk_score=30,
    ),
    "cffi": ThreatPattern(
        "IMP013", "import", "cffi import",
        "C Foreign Function Interface — arbitrary C code", risk_score=35,
    ),
    "cryptography": ThreatPattern(
        "IMP014", "import", "cryptography import",
        "Crypto library — common in ransomware", risk_score=10,
    ),
    "paramiko": ThreatPattern(
        "IMP015", "import", "paramiko import",
        "SSH client — exfiltration vector", risk_score=20,
    ),
    "ftplib": ThreatPattern(
        "IMP016", "import", "ftplib import",
        "FTP client — exfiltration vector", risk_score=20,
    ),
    "smtplib": ThreatPattern(
        "IMP017", "import", "smtplib import",
        "SMTP client — data exfiltration", risk_score=15,
    ),
    "pdb": ThreatPattern(
        "IMP018", "import", "pdb import",
        "Debugger — anti-analysis or debugging live processes",
        risk_score=10,
    ),
    "gc": ThreatPattern(
        "IMP019", "import", "gc import",
        "Garbage collector manipulation — anti-forensic technique",
        risk_score=15,
    ),
    "sys": ThreatPattern(
        "IMP020", "import", "sys import",
        "System access — commonly abused", risk_score=5,
    ),
}

# Modules that are ALWAYS dangerous in combination with other findings
HIGH_RISK_IMPORT_COMBOS: List[Tuple[FrozenSet[str], str, int]] = [
    (frozenset({"socket", "subprocess"}),  "reverse_shell_combo", 40),
    (frozenset({"socket", "pty"}),          "reverse_shell_pty",   60),
    (frozenset({"base64", "exec"}),         "obfuscated_exec",     50),
    (frozenset({"ctypes", "mmap"}),         "shellcode_injection",  65),
    (frozenset({"pickle", "socket"}),       "remote_pickle_exec",  55),
    (frozenset({"winreg", "subprocess"}),   "registry_persistence", 45),
    (frozenset({"cryptography", "socket"}), "ransomware_combo",     45),
]


# ── Dangerous function calls ───────────────────────────────────────────────────

DANGEROUS_CALLS: Dict[str, ThreatPattern] = {
    # Execution
    "eval":    ThreatPattern("CALL001", "execution", "eval()",
                             "Dynamic code execution", 50, cwe="CWE-95"),
    "exec":    ThreatPattern("CALL002", "execution", "exec()",
                             "Arbitrary code execution", 50, cwe="CWE-95"),
    "compile": ThreatPattern("CALL003", "execution", "compile()",
                             "Runtime code compilation", 35, cwe="CWE-95"),
    "__import__": ThreatPattern("CALL004", "execution", "__import__()",
                                "Dynamic import", 30),
    "execfile": ThreatPattern("CALL005", "execution", "execfile()",
                              "File execution (Python 2)", 45),
    # OS
    "os.system":  ThreatPattern("CALL010", "os",  "os.system()", "Shell execution", 50),
    "os.popen":   ThreatPattern("CALL011", "os",  "os.popen()",  "Shell pipe",      45),
    "os.execve":  ThreatPattern("CALL012", "os",  "os.execve()", "Process replace", 50),
    "os.execvp":  ThreatPattern("CALL013", "os",  "os.execvp()", "Process replace", 50),
    "os.execv":   ThreatPattern("CALL014", "os",  "os.execv()",  "Process replace", 50),
    "os.fork":    ThreatPattern("CALL015", "os",  "os.fork()",   "Fork process",    30),
    "os.unlink":  ThreatPattern("CALL016", "os",  "os.unlink()", "File delete",     15),
    "os.remove":  ThreatPattern("CALL017", "os",  "os.remove()", "File delete",     15),
    "os.rmdir":   ThreatPattern("CALL018", "os",  "os.rmdir()",  "Dir delete",      15),
    "shutil.rmtree": ThreatPattern("CALL019", "os", "shutil.rmtree()", "Recursive delete", 35),
    # Subprocess
    "subprocess.run":   ThreatPattern("CALL020", "subprocess", "subprocess.run()",   "Subprocess", 30),
    "subprocess.call":  ThreatPattern("CALL021", "subprocess", "subprocess.call()",  "Subprocess", 30),
    "subprocess.Popen": ThreatPattern("CALL022", "subprocess", "subprocess.Popen()", "Subprocess", 35),
    "subprocess.check_output": ThreatPattern("CALL023", "subprocess", "subprocess.check_output()", "Subprocess", 30),
    # Network
    "socket.connect":     ThreatPattern("CALL030", "network", "socket.connect()",     "Network connect", 25),
    "socket.sendall":     ThreatPattern("CALL031", "network", "socket.sendall()",     "Network send",    25),
    "requests.post":      ThreatPattern("CALL032", "network", "requests.post()",      "HTTP POST",       20),
    "requests.get":       ThreatPattern("CALL033", "network", "requests.get()",       "HTTP GET",        10),
    "urllib.request.urlopen": ThreatPattern("CALL034", "network", "urlopen()", "HTTP request", 15),
    # Deserialization
    "pickle.loads": ThreatPattern("CALL040", "deser", "pickle.loads()", "Pickle deserialization", 55,
                                  cwe="CWE-502"),
    "marshal.loads": ThreatPattern("CALL041", "deser", "marshal.loads()", "Marshal deserialization", 55),
    "yaml.load":     ThreatPattern("CALL042", "deser", "yaml.load()",    "Unsafe YAML load", 40),
    # Windows API
    "ctypes.windll.kernel32.VirtualAllocEx": ThreatPattern("CALL050", "winapi",
        "VirtualAllocEx", "Process memory allocation — injection", 80, blacklisted=True),
    "ctypes.windll.kernel32.WriteProcessMemory": ThreatPattern("CALL051", "winapi",
        "WriteProcessMemory", "Process memory write — injection", 85, blacklisted=True),
    "ctypes.windll.kernel32.CreateRemoteThread": ThreatPattern("CALL052", "winapi",
        "CreateRemoteThread", "Remote thread injection", 90, blacklisted=True),
    "ctypes.windll.advapi32.AdjustTokenPrivileges": ThreatPattern("CALL053", "winapi",
        "AdjustTokenPrivileges", "Privilege escalation via token", 80, blacklisted=True),
    # Privilege
    "os.setuid":  ThreatPattern("CALL060", "privilege", "os.setuid()",  "UID change", 40),
    "os.setgid":  ThreatPattern("CALL061", "privilege", "os.setgid()",  "GID change", 40),
    "os.setreuid": ThreatPattern("CALL062", "privilege", "os.setreuid()", "RUID change", 45),
}


# ── Obfuscation patterns (regex-based on source text) ─────────────────────────

import re

OBFUSCATION_REGEXES: List[Tuple[str, ThreatPattern]] = [
    (r"exec\s*\(\s*(base64|b64|decode|bytes)",
     ThreatPattern("OBF001", "obfuscation", "exec(base64())",
                   "Base64-encoded exec payload", 60)),
    (r"eval\s*\(\s*(base64|b64|decode)",
     ThreatPattern("OBF002", "obfuscation", "eval(base64())",
                   "Base64-encoded eval payload", 60)),
    (r"[A-Za-z0-9+/]{80,}={0,2}",
     ThreatPattern("OBF003", "obfuscation", "Long base64 string",
                   "Encoded payload detected", 20)),
    (r"\\x[0-9a-fA-F]{2}(\\x[0-9a-fA-F]{2}){15,}",
     ThreatPattern("OBF004", "obfuscation", "Hex-encoded payload",
                   "Long hex-encoded string", 30)),
    (r"marshal\.loads\s*\(\s*zlib\.decompress",
     ThreatPattern("OBF005", "obfuscation", "marshal+zlib payload",
                   "Compressed bytecode payload", 65, blacklisted=False)),
    (r'chr\(\d+\)(\s*\+\s*chr\(\d+\)){8,}',
     ThreatPattern("OBF006", "obfuscation", "chr() string construction",
                   "String built character by character", 35)),
    (r'__builtins__\s*\[',
     ThreatPattern("OBF007", "obfuscation", "__builtins__ access",
                   "Direct builtins manipulation", 40)),
    (r'getattr\s*\(\s*__builtins__',
     ThreatPattern("OBF008", "obfuscation", "getattr(__builtins__)",
                   "Dynamic builtin access", 40)),
    (r'compile\s*\(.*\bexec\b',
     ThreatPattern("OBF009", "obfuscation", "compile+exec chain",
                   "Compiled code execution", 55)),
    (r'lambda\s.*:\s*exec\s*\(',
     ThreatPattern("OBF010", "obfuscation", "lambda exec",
                   "exec inside lambda — obfuscation technique", 45)),
    (r'\bROT\d+\b|\brot13\b',
     ThreatPattern("OBF011", "obfuscation", "ROT encoding",
                   "ROT-encoded string detected", 20)),
]


# ── Persistence patterns ───────────────────────────────────────────────────────

PERSISTENCE_STRINGS: List[Tuple[str, ThreatPattern]] = [
    (r"(?i)(startup|autorun|autostart)",
     ThreatPattern("PER001", "persistence", "Startup directory reference",
                   "Writing to startup/autorun location", 40)),
    (r"(?i)(HKEY_CURRENT_USER|HKEY_LOCAL_MACHINE|Software\\Microsoft\\Windows\\CurrentVersion\\Run)",
     ThreatPattern("PER002", "persistence", "Registry Run key",
                   "Windows registry persistence mechanism", 55)),
    (r"(?i)(schtasks|Task Scheduler|at\.exe|crontab|cron\.d)",
     ThreatPattern("PER003", "persistence", "Scheduled task creation",
                   "Persistence via scheduled tasks", 50)),
    (r"(?i)(\.bashrc|\.bash_profile|\.zshrc|\.profile)",
     ThreatPattern("PER004", "persistence", "Shell profile modification",
                   "Persistence via shell profile", 40)),
    (r"(?i)(shutil\.copy.*__file__|copyfile.*sys\.argv)",
     ThreatPattern("PER005", "persistence", "Self-copy behavior",
                   "Script copying itself — worm-like behavior", 65,
                   blacklisted=False)),
    (r"(?i)(sc\s+create|sc\s+config|CreateService)",
     ThreatPattern("PER006", "persistence", "Service creation",
                   "Windows service installation", 55)),
    (r"(?i)(launchd|plist|LaunchDaemons|LaunchAgents)",
     ThreatPattern("PER007", "persistence", "macOS LaunchAgent",
                   "macOS persistence mechanism", 50)),
]


# ── Exfiltration patterns ──────────────────────────────────────────────────────

EXFILTRATION_STRINGS: List[Tuple[str, ThreatPattern]] = [
    (r"(?i)(os\.environ|environ\.get|getenv).*?(token|key|secret|password|api)",
     ThreatPattern("EXF001", "exfiltration", "Environment credential dump",
                   "Accessing env vars for credentials", 35)),
    (r"(?i)(\.ssh[/\\]|id_rsa|authorized_keys|known_hosts)",
     ThreatPattern("EXF002", "exfiltration", "SSH key access",
                   "Accessing SSH credentials", 60)),
    (r"(?i)(cookies|browser\s*data|chrome|firefox|saved\s*password)",
     ThreatPattern("EXF003", "exfiltration", "Browser credential theft",
                   "Accessing browser cookies/passwords", 70, blacklisted=False)),
    (r"(?i)(keylog|GetAsyncKeyState|keyboard\.on_press|pynput)",
     ThreatPattern("EXF004", "exfiltration", "Keylogger pattern",
                   "Keyboard input capture", 80, blacklisted=True)),
    (r"(?i)(screenshot|ImageGrab|PIL\.ImageGrab|mss\.mss)",
     ThreatPattern("EXF005", "exfiltration", "Screenshot capture",
                   "Screen capture for exfiltration", 45)),
    (r"(?i)(requests\.(post|put)|urllib.*open).*pass(word)?",
     ThreatPattern("EXF006", "exfiltration", "Credential POST",
                   "Sending credentials over network", 60)),
    (r"(?i)(smtplib.*sendmail|ftplib.*storb|paramiko.*exec_command)",
     ThreatPattern("EXF007", "exfiltration", "Data exfil via SMTP/FTP/SSH",
                   "Exfiltrating data via email/FTP/SSH", 65)),
]


# ── Reverse shell patterns ─────────────────────────────────────────────────────

REVERSE_SHELL_PATTERNS: List[Tuple[str, ThreatPattern]] = [
    (r"(?i)socket\.socket.*socket\.AF_INET.*SOCK_STREAM",
     ThreatPattern("RSH001", "revshell", "TCP socket setup",
                   "TCP socket creation (reverse shell setup)", 25)),
    (r"(?i)(dup2|os\.dup2).*\bstdin\b|\bstdout\b|\bstderr\b",
     ThreatPattern("RSH002", "revshell", "fd dup2 pattern",
                   "File descriptor duplication — classic reverse shell pattern",
                   70, blacklisted=True)),
    (r"(?i)pty\.spawn|pty\.openpty",
     ThreatPattern("RSH003", "revshell", "pty.spawn reverse shell",
                   "PTY spawn — reverse shell", 75, blacklisted=True)),
    (r"(?i)bash\s+-i|/bin/sh\s+-i|cmd\.exe\s*/k",
     ThreatPattern("RSH004", "revshell", "Interactive shell spawn",
                   "Interactive shell invocation", 70, blacklisted=True)),
    (r"(?i)(nc\s+-[le]|ncat\s+-[le]|netcat\s+-[le])",
     ThreatPattern("RSH005", "revshell", "netcat listener/connect",
                   "Netcat usage — possible reverse shell", 60)),
    (r"(?i)socket\.connect.*\(\s*\(.*\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
     ThreatPattern("RSH006", "revshell", "Hardcoded IP connect",
                   "Socket connecting to hardcoded IP", 40)),
]


# ── Ransomware patterns ────────────────────────────────────────────────────────

RANSOMWARE_PATTERNS: List[Tuple[str, ThreatPattern]] = [
    (r"(?i)(Fernet|AES|RSA).*encrypt.*open|open.*encrypt.*Fernet",
     ThreatPattern("RAN001", "ransomware", "File encryption loop",
                   "Encrypting files with crypto — ransomware pattern",
                   80, blacklisted=True)),
    (r"(?i)glob\.glob.*encrypt|os\.walk.*encrypt",
     ThreatPattern("RAN002", "ransomware", "Recursive file encryption",
                   "Walking and encrypting files", 85, blacklisted=True)),
    (r"(?i)(bitcoin|monero|ransom|decrypt.*payment|pay.*bitcoin)",
     ThreatPattern("RAN003", "ransomware", "Ransom note strings",
                   "Ransom message content detected", 80, blacklisted=True)),
    (r"(?i)os\.walk.*os\.remove|os\.walk.*os\.unlink",
     ThreatPattern("RAN004", "ransomware", "Recursive file deletion",
                   "Walking directories and deleting files", 70)),
]


# ── Taint sources and sinks ────────────────────────────────────────────────────

TAINT_SOURCES: FrozenSet[str] = frozenset({
    "input", "sys.stdin.read", "sys.argv", "os.environ",
    "os.getenv", "socket.recv", "socket.recvfrom",
    "requests.get", "requests.post", "urllib.request.urlopen",
    "open",   # reading files is a taint source
})

TAINT_SINKS: Dict[str, ThreatPattern] = {
    "eval":              ThreatPattern("TNT001", "taint", "eval(tainted)",
                                       "Tainted data flows into eval()", 65, blacklisted=False),
    "exec":              ThreatPattern("TNT002", "taint", "exec(tainted)",
                                       "Tainted data flows into exec()", 65, blacklisted=False),
    "subprocess.run":    ThreatPattern("TNT003", "taint", "subprocess.run(tainted)",
                                       "Tainted data in subprocess command", 55),
    "subprocess.Popen":  ThreatPattern("TNT004", "taint", "Popen(tainted)",
                                       "Tainted data in Popen command", 55),
    "os.system":         ThreatPattern("TNT005", "taint", "os.system(tainted)",
                                       "Tainted data in os.system", 60),
    "open":              ThreatPattern("TNT006", "taint", "open(tainted)",
                                       "Tainted path in open() — path traversal", 30),
    "pickle.loads":      ThreatPattern("TNT007", "taint", "pickle.loads(tainted)",
                                       "Tainted deserialization", 70, blacklisted=False),
    "requests.post":     ThreatPattern("TNT008", "taint", "requests.post(tainted)",
                                       "Tainted data sent to network", 35),
    "compile":           ThreatPattern("TNT009", "taint", "compile(tainted)",
                                       "Tainted code compilation", 55),
    "socket.sendall":    ThreatPattern("TNT010", "taint", "socket.sendall(tainted)",
                                       "Tainted data sent via socket", 40),
}
