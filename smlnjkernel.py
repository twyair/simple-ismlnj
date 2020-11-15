from typing import Dict, Optional, Any
import re
import signal

from ipykernel.kernelbase import Kernel
from ipykernel.kernelapp import IPKernelApp
import pexpect
from subprocess import check_output

crlf_pat = re.compile(r"[\r\n]+")
REGEX_WORD = re.compile(r"(\w+)$")
SML_KEYWORDS = sorted(
    [
        "fun",
        "true",
        "false",
        "orelse",
        "andalso",
        "if",
        "then",
        "else",
        "val",
        "let",
        "in",
        "end",
        "fn",
        "type",
        "datatype",
        "of",
        "case",
        "raise",
        "exception",
        "handle",
        "use",
        "real",
        "int",
    ]
)


class REPLWrapper:
    def __init__(self, cmd, orig_prompt: str, continuation_prompt: str):
        self.child = pexpect.spawn(cmd, echo=False, encoding="utf-8")

        self.prompt = re.compile(orig_prompt)
        self.continuation_prompt = re.compile(continuation_prompt)

        self._expect_prompt(timeout=1)

    def _expect_prompt(self, timeout=-1):
        return self.child.expect_list(
            [self.prompt, self.continuation_prompt], timeout=timeout
        )

    def run_command(self, command: str, timeout: Optional[int] = -1) -> Optional[str]:
        if not command:
            raise ValueError("No command was given")

        self.child.sendline(command)

        # Command was fully submitted, now wait for the next prompt
        if self._expect_prompt(timeout=timeout) == 1:
            # We got the continuation prompt - command was incomplete
            self.child.kill(signal.SIGINT)
            self._expect_prompt(timeout=1)
            raise ValueError(
                "Continuation prompt found - input was incomplete:\n" + command
            )
        return self.child.before
    
    def get_output(self) -> Optional[str]:
        return self.child.before


class SMLNJKernel(Kernel):
    implementation = "SML/NJ"
    implementation_version = "0.0.1"

    language_info = {
        "name": "SML/NJ",
        "codemirror_mode": "fsharp",
        "mimetype": "text/plain",
        "file_extension": ".sml",
    }

    @property
    def language_version(self) -> str:
        if self._language_version is None:
            self._language_version = check_output(["sml", ""]).decode("utf-8")
        return self._language_version

    @property
    def banner(self) -> str:
        return f"Simple SML/NJ Kernel {self.language_version}"

    def __init__(self, **kwargs):
        Kernel.__init__(self, **kwargs)
        self._language_version = None
        self._start_smlnj()

    def _start_smlnj(self):
        sig = signal.signal(signal.SIGINT, signal.SIG_DFL)
        try:
            self.smlnjwrapper = REPLWrapper("sml", "(\n|^)- ", "(\n|^)= ")
        finally:
            signal.signal(signal.SIGINT, sig)

    def do_complete(self, code: str, cursor_pos: int) -> Dict[str, Any]:
        m = REGEX_WORD.search(code[:cursor_pos])
        if m is not None:
            keyword = m.group(1)
            matches = [s for s in SML_KEYWORDS if s.startswith(keyword)]
            if matches:
                return {
                    "status": "ok",
                    "matches": matches,
                    "cursor_start": cursor_pos - len(keyword),
                    "cursor_end": cursor_pos,
                    "metadata": {},
                }
        return {
            "status": "ok",
            "matches": [],
            "cursor_start": cursor_pos,
            "cursor_end": cursor_pos,
            "metadata": {},
        }

    def do_is_complete(self, code: str) -> Dict[str, Any]:
        stripped = code.rstrip()
        if not stripped:
            return {
                "status": "complete",
            }
        elif stripped.endswith("*)") or stripped.endswith(";"):
            return {
                "status": "unknown",
            }
        else:
            return {
                "status": "incomplete",
                "indent": "",
            }

    def stdout_print(self, text: str) -> None:
        stream_content = {"name": "stdout", "text": text}
        self.send_response(self.iopub_socket, "stream", stream_content)

    def do_execute(
        self, code: str, silent, store_history: bool=True, user_expressions=None, allow_stdin: bool=False
    ) -> Dict[str, Any]:
        code = crlf_pat.sub(" ", code.strip())
        if not code:
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }

        interrupted = False
        try:
            output = self.smlnjwrapper.run_command(code)
        except KeyboardInterrupt:
            self.smlnjwrapper.child.sendintr()
            interrupted = True
            self.smlnjwrapper._expect_prompt()
            output = self.smlnjwrapper.get_output()
        except pexpect.EOF:
            output = self.smlnjwrapper.get_output() + "Restarting SML/NJ"
            self._start_smlnjang()
        except ValueError as e:
            # Continuation prompt found - input was incomplete
            self.stdout_print(e.args[0])
            return {"status": "error", "execution_count": self.execution_count}

        if not silent and output is not None:
            self.stdout_print(output)

        if interrupted:
            return {"status": "abort", "execution_count": self.execution_count}

        return {
            "status": "ok",
            "execution_count": self.execution_count,
            "payload": [],
            "user_expressions": {},
        }


if __name__ == "__main__":
    IPKernelApp.launch_instance(kernel_class=SMLNJKernel)
