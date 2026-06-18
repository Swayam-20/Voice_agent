# 🎙️ Voice AI Agent using OpenAI + Tool Calling

## Overview

This project is a **Voice Controlled AI Agent** that listens to user speech, converts it into text, reasons step-by-step using an LLM, executes tools when needed, and finally speaks the response back.

The assistant follows a structured execution cycle:

```text
Speech → Speech Recognition → LLM Planning → Tool Execution → Observation → Final Response → Text To Speech
```

---

# Project Architecture

```text
┌─────────────────────────┐
│ User Speaks             │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Speech Recognition      │
│ (speech_recognition)    │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Convert Speech → Text   │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ OpenAI LLM              │
│ (Chain of Thought)      │
└────────────┬────────────┘
             │
             ▼
 ┌────────────────────────────┐
 │ Decide Next Step           │
 │ start / plan / tool        │
 │ observe / output           │
 └────────────┬──────────────┘
              │
       Tool Required?
         YES / NO
          │
          ▼
┌─────────────────────────┐
│ Execute Tool            │
│ weather / command       │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Observe Tool Result     │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Generate Final Output   │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ Text To Speech          │
└─────────────────────────┘
```

---

# Technologies Used

| Tool              | Purpose                      |
| ----------------- | ---------------------------- |
| Python            | Main programming language    |
| OpenAI SDK        | LLM interaction              |
| AsyncOpenAI       | Async Text-to-Speech         |
| SpeechRecognition | Voice input                  |
| wttr.in API       | Weather API                  |
| requests          | HTTP requests                |
| pydantic          | Structured output validation |
| dotenv            | Environment variables        |
| asyncio           | Async execution              |

---

# Installation

## 1. Clone Repository

```bash
git clone <repo-url>
cd project
```

---

## 2. Install Dependencies

```bash
pip install openai
pip install python-dotenv
pip install requests
pip install pydantic
pip install SpeechRecognition
pip install pyaudio
```

---

## 3. Create Environment File

Create:

```text
.env
```

Add:

```env
OPENAI_API_KEY=your_api_key
```

---

# Project Structure

```text
project/
│
├── curser.py
├── .env
├── README.md
└── requirements.txt
```

---

# Execution Flow

## Step 1 — User Speaks

Program opens microphone.

```python
with sr.Microphone()
```

Example:

```text
"What's weather in Delhi?"
```

---

## Step 2 — Speech To Text

Convert audio into text:

```python
stt = r.recognize_google(audio)
```

Output:

```text
what is weather in delhi
```

---

## Step 3 — Send To LLM

Input goes to:

```python
client.chat.completions.parse()
```

LLM follows JSON format.

Example:

```json
{
 "step":"plan",
 "content":"Need weather info"
}
```

---

## Step 4 — Tool Decision

Model selects tool:

```json
{
 "step":"tool",
 "tool":"weather_api_call",
 "input":"delhi"
}
```

---

## Step 5 — Execute Tool

Tool runs:

```python
weather_api_call("delhi")
```

Output:

```text
weather of delhi is Cloudy 24°C
```

---

## Step 6 — Observe Result

System appends:

```json
{
 "step":"observe",
 "output":"weather data"
}
```

---

## Step 7 — Final Output

LLM produces final answer:

```json
{
 "step":"output",
 "content":"Current weather is 24°C"
}
```

---

## Step 8 — Text To Speech

AI speaks:

```python
asyncio.run(tts(text))
```

---

# Available Tools

## Weather Tool

Gets weather information.

```python
weather_api_call(city)
```

Example:

```text
weather_api_call("London")
```

Returns:

```text
Weather of London is Sunny 28°C
```

---

## Command Tool

Executes Linux commands.

```python
run_command(cmd)
```

Example:

```text
run_command("ls")
```

Returns terminal output.

⚠️ Warning:
Executing shell commands can be risky.

---

# JSON Response Format

```json
{
 "step":"start",
 "tool":"optional",
 "input":"optional",
 "output":"optional",
 "content":"message"
}
```

Values:

```text
start
plan
tool
observe
output
```

---

# Example Full Conversation

```text
User:
What's weather in Delhi?

AI:
start

AI:
plan

AI:
tool(weather_api_call)

Tool:
Cloudy 25°C

AI:
observe

AI:
output
Current weather in Delhi is 25°C
```

---

# Future Improvements

* Add memory
* Multi-tool execution
* Streaming responses
* Better error handling
* GUI interface
* Local speech model
* Docker deployment

---

# Run Project

```bash
python curser.py
```

Speak into microphone and the assistant will respond.
