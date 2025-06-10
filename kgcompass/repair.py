import os
import json
from tqdm import tqdm
import dashscope
import http
from kgcompass.config import (
    BAILIAN_API_KEY,
    BAILIAN_AGENT_KEY,
    MODEL_MAP,
    MAX_INPUT_LENGTH
)
from concurrent.futures import ThreadPoolExecutor, as_completed

class CodeRepair:
    def __init__(self, api_type, temperature, top_p, num_workers):
        self.api_type = api_type
        self.temperature = temperature
        self.top_p = top_p
        self.num_workers = num_workers
        self.model = MODEL_MAP.get(api_type, api_type)

        if self.api_type in ["deepseek", "qwen", "yi"]:
            self.api_key = BAILIAN_API_KEY
            self.agent_key = BAILIAN_AGENT_KEY
            self.client = None # Not using a persistent client for dashscope
            self.MAX_INPUT_LENGTH = MAX_INPUT_LENGTH['bailian']
        else:
            raise ValueError(f"Unsupported API type: {api_type}")

    def get_completion(self, prompt, retries=5, delay=10):
        if self.client is None: # dashscope logic
            dashscope.api_key = self.api_key
            try:
                response = dashscope.Generation.call(
                    model=self.model,
                    prompt=prompt,
                    api_key=self.api_key,
                    agent_key=self.agent_key,
                    temperature=self.temperature,
                    top_p=self.top_p,
                )
                if response.status_code == http.HTTPStatus.OK:
                    return response.output['text']
                else:
                    print(f"Error: {response.code} - {response.message}")
                    return None
            except Exception as e:
                print(f"An error occurred: {e}")
                return None
        else:
             raise ValueError(f"Unsupported API type: {self.api_type}")
        return None

    def process_instance(self, instance_id, repo_name, file_path, func_name, start_line, end_line, issue):
        pass

