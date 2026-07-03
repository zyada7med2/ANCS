import unittest
import json
from network_manager.ai_agent import CopilotWorker

class TestOpenModelTranslator(unittest.TestCase):
    def test_build_anthropic_tools(self):
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "description": "Test description",
                    "parameters": {
                        "type": "object",
                        "properties": {"arg1": {"type": "string"}},
                        "required": ["arg1"]
                    }
                }
            }
        ]
        worker = CopilotWorker(api_key="test", gns3_url="test")
        anthropic_tools = worker._build_anthropic_tools(openai_tools)
        
        self.assertEqual(len(anthropic_tools), 1)
        self.assertEqual(anthropic_tools[0]["name"], "test_tool")
        self.assertEqual(anthropic_tools[0]["description"], "Test description")
        self.assertIn("input_schema", anthropic_tools[0])
        self.assertEqual(anthropic_tools[0]["input_schema"]["properties"]["arg1"]["type"], "string")

    def test_get_anthropic_messages(self):
        openai_history = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": "Running tool",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "test_tool", "arguments": "{\"arg1\": \"val\"}"}
                    }
                ]
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "success"}
        ]
        worker = CopilotWorker(api_key="test", gns3_url="test", initial_messages=openai_history)
        msgs = worker._get_anthropic_messages()
        
        # system should be filtered out
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[0]["content"], "Hello")
        
        # assistant message has text and tool_use blocks
        self.assertEqual(msgs[1]["role"], "assistant")
        self.assertEqual(len(msgs[1]["content"]), 2)
        self.assertEqual(msgs[1]["content"][0]["type"], "text")
        self.assertEqual(msgs[1]["content"][0]["text"], "Running tool")
        self.assertEqual(msgs[1]["content"][1]["type"], "tool_use")
        self.assertEqual(msgs[1]["content"][1]["id"], "call_1")
        self.assertEqual(msgs[1]["content"][1]["input"], {"arg1": "val"})
        
        # tool response maps back to user role with tool_result block
        self.assertEqual(msgs[2]["role"], "user")
        self.assertEqual(msgs[2]["content"][0]["type"], "tool_result")
        self.assertEqual(msgs[2]["content"][0]["tool_use_id"], "call_1")
        self.assertEqual(msgs[2]["content"][0]["content"], "success")

if __name__ == "__main__":
    unittest.main()
