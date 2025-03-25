# coding=utf-8
# Copyright 2024 HuggingFace Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
from textwrap import dedent
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import mcp
import numpy as np
import PIL.Image
import pytest
import torch
from huggingface_hub.utils import is_torch_available

from smolagents.agent_types import _AGENT_TYPE_MAPPING, AgentAudio, AgentImage, AgentText
from smolagents.tools import AUTHORIZED_TYPES, Tool, ToolCollection, tool

from .utils.markers import require_run_all


if is_torch_available():
    import torch


def output_type(output):
    if isinstance(output, (str, AgentText)):
        return "string"
    elif isinstance(output, (PIL.Image.Image, AgentImage)):
        return "image"
    elif isinstance(output, (torch.Tensor, AgentAudio)):
        return "audio"
    else:
        raise TypeError(f"Invalid output: {output}")


class ToolTesterMixin:
    def test_inputs_output(self):
        assert hasattr(self.tool, "inputs")
        assert hasattr(self.tool, "output_type")

        inputs = self.tool.inputs
        assert isinstance(inputs, dict)

        for _, input_spec in inputs.items():
            assert "type" in input_spec
            assert "description" in input_spec
            assert input_spec["type"] in AUTHORIZED_TYPES
            assert isinstance(input_spec["description"], str)

        output_type = self.tool.output_type
        assert output_type in AUTHORIZED_TYPES

    def test_common_attributes(self):
        assert hasattr(self.tool, "description")
        assert hasattr(self.tool, "name")
        assert hasattr(self.tool, "inputs")
        assert hasattr(self.tool, "output_type")

    def test_agent_type_output(self, create_inputs):
        inputs = create_inputs(self.tool.inputs)
        output = self.tool(**inputs, sanitize_inputs_outputs=True)
        if self.tool.output_type != "any":
            agent_type = _AGENT_TYPE_MAPPING[self.tool.output_type]
            assert isinstance(output, agent_type)

    @pytest.fixture
    def create_inputs(self, shared_datadir):
        def _create_inputs(tool_inputs: dict[str, dict[str | type, str]]) -> dict[str, Any]:
            inputs = {}

            for input_name, input_desc in tool_inputs.items():
                input_type = input_desc["type"]

                if input_type == "string":
                    inputs[input_name] = "Text input"
                elif input_type == "image":
                    inputs[input_name] = PIL.Image.open(shared_datadir / "000000039769.png").resize((512, 512))
                elif input_type == "audio":
                    inputs[input_name] = np.ones(3000)
                else:
                    raise ValueError(f"Invalid type requested: {input_type}")

            return inputs

        return _create_inputs


class TestTool:
    def test_tool_init_with_decorator(self):
        @tool
        def coolfunc(a: str, b: int) -> float:
            """Cool function

            Args:
                a: The first argument
                b: The second one
            """
            return b + 2, a

        assert coolfunc.output_type == "number"

    def test_tool_init_vanilla(self):
        class HFModelDownloadsTool(Tool):
            name = "model_download_counter"
            description = """
            This is a tool that returns the most downloaded model of a given task on the Hugging Face Hub.
            It returns the name of the checkpoint."""

            inputs = {
                "task": {
                    "type": "string",
                    "description": "the task category (such as text-classification, depth-estimation, etc)",
                }
            }
            output_type = "string"

            def forward(self, task: str) -> str:
                return "best model"

        tool = HFModelDownloadsTool()
        assert list(tool.inputs.keys())[0] == "task"

    def test_tool_init_decorator_raises_issues(self):
        with pytest.raises(Exception) as e:

            @tool
            def coolfunc(a: str, b: int):
                """Cool function

                Args:
                    a: The first argument
                    b: The second one
                """
                return a + b

            assert coolfunc.output_type == "number"
        assert "Tool return type not found" in str(e)

        with pytest.raises(Exception) as e:

            @tool
            def coolfunc(a: str, b: int) -> int:
                """Cool function

                Args:
                    a: The first argument
                """
                return b + a

            assert coolfunc.output_type == "number"
        assert "docstring has no description for the argument" in str(e)

    def test_saving_tool_raises_error_imports_outside_function(self, tmp_path):
        with pytest.raises(Exception) as e:
            import numpy as np

            @tool
            def get_current_time() -> str:
                """
                Gets the current time.
                """
                return str(np.random.random())

            get_current_time.save(tmp_path)

        assert "np" in str(e)

        # Also test with classic definition
        with pytest.raises(Exception) as e:

            class GetCurrentTimeTool(Tool):
                name = "get_current_time_tool"
                description = "Gets the current time"
                inputs = {}
                output_type = "string"

                def forward(self):
                    return str(np.random.random())

            get_current_time = GetCurrentTimeTool()
            get_current_time.save(tmp_path)

        assert "np" in str(e)

    def test_tool_definition_raises_no_error_imports_in_function(self):
        @tool
        def get_current_time() -> str:
            """
            Gets the current time.
            """
            from datetime import datetime

            return str(datetime.now())

        class GetCurrentTimeTool(Tool):
            name = "get_current_time_tool"
            description = "Gets the current time"
            inputs = {}
            output_type = "string"

            def forward(self):
                from datetime import datetime

                return str(datetime.now())

    def test_tool_to_dict_allows_no_arg_in_init(self):
        """Test that a tool cannot be saved with required args in init"""

        class FailTool(Tool):
            name = "specific"
            description = "test description"
            inputs = {"string_input": {"type": "string", "description": "input description"}}
            output_type = "string"

            def __init__(self, url):
                super().__init__(self)
                self.url = url

            def forward(self, string_input: str) -> str:
                return self.url + string_input

        fail_tool = FailTool("dummy_url")
        with pytest.raises(Exception) as e:
            fail_tool.to_dict()
        assert "Parameters in __init__ must have default values, found required parameters" in str(e)

        class PassTool(Tool):
            name = "specific"
            description = "test description"
            inputs = {"string_input": {"type": "string", "description": "input description"}}
            output_type = "string"

            def __init__(self, url: Optional[str] = "none"):
                super().__init__(self)
                self.url = url

            def forward(self, string_input: str) -> str:
                return self.url + string_input

        fail_tool = PassTool()
        fail_tool.to_dict()

    def test_saving_tool_allows_no_imports_from_outside_methods(self, tmp_path):
        # Test that using imports from outside functions fails
        import numpy as np

        class FailTool(Tool):
            name = "specific"
            description = "test description"
            inputs = {"string_input": {"type": "string", "description": "input description"}}
            output_type = "string"

            def useless_method(self):
                self.client = np.random.random()
                return ""

            def forward(self, string_input):
                return self.useless_method() + string_input

        fail_tool = FailTool()
        with pytest.raises(Exception) as e:
            fail_tool.save(tmp_path)
        assert "'np' is undefined" in str(e)

        # Test that putting these imports inside functions works
        class SuccessTool(Tool):
            name = "specific"
            description = "test description"
            inputs = {"string_input": {"type": "string", "description": "input description"}}
            output_type = "string"

            def useless_method(self):
                import numpy as np

                self.client = np.random.random()
                return ""

            def forward(self, string_input):
                return self.useless_method() + string_input

        success_tool = SuccessTool()
        success_tool.save(tmp_path)

    def test_tool_missing_class_attributes_raises_error(self):
        with pytest.raises(Exception) as e:

            class GetWeatherTool(Tool):
                name = "get_weather"
                description = "Get weather in the next days at given location."
                inputs = {
                    "location": {"type": "string", "description": "the location"},
                    "celsius": {
                        "type": "string",
                        "description": "the temperature type",
                    },
                }

                def forward(self, location: str, celsius: Optional[bool] = False) -> str:
                    return "The weather is UNGODLY with torrential rains and temperatures below -10°C"

            GetWeatherTool()
        assert "You must set an attribute output_type" in str(e)

    def test_tool_from_decorator_optional_args(self):
        @tool
        def get_weather(location: str, celsius: Optional[bool] = False) -> str:
            """
            Get weather in the next days at given location.
            Secretly this tool does not care about the location, it hates the weather everywhere.

            Args:
                location: the location
                celsius: the temperature type
            """
            return "The weather is UNGODLY with torrential rains and temperatures below -10°C"

        assert "nullable" in get_weather.inputs["celsius"]
        assert get_weather.inputs["celsius"]["nullable"]
        assert "nullable" not in get_weather.inputs["location"]

    def test_tool_mismatching_nullable_args_raises_error(self):
        with pytest.raises(Exception) as e:

            class GetWeatherTool(Tool):
                name = "get_weather"
                description = "Get weather in the next days at given location."
                inputs = {
                    "location": {"type": "string", "description": "the location"},
                    "celsius": {
                        "type": "string",
                        "description": "the temperature type",
                    },
                }
                output_type = "string"

                def forward(self, location: str, celsius: Optional[bool] = False) -> str:
                    return "The weather is UNGODLY with torrential rains and temperatures below -10°C"

            GetWeatherTool()
        assert "Nullable" in str(e)

        with pytest.raises(Exception) as e:

            class GetWeatherTool2(Tool):
                name = "get_weather"
                description = "Get weather in the next days at given location."
                inputs = {
                    "location": {"type": "string", "description": "the location"},
                    "celsius": {
                        "type": "string",
                        "description": "the temperature type",
                    },
                }
                output_type = "string"

                def forward(self, location: str, celsius: bool = False) -> str:
                    return "The weather is UNGODLY with torrential rains and temperatures below -10°C"

            GetWeatherTool2()
        assert "Nullable" in str(e)

        with pytest.raises(Exception) as e:

            class GetWeatherTool3(Tool):
                name = "get_weather"
                description = "Get weather in the next days at given location."
                inputs = {
                    "location": {"type": "string", "description": "the location"},
                    "celsius": {
                        "type": "string",
                        "description": "the temperature type",
                        "nullable": True,
                    },
                }
                output_type = "string"

                def forward(self, location, celsius: str) -> str:
                    return "The weather is UNGODLY with torrential rains and temperatures below -10°C"

            GetWeatherTool3()
        assert "Nullable" in str(e)

    def test_tool_default_parameters_is_nullable(self):
        @tool
        def get_weather(location: str, celsius: bool = False) -> str:
            """
            Get weather in the next days at given location.

            Args:
                location: The location to get the weather for.
                celsius: is the temperature given in celsius?
            """
            return "The weather is UNGODLY with torrential rains and temperatures below -10°C"

        assert get_weather.inputs["celsius"]["nullable"]

    def test_tool_supports_any_none(self, tmp_path):
        @tool
        def get_weather(location: Any) -> None:
            """
            Get weather in the next days at given location.

            Args:
                location: The location to get the weather for.
            """
            return

        get_weather.save(tmp_path)
        assert get_weather.inputs["location"]["type"] == "any"
        assert get_weather.output_type == "null"

    def test_tool_supports_array(self):
        @tool
        def get_weather(locations: List[str], months: Optional[Tuple[str, str]] = None) -> Dict[str, float]:
            """
            Get weather in the next days at given locations.

            Args:
                locations: The locations to get the weather for.
                months: The months to get the weather for
            """
            return

        assert get_weather.inputs["locations"]["type"] == "array"
        assert get_weather.inputs["months"]["type"] == "array"

    def test_saving_tool_produces_valid_pyhon_code_with_multiline_description(self, tmp_path):
        @tool
        def get_weather(location: Any) -> None:
            """
            Get weather in the next days at given location.
            And works pretty well.

            Args:
                location: The location to get the weather for.
            """
            return

        get_weather.save(tmp_path)
        with open(os.path.join(tmp_path, "tool.py"), "r", encoding="utf-8") as f:
            source_code = f.read()
            compile(source_code, f.name, "exec")

    def test_saving_tool_produces_valid_python_code_with_complex_name(self, tmp_path):
        # Test one cannot save tool with additional args in init
        class FailTool(Tool):
            name = 'spe"\rcific'
            description = """test \n\r
            description"""
            inputs = {"string_input": {"type": "string", "description": "input description"}}
            output_type = "string"

            def __init__(self):
                super().__init__(self)

            def forward(self, string_input):
                return "foo"

        fail_tool = FailTool()
        fail_tool.save(tmp_path)
        with open(os.path.join(tmp_path, "tool.py"), "r", encoding="utf-8") as f:
            source_code = f.read()
            compile(source_code, f.name, "exec")

    @pytest.mark.parametrize("fixture_name", ["boolean_default_tool_class", "boolean_default_tool_function"])
    def test_to_dict_boolean_default_input(self, fixture_name, request):
        """Test that boolean input parameter with default value is correctly represented in to_dict output"""
        tool = request.getfixturevalue(fixture_name)
        result = tool.to_dict()
        # Check that the boolean default annotation is preserved
        assert "flag: bool = False" in result["code"]
        # Check nullable attribute is set for the parameter with default value
        assert "'nullable': True" in result["code"]

    @pytest.mark.parametrize("fixture_name", ["optional_input_tool_class", "optional_input_tool_function"])
    def test_to_dict_optional_input(self, fixture_name, request):
        """Test that Optional/nullable input parameter is correctly represented in to_dict output"""
        tool = request.getfixturevalue(fixture_name)
        result = tool.to_dict()
        # Check the Optional type annotation is preserved
        assert "optional_text: Optional[str] = None" in result["code"]
        # Check that the input is marked as nullable in the code
        assert "'nullable': True" in result["code"]


@pytest.fixture
def mock_server_parameters():
    return MagicMock()


@pytest.fixture
def mock_mcp_adapt():
    with patch("mcpadapt.core.MCPAdapt") as mock:
        mock.return_value.__enter__.return_value = ["tool1", "tool2"]
        mock.return_value.__exit__.return_value = None
        yield mock


@pytest.fixture
def mock_smolagents_adapter():
    with patch("mcpadapt.smolagents_adapter.SmolAgentsAdapter") as mock:
        yield mock


class TestToolCollection:
    def test_from_mcp(self, mock_server_parameters, mock_mcp_adapt, mock_smolagents_adapter):
        with ToolCollection.from_mcp(mock_server_parameters) as tool_collection:
            assert isinstance(tool_collection, ToolCollection)
            assert len(tool_collection.tools) == 2
            assert "tool1" in tool_collection.tools
            assert "tool2" in tool_collection.tools

    @require_run_all
    def test_integration_from_mcp(self):
        # define the most simple mcp server with one tool that echoes the input text
        mcp_server_script = dedent("""\
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("Echo Server")

            @mcp.tool()
            def echo_tool(text: str) -> str:
                return text

            mcp.run()
        """).strip()

        mcp_server_params = mcp.StdioServerParameters(
            command="python",
            args=["-c", mcp_server_script],
        )

        with ToolCollection.from_mcp(mcp_server_params) as tool_collection:
            assert len(tool_collection.tools) == 1, "Expected 1 tool"
            assert tool_collection.tools[0].name == "echo_tool", "Expected tool name to be 'echo_tool'"
            assert tool_collection.tools[0](text="Hello") == "Hello", "Expected tool to echo the input text"

    def test_integration_from_mcp_with_sse(self):
        import subprocess
        import time

        # define the most simple mcp server with one tool that echoes the input text
        mcp_server_script = dedent("""\
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("Echo Server", host="127.0.0.1", port=8000)

            @mcp.tool()
            def echo_tool(text: str) -> str:
                return text

            mcp.run("sse")
        """).strip()

        # start the SSE mcp server in a subprocess
        server_process = subprocess.Popen(
            ["python", "-c", mcp_server_script],
        )

        # wait for the server to start
        time.sleep(1)

        try:
            with ToolCollection.from_mcp({"url": "http://127.0.0.1:8000/sse"}) as tool_collection:
                assert len(tool_collection.tools) == 1, "Expected 1 tool"
                assert tool_collection.tools[0].name == "echo_tool", "Expected tool name to be 'echo_tool'"
                assert tool_collection.tools[0](text="Hello") == "Hello", "Expected tool to echo the input text"
        finally:
            # clean up the process when test is done
            server_process.kill()
            server_process.wait()
