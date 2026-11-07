from openai import OpenAI
from dotenv import load_dotenv
import json
import os
import requests
import re
import shlex
import subprocess
import threading
from queue import Empty, Queue
from pathlib import Path
from pydantic import BaseModel,Field
from typing import Optional

import speech_recognition as sr
import asyncio

from openai import AsyncOpenAI
from openai.helpers import LocalAudioPlayer



load_dotenv()
PROJECT_ROOT = Path(__file__).resolve().parent
BLOCKED_PATH_PARTS = {".env", ".git", ".venv", "__pycache__"}
MAX_FILE_CHARS = 100_000
MAX_COMMAND_OUTPUT_CHARS = 12_000

STOP_COMMAND = re.compile(
    r"^\s*(?:(?:please|wait|hey|okay|ok)[,\s]+)*stop\b",
    re.IGNORECASE,
)
APPROVE_COMMAND = re.compile(
    r"^\s*(?:yes|yeah|yep|sure|go ahead|run it|do it|approve)\b",
    re.IGNORECASE,
)

class LLM_input(BaseModel):
    step: str = Field(..., description="Return either tool or output")
    tool : Optional[str] = Field(None,description="tool")
    input:Optional[str] = Field(None,description="input")
    output:Optional[str] = Field(None)
    content:Optional[str] = Field("")
    
    
    
## tools 

def listen_for_stop(stop_event, followup_queue):
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 0.6
    recognizer.non_speaking_duration = 0.3
    recognizer.operation_timeout = 3

    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.25)
            while not stop_event.is_set():
                try:
                    audio = recognizer.listen(
                        source,
                        timeout=0.25,
                        phrase_time_limit=4,
                    )
                except sr.WaitTimeoutError:
                    continue

                if stop_event.is_set():
                    return

                try:
                    transcript = recognizer.recognize_google(audio).strip()
                except sr.UnknownValueError:
                    continue
                except sr.RequestError as error:
                    print(f"Stop listener could not reach speech recognition: {error}")
                    return

                match = STOP_COMMAND.match(transcript)
                if match:
                    followup = transcript[match.end():].strip(" \t,.;:!?")
                    if followup.lower().startswith("and "):
                        followup = followup[4:].lstrip()
                    followup_queue.put(followup)
                    stop_event.set()
                    return
    except OSError as error:
        print(f"Stop listener could not open the microphone: {error}")


async def tts(speech):
    stop_event = threading.Event()
    followup_queue = Queue(maxsize=1)
    listener = threading.Thread(
        target=listen_for_stop,
        args=(stop_event, followup_queue),
        daemon=True,
    )
    listener.start()

    try:
        async with AsyncOpenAI() as async_client:
            async with async_client.audio.speech.with_streaming_response.create(
                model="gpt-4o-mini-tts",
                voice="coral",
                input=speech,
                instructions="Speak in a cheerful and positive tone.",
                response_format="pcm",
            ) as response:
                await LocalAudioPlayer(should_stop=stop_event.is_set).play(response)
    finally:
        stop_event.set()
        listener.join(timeout=4.5)

    try:
        return followup_queue.get_nowait()
    except Empty:
        return None

    
def weather_api_call(city:str):
    url = f"https://wttr.in/{city.lower()}?format=%C+%t"
    res=  requests.get(url)
    
    if res.status_code == 200:
        return f"weather of {city} is {res.text}"
    return f"Something went wrong"

def run_command(cmd:str):
    if not isinstance(cmd, str):
        return "Command input must be text."
    try:
        payload = json.loads(cmd)
    except (json.JSONDecodeError, TypeError):
        payload = {"command": cmd, "cwd": "."}

    if not isinstance(payload, dict):
        return "Command input must be a command string or JSON object."

    command = payload.get("command", "")
    working_directory = payload.get("cwd", ".")
    if not isinstance(command, str) or not command.strip():
        return "No command was provided."

    try:
        cwd = workspace_path(working_directory)
        if not cwd.is_dir():
            return f"Working directory does not exist: {working_directory}"
        args = shlex.split(command)
        if not args:
            return "No command was provided."
        if any(command_references_blocked_path(arg) for arg in args):
            return "Command blocked from accessing protected project paths."
        result = subprocess.run(
            args,
            cwd=cwd,
            env=command_environment(),
            capture_output=True,
            text=True,
            timeout=120,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        return f"Command not found: {args[0]}"
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        return f"Command timed out after 120 seconds.\n{stdout}\n{stderr}"[:MAX_COMMAND_OUTPUT_CHARS]
    except (OSError, RuntimeError, ValueError) as error:
        return f"Invalid command or path: {error}"

    output = (
        f"Exit code: {result.returncode}\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    return output[:MAX_COMMAND_OUTPUT_CHARS]


def command_environment():
    environment = os.environ.copy()
    virtualenv_bin = PROJECT_ROOT / ".venv" / "bin"
    if virtualenv_bin.is_dir():
        environment["PATH"] = f"{virtualenv_bin}{os.pathsep}{environment.get('PATH', '')}"
    return environment


def get_command_text(command_input):
    if not isinstance(command_input, str):
        return ""
    try:
        payload = json.loads(command_input)
    except json.JSONDecodeError:
        return command_input
    return payload.get("command", "") if isinstance(payload, dict) else command_input


def command_references_blocked_path(argument):
    candidates = [argument]
    if "=" in argument:
        candidates.append(argument.split("=", 1)[1])
    for candidate in candidates:
        if any(is_blocked_path_part(part) for part in Path(candidate).parts):
            return True
    return False


def command_requires_approval(command_input):
    command = get_command_text(command_input)
    try:
        args = shlex.split(command)
    except ValueError:
        return True
    if not args:
        return False

    executable = Path(args[0]).name.lower()
    lowered_args = [argument.lower() for argument in args[1:]]
    if executable in {
        "rm", "rmdir", "mv", "sudo", "chmod", "chown", "kill", "pkill",
        "launchctl", "diskutil", "shutdown", "reboot", "osascript", "open",
        "curl", "wget", "bash", "sh", "zsh", "dd", "truncate", "mkfs",
        "mount", "umount", "format",
    }:
        return True

    if executable in {"python", "python3"} and "-c" in lowered_args:
        return True
    if executable in {"node", "ruby", "perl", "php"} and any(
        flag in lowered_args for flag in {"-e", "-r"}
    ):
        return True

    if executable in {"pip", "pip3"} and any(action in lowered_args for action in {"install", "uninstall"}):
        return True
    if executable in {"python", "python3"} and "-m" in lowered_args:
        module_index = lowered_args.index("-m")
        if module_index + 2 < len(lowered_args) and lowered_args[module_index + 1] == "pip":
            if lowered_args[module_index + 2] in {"install", "uninstall"}:
                return True

    if executable == "brew" and len(lowered_args) > 0 and lowered_args[0] not in {"--version", "list", "info"}:
        return True
    if executable == "npx":
        return True
    if executable in {"npm", "pnpm", "yarn", "uv"}:
        if any(action in lowered_args for action in {"install", "uninstall", "add", "remove", "upgrade", "update"}):
            return True

    if executable == "git" and lowered_args:
        if any(action in lowered_args for action in {
            "clone", "fetch", "pull", "push", "reset", "clean", "checkout",
            "restore", "commit", "merge", "rebase", "revert",
        }):
            return True
        if "branch" in lowered_args and any(flag in lowered_args for flag in {"-d", "-D"}):
            return True

    for argument in args[1:]:
        candidate = argument.split("=", 1)[-1]
        path = Path(candidate)
        if ".." in path.parts:
            return True
        if path.is_absolute() and not path.resolve().is_relative_to(PROJECT_ROOT):
            return True
    return False


def workspace_path(relative_path):
    if not isinstance(relative_path, str):
        raise ValueError("Path must be text.")
    if not relative_path.strip():
        relative_path = "."

    requested_path = Path(relative_path)
    if requested_path.is_absolute():
        raise ValueError("Use a relative path inside the project folder.")

    resolved_path = (PROJECT_ROOT / requested_path).resolve()
    if not resolved_path.is_relative_to(PROJECT_ROOT):
        raise ValueError("That path is outside the project folder.")

    parts = resolved_path.relative_to(PROJECT_ROOT).parts
    if any(is_blocked_path_part(part) for part in parts):
        raise ValueError("Access to environment and internal folders is blocked.")
    return resolved_path


def is_blocked_path_part(part):
    return part in BLOCKED_PATH_PARTS or part.startswith(".env.")


def create_directory(path):
    try:
        directory = workspace_path(path)
        relative_directory = directory.relative_to(PROJECT_ROOT)
        directory_argument = relative_directory.as_posix()
        if directory_argument != ".":
            directory_argument = f"./{directory_argument}"
        result = subprocess.run(
            ["mkdir", "-p", directory_argument],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            return f"Could not create folder: {result.stderr.strip()}"
        return f"Folder ready: {directory.relative_to(PROJECT_ROOT) or '.'}"
    except (OSError, ValueError) as error:
        return f"Could not create folder: {error}"


def list_files(path):
    try:
        directory = workspace_path(path)
        if not directory.is_dir():
            return f"Not a folder: {path}"
        entries = []
        for entry in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
            if is_blocked_path_part(entry.name):
                continue
            try:
                if not entry.resolve().is_relative_to(PROJECT_ROOT):
                    continue
            except OSError:
                continue
            kind = "folder" if entry.is_dir() else "file"
            entries.append(f"{kind}: {entry.name}")
            if len(entries) >= 250:
                entries.append("(truncated after 250 entries)")
                break
        return "\n".join(entries) if entries else "Folder is empty."
    except (OSError, ValueError) as error:
        return f"Could not list folder: {error}"


def read_file(path):
    try:
        file_path = workspace_path(path)
        if not file_path.is_file():
            return f"Not a file: {path}"
        content = file_path.read_text(encoding="utf-8")
        if len(content) > MAX_FILE_CHARS:
            return f"File is too large to read (limit: {MAX_FILE_CHARS} characters)."
        return content
    except (OSError, UnicodeError, ValueError) as error:
        return f"Could not read file: {error}"


def write_file(raw_input):
    try:
        payload = json.loads(raw_input)
        relative_path = payload["path"]
        content = payload["content"]
        overwrite = payload.get("overwrite", False)
        if not isinstance(content, str):
            return "File content must be text."
        if len(content) > MAX_FILE_CHARS:
            return f"File content exceeds the {MAX_FILE_CHARS}-character limit."

        file_path = workspace_path(relative_path)
        if file_path.exists() and not overwrite:
            return "File already exists. Read it first and set overwrite=true only when the user requested a change."
        if not file_path.parent.is_dir():
            return "Parent folder does not exist. Create it first with create_directory."
        file_path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {file_path.relative_to(PROJECT_ROOT)}."
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        return f"File input must be JSON with path and content fields: {error}"
    except (OSError, ValueError) as error:
        return f"Could not write file: {error}"

# available tools
available_tools={
    'weather_api_call':weather_api_call,
    'run_command':run_command,
    'create_directory':create_directory,
    'list_files':list_files,
    'read_file':read_file,
    'write_file':write_file,
}


## it will convert speech to text
r = sr.Recognizer() 

def listen_for_input():
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source)
        r.pause_threshold = 1.5
        audio = r.listen(source)

    try:
        stt = r.recognize_google(audio)
    except sr.UnknownValueError:
        print("I couldn't understand that. Please try again.")
        return None
    except sr.RequestError as error:
        print(f"Speech recognition service is unavailable: {error}")
        return None

    return stt


# zero shot prompting - direct giving instruction to LLM
system_prompt="""
                You are a fast, helpful voice assistant and coding agent.
                Think through the task privately. Do not narrate routine steps or read out your plan.
                If the request is clear, act immediately and use the available tools to complete it.
                Offer a suggestion only when it materially helps or prevents a likely mistake.
                Ask a brief question only when a missing detail blocks the task.
                After each tool result, either take the next action or give the concise final answer.

                Rules:
                - Return exactly one JSON object with step "tool" or "output".
                - Do not send start or plan narration for routine requests.
                - Make one tool call at a time, then use its result to continue.
                - Keep using conversation history when the user asks to add or remove steps from the current plan.
                - Apply requested plan changes before continuing the response.
                - For coding requests, inspect the project before changing it, then create folders and files as needed.
                - Use paths relative to the project folder. Never access .env, .git, .venv, or __pycache__.
                - Use run_command for one CLI command at a time. Routine project commands run automatically; the app asks before risky commands.
                - Keep the final spoken response to one or two short sentences.
                
                output json format :
                { "step" : "tool" | "output", "content" : "string","tool":"string","input":"string"}
                
                available tools :
                - list_files(path:str): list files in a project folder; use "." for the project root.
                - read_file(path:str): read a UTF-8 file inside the project.
                - create_directory(path:str): create a project folder with the mkdir CLI, including missing parents.
                - write_file(input:str): input is JSON with path, content, and optional overwrite boolean.
                - run_command(input:str): input is a command string or JSON {"command":"...","cwd":"."}; runs one CLI command in the project.
                - weather_api_call(city:str): get current weather for a city.
                
                example:
                User: Create a folder named reports.
                Assistant: {"step":"tool","tool":"create_directory","input":"reports"}
                
                
                
"""

def main():
    client = OpenAI()
    message_ = [{"role": "system", "content": system_prompt}]
    pending_user_input = None

    while True:
        if pending_user_input is None:
            user_input = listen_for_input()
            if user_input is None:
                continue
        else:
            user_input = pending_user_input
            pending_user_input = None

        if not user_input.strip():
            continue

        message_.append({"role": "user", "content": user_input})

        while True:
            response = client.chat.completions.parse(
                model="gpt-4.1",
                response_format=LLM_input,
                messages=message_,
            )
            rew_res = response.choices[0].message.content
            message_.append({"role": "assistant", "content": rew_res})
            parsed_output = response.choices[0].message.parsed

            if parsed_output.step == "start":
                continue
            if parsed_output.step == "plan":
                continue
            if parsed_output.step == "tool":
                user_tool = parsed_output.tool
                tool_input = parsed_output.input or ""
                command_interrupted = False
                if user_tool not in available_tools:
                    result = f"Unknown tool: {user_tool}"
                elif user_tool == "run_command":
                    if command_requires_approval(tool_input):
                        command_preview = get_command_text(tool_input)
                        approval_prompt = (
                            f"This command needs your approval: {command_preview}. "
                            "When I finish, say yes to run it, or no to cancel."
                        )
                        interrupted_input = asyncio.run(tts(approval_prompt))
                        if interrupted_input is not None:
                            command_interrupted = True
                            if interrupted_input:
                                pending_user_input = interrupted_input
                            result = "Command cancelled because the approval prompt was interrupted."
                        else:
                            approval = listen_for_input()
                            if APPROVE_COMMAND.match(approval or ""):
                                result = available_tools[user_tool](tool_input)
                            else:
                                result = "Command not run because spoken approval was not received."
                    else:
                        result = available_tools[user_tool](tool_input)
                else:
                    result = available_tools[user_tool](tool_input)

                message_.append({"role": "user", "content": json.dumps(
                    {"step": "observe", "tool": user_tool, "input": tool_input, "output": result}
                )})
                if command_interrupted:
                    break
                continue

            if parsed_output.step == "output":
                text = parsed_output.content
                print(text)
                interrupted_input = asyncio.run(tts(text))
                if interrupted_input is not None:
                    if interrupted_input:
                        pending_user_input = interrupted_input
                break


if __name__ == "__main__":
    main()
