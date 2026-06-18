from openai import OpenAI
from dotenv import load_dotenv
import json
import requests
import os
from pydantic import BaseModel,Field
from typing import Optional

import speech_recognition as sr
import asyncio

from openai import AsyncOpenAI
from openai.helpers import LocalAudioPlayer



load_dotenv()
client = OpenAI()
async_client = AsyncOpenAI()

class LLM_input(BaseModel):
    step: str = Field(...,description="this should be start | output | plan | tool | observe")
    tool : Optional[str] = Field(None,description="tool")
    input:Optional[str] = Field(None,description="input")
    output:Optional[str] = Field(None)
    content:Optional[str] = Field("")
    
    
    
## tools 

async def tts(speech):
    
    async with async_client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts",
        voice="coral",
        input=speech,
        instructions="Speak in a cheerful and positive tone.",
        response_format="pcm",
    ) as response:
        await LocalAudioPlayer().play(response)

    
def weather_api_call(city:str):
    url = f"https://wttr.in/{city.lower()}?format=%C+%t"
    res=  requests.get(url)
    
    if res.status_code == 200:
        return f"weather of {city} is {res.text}"
    return f"Something went wrong"

def run_command(cmd:str):
    return os.system(cmd)

# available tools
available_tools={
    'weather_api_call':weather_api_call,
    'run_command':run_command
}


## it will convert speech to text
r = sr.Recognizer() 


# zero shot prompting - direct giving instruction to LLM
system_prompt="""
                You are an expert assistant in resolving user queries, using chain of thought
                you work on start, plan and output Step.
                You need to 1st plan. What need to be done. The plan can be multiple step.
                Once you think enough plan has been done, finding given out.
                you can also call a tool if required from the list of available tools.
                For every tool call wait for the observe Step which is the output from the called tool.

                Rules:
                - Strictly follow the given JSON output format
                - only run one step at a time.
                - the sequence of step is start
                
                output json format :
                { "step" : "start" | "plan" | "output" | "tool", "content" : "string","tool":"string","input":"string"}
                
                available tools :
                - weather_api_call(city:str) : take city name as input string and return the weather info about city.
                -run_command(cmd:str): take linux command as string and execute command on user system and return the output from that command
                
                example:
                start : what is the weather of delhi?
                plan: {"step": "plan" , "content" : "seems like user is interested in getting the weather of Delhi in India"}
                plan: {"step": "plan" , "content" : "let's see, we have an available tool from the list of available tools"}
                plan: {"step": "plan" , "content" : "great, we have an available tool for the query"}
                plan: {"step": "plan" , "content" : "I need to call available function to get delhi as city for the function"}
                plan: {"step": "tool" ,"tool":"weather_api_call" , "input" : "delhi"}
                plan: {"step": "observe" , "tool" : "weather_api_call" , "output" : "the weather of the Delhi is 20°C"}
                plan: {"step": "plan" , "content" : "great, I got weather info about Delhi"}
                output : { "step": "output" , "content" : "the current weather in Delhi is 20°C with cloudy"}
                
                
                
"""

message_ = [
    {   "role": "system",
            "content": system_prompt
    }]

print("\n\n\n")
while True:
    with sr.Microphone() as source: # access to microphone
                r.adjust_for_ambient_noise(source) # active noise cancellation of input
                
                r.pause_threshold = 1.5
                print("say  something...")
                
                audio = r.listen(source)
                print("process audio...")
                stt = r.recognize_google(audio)
                print("You said:" , stt)
                
                
        
                user_input=stt
                    
                    
                message_.append({
                            "role": "user",
                            "content": user_input
                        })

                while True:
                        response = client.chat.completions.parse(
                        model="gpt-4.1",
                        response_format=LLM_input,
                        messages=message_
                        )
                        rew_res= response.choices[0].message.content
                        message_.append({"role":"assistant","content":rew_res})
                        parsed_output=response.choices[0].message.parsed
                    
                        if parsed_output.step == "start":
                            print("💥",parsed_output.content)
                            continue
                        if parsed_output.step == "plan":
                            print("🧠",parsed_output.content)
                            continue
                        if parsed_output.step == "tool":
                            user_tool = parsed_output.tool
                            user_inputcity = parsed_output.input
                            print(f"🚀 is tool {user_tool}({user_inputcity})")
                            res=available_tools[user_tool](user_inputcity)
                            message_.append({"role":"user","content":json.dumps(
                            {"step": "observe", "tool": user_tool , "input": user_inputcity, "output" : res}
                        )})
                            continue
                        
                        if parsed_output.step == "output":
                            print("🤖",parsed_output.content)
                            text  = parsed_output.content
                            print("Ai generated response \t" , text)
                            asyncio.run(tts(text))
                            break




                print("\n\n\n")