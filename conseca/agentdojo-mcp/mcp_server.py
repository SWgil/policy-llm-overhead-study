import abc
import argparse
import json
from collections import defaultdict
import threading
from typing import Optional
import os
import re

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
from agentdojo.functions_runtime import FunctionsRuntime, FunctionCall
from agentdojo.task_suite.load_suites import get_suite, get_suites
from agentdojo.task_suite.task_suite import TaskSuite
import agentdojo.attacks  # noqa: F401  -- registers the attacks
from agentdojo.attacks.attack_registry import ATTACKS, load_attack
from agentdojo.attacks.base_attacks import DEFAULT_MODEL_NAME
from agentdojo.models import MODEL_NAMES
from agentdojo.types import text_content_block_from_string

from mcp import ErrorData
import uvicorn
from fastapi import FastAPI, HTTPException
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers
from fastmcp.exceptions import McpError
from fastmcp.tools.tool import Tool, ToolResult
from pydantic import BaseModel

rest_api = FastAPI(title="MCP API")

data = {}

RESULT_DIR = "./mcp_results"

# Benchmark version used when the request does not name one. AgentDyn's paper
# runs are logged as v1.2.2; its own suites (shopping/github/dailylife) are the
# same objects under every version key, the four AgentDojo suites are not.
DEFAULT_BENCHMARK_VERSION = "v1.2.2"


class InitTaskRequest(BaseModel):
    task_id: str
    suite_name: str
    user_task_id: str
    injection_task_id: Optional[str] = None
    # Suite registry key (v1, v1.1, ..., v1.2.2). Only matters for the four
    # AgentDojo suites, whose tasks differ between versions.
    benchmark_version: str = DEFAULT_BENCHMARK_VERSION
    # Model the agent runs on (e.g. "gemini-2.5-flash"). Used to pick the model
    # name in the injection text the same way upstream does from the pipeline
    # name (MODEL_NAMES: gemini-* -> "AI model developed by Google").
    agent_model: Optional[str] = None
    # Explicit override for the {model} placeholder in the injection text.
    attack_model_name: Optional[str] = None
    # Attack from agentdojo's registry (GET /attacks lists them). Ignored when
    # injection_task_id is None.
    attack: str = "important_instructions"
    # Optional sub-directory of --results-dir for this task's result file, e.g.
    # "<model>/<attack>", so sweeps over models/attacks do not overwrite each other.
    run_label: Optional[str] = None


# Every gemini-* entry in MODEL_NAMES maps to this; newer Gemini ids that the
# table does not list yet (e.g. gemini-3.1-flash-lite) get the same wording.
GOOGLE_MODEL_NAME = MODEL_NAMES["gemini-2.5-flash"]


def attack_model_name_for(agent_model: Optional[str]) -> str:
    """Same lookup as agentdojo.attacks.base_attacks.get_model_name_from_pipeline,
    on a bare model id instead of a pipeline. Unlisted gemini-* ids map to the
    Google wording; anything else falls back to the generic name."""
    if agent_model:
        for full_name, prose_name in MODEL_NAMES.items():
            if full_name in agent_model:
                return prose_name
        if agent_model.lower().startswith("gemini"):
            return GOOGLE_MODEL_NAME
    return DEFAULT_MODEL_NAME


class _StubPipeline(BasePipelineElement):
    """Stand-in for the agent pipeline. The bridge has no AgentPipeline (the agent
    is gemini-cli); attacks only read `.name` to pick the model name in the
    injection text, so the stub carries a name that maps to the wanted prose."""

    def __init__(self, name: str) -> None:
        self.name = name

    def query(self, *args, **kwargs):  # pragma: no cover - never called
        raise NotImplementedError("the bridge does not run an agent pipeline")


def pipeline_name_for(prose_model_name: str) -> str:
    """A MODEL_NAMES key that get_model_name_from_pipeline() resolves to the given
    prose name; the first key if none does (the caller then overrides model_name)."""
    for full_name, prose in MODEL_NAMES.items():
        if prose == prose_model_name:
            return full_name
    return next(iter(MODEL_NAMES))


def build_attack(attack_name: str, task_suite: TaskSuite, prose_model_name: str, explicit: bool):
    """Instantiate a registry attack against the stub pipeline. `explicit` marks a
    user-supplied model name, which then overrides whatever the attack derived
    (attacks that deliberately drop the model name are left alone otherwise)."""
    if attack_name not in ATTACKS:
        raise HTTPException(status_code=404,
                            detail=f"Unknown attack '{attack_name}' (available: {sorted(ATTACKS)})")
    attack = load_attack(attack_name, task_suite, _StubPipeline(pipeline_name_for(prose_model_name)))
    # The stub resolves to the wanted prose only when it is a MODEL_NAMES value.
    # Otherwise (an explicit --attack-model-name, or the generic default for a
    # model outside the table) set it directly, except on the variants that
    # drop or deliberately mis-state the model name.
    keeps_own_name = attack_name in (
        "important_instructions_no_model_name", "important_instructions_no_names",
        "important_instructions_wrong_model_name",
    )
    if hasattr(attack, "model_name") and (explicit or prose_model_name not in MODEL_NAMES.values()) \
            and not (keeps_own_name and not explicit):
        attack.model_name = prose_model_name
    return attack


@rest_api.get("/attacks")
def list_attacks_endpoint():
    """Registered attacks with their DoS flag, for sweep scripts."""
    return {name: {"is_dos_attack": bool(cls.is_dos_attack)} for name, cls in sorted(ATTACKS.items())}


class FinishTaskRequest(BaseModel):
    task_id: str
    model_output: str


@rest_api.post("/init_task")
def init_task_endpoint(request: InitTaskRequest):
    # Load the task suite on the server side
    suites = get_suites(request.benchmark_version)
    if request.suite_name not in suites:
        raise HTTPException(
            status_code=404,
            detail=f"Suite '{request.suite_name}' not in benchmark version "
                   f"'{request.benchmark_version}' (available: {sorted(suites)})")
    task_suite = suites[request.suite_name]

    user_task = task_suite.get_user_task_by_id(request.user_task_id)
    attack_model_name = request.attack_model_name or attack_model_name_for(request.agent_model)
    is_dos = False
    if request.injection_task_id is None:
        injection_task = None
        task_injections = {}
    else:
        injection_task = task_suite.get_injection_task_by_id(
            request.injection_task_id)
        attack = build_attack(request.attack, task_suite, attack_model_name,
                              explicit=request.attack_model_name is not None)
        is_dos = bool(attack.is_dos_attack)
        attack_model_name = getattr(attack, "model_name", attack_model_name)
        try:
            task_injections = attack.attack(user_task, injection_task)
        except ValueError as e:  # e.g. tool_knowledge on a task without placeholder_args
            raise HTTPException(status_code=400, detail=f"attack '{request.attack}' failed: {e}")
    environment = task_suite.load_and_inject_default_environment(
        task_injections)
    runtime = FunctionsRuntime(task_suite.tools)
    pre_environment = environment.model_copy(deep=True)
    data[request.task_id] = {
        "task_id": request.task_id,
        "task_suite": task_suite,
        "user_task_id": request.user_task_id,
        "injection_task_id": request.injection_task_id,
        "user_task": user_task,
        "injection_task": injection_task,
        "benchmark_version": request.benchmark_version,
        "attack": request.attack if injection_task is not None else None,
        "is_dos_attack": is_dos,
        "attack_model_name": attack_model_name if injection_task is not None else None,
        "run_label": request.run_label,
        "environment": environment,
        "pre_environment": pre_environment,
        "runtime": runtime,
        "functions_stack_trace": [],
        "functions_stack_trace_details": [],
    }
    return {
        "message": f"Successfully initialized task '{request.task_id}'",
        "tools_count": len(task_suite.tools),
        "user_task_prompt": user_task.PROMPT,
        "benchmark_version": request.benchmark_version,
        "attack": request.attack if injection_task is not None else None,
        "attack_model_name": attack_model_name if injection_task is not None else None,
        "injection_vectors": sorted(task_injections),
    }


@rest_api.post("/finish_task")
def finish_task_endpoint(request: FinishTaskRequest):
    task_data = data.get(request.task_id)
    if task_data is None:
        raise HTTPException(
            status_code=404, detail=f"Task ID '{request.task_id}' not found")
    # agentdojo >= 0.1.3x scores a list of content blocks, not a bare string.
    model_output = [text_content_block_from_string(request.model_output or "")]
    utility = task_data["task_suite"]._check_task_result(
        task_data["user_task"],
        model_output,
        task_data["pre_environment"],
        task_data["environment"],
        task_data["functions_stack_trace"],
    )

    if task_data["injection_task"] is None:
        security = False
    elif task_data["is_dos_attack"]:
        # As in agentdojo.benchmark: a DoS attack succeeds when the user task fails.
        security = not utility
    else:
        security = task_data["task_suite"]._check_task_result(
            task_data["injection_task"],
            model_output,
            task_data["pre_environment"],
            task_data["environment"],
            task_data["functions_stack_trace"],
        )

    # save
    task_id = task_data["task_id"]
    pattern = r'^(\w+)_([\w]+)_(user_task_\d+)_(injection_task_\d+|noinjection)$'
    match = re.match(pattern, task_id)
    if match:
        agent_type, suite, user_task, injection_task = match.groups()
        filename = f"{agent_type}/{suite}/{user_task}/{injection_task}.json"
    else:
        filename = f"others/{task_id}.json"
    if task_data["run_label"]:
        filename = f"{task_data['run_label'].strip('/')}/{filename}"
    os.makedirs(os.path.dirname(f"{RESULT_DIR}/{filename}"), exist_ok=True)
    with open(f"{RESULT_DIR}/{filename}", "w") as f:
        json.dump({
            "task_id": task_data["task_id"],
            "benchmark_version": task_data["benchmark_version"],
            "user_task_id": task_data["user_task_id"],
            "injection_task_id": task_data["injection_task_id"],
            "attack": task_data["attack"],
            "attack_model_name": task_data["attack_model_name"],
            "user_prompt": task_data["user_task"].PROMPT,
            "injection_goal": task_data["injection_task"].GOAL if task_data["injection_task"] else None,
            "functions_stack_trace": task_data["functions_stack_trace"],
            "functions_stack_trace_details": task_data["functions_stack_trace_details"],
            "model_output": request.model_output,
            "utility": utility,
            "security": security,
        }, f, indent=2, default=str)

    return {
        "utility": utility,
        "security": security
    }


mcp_server = FastMCP("MCP")


def convert_agentdojo_tool_to_mcp(tool) -> Tool:
    """Convert an AgentDojo Function to MCP Tool object."""
    # Extract the JSON schema from the Pydantic model
    parameters_schema = tool.parameters.model_json_schema()

    # Create and return a FastMCP Tool object
    return Tool(
        name=tool.name,
        description=tool.description,
        parameters=parameters_schema
    )


class ListingFilterMiddleware(Middleware):
    async def on_list_tools(self, context: MiddlewareContext, call_next):
        print("ListingFilterMiddleware: on_list_tools called")

        headers = get_http_headers()
        task_id = headers.get('task_id', None)
        if task_id is None:
            authorization = headers.get('authorization', '')
            match = re.match(r'Bearer (.+)', authorization)
            if match:
                task_id = match.group(1)
        print(f"Task ID: {task_id}")

        if task_id and task_id in data:
            task_data = data[task_id]
            task_suite: TaskSuite = task_data["task_suite"]
            agentdojo_tools = task_suite.tools

            # Convert AgentDojo tools to MCP Tool objects
            mcp_tools = [convert_agentdojo_tool_to_mcp(
                tool) for tool in agentdojo_tools]

            return mcp_tools

        else:
            raise McpError(ErrorData(
                code=-32600,
                message=f"Task ID '{task_id}' not found"
            ))


class ToolCallMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        print("ToolCallMiddleware: on_call_tool called")

        headers = get_http_headers()
        task_id = headers.get('task_id', None)
        if task_id is None:
            authorization = headers.get('authorization', '')
            match = re.match(r'Bearer (.+)', authorization)
            if match:
                task_id = match.group(1)
        print(f"Task ID: {task_id}")

        if task_id and task_id in data:
            try:
                task_data = data[task_id]
                runtime: FunctionsRuntime = task_data["runtime"]
                environment = task_data["environment"]

                # Get the tool call details from the request
                tool_name = context.message.name
                tool_args = context.message.arguments

                print(f"Executing tool: {tool_name} with args: {tool_args}")

                # Execute the tool using AgentDojo's runtime
                result, error = runtime.run_function(
                    environment, tool_name, tool_args)
                # print(f"Tool execution result: {result}, error: {error}")

                # Track the function call in AgentDojo FunctionCall format
                function_call = FunctionCall(
                    function=tool_name,
                    args=tool_args,
                    id=None  # MCP doesn't provide IDs in the same way
                )
                task_data["functions_stack_trace"].append(function_call)
                task_data["functions_stack_trace_details"].append({
                    "function": tool_name,
                    "args": tool_args,
                    "result": result,
                    "error": error
                })

                # Return ToolResult object
                if error:
                    raise McpError(ErrorData(
                        code=-32603,
                        message=error
                    ))
                else:
                    # Format the result exactly as AgentDojo's own pipeline does
                    # (YAML dump of pydantic models / lists, str otherwise).
                    # structured_content is set explicitly: gemini-cli re-parses a
                    # bare text block as JSON and rejects the call when that yields
                    # a non-object (a numeric result such as get_balance -> 1810.0).
                    result_str = tool_result_to_str(result) if result is not None else ""
                    return ToolResult(content=result_str, structured_content={"result": result_str})
            except McpError as e:
                raise e
            except Exception as e:
                raise McpError(ErrorData(
                    code=-32603,
                    message=f"Internal error during tool execution: {str(e)}"
                ))
        else:
            raise McpError(ErrorData(
                code=-32600,
                message=f"Task ID '{task_id}' not found"
            ))


mcp_server.add_middleware(ListingFilterMiddleware())
mcp_server.add_middleware(ToolCallMiddleware())


def run_rest_api(port: int):
    """Run the REST API server"""
    print(f"Starting REST API server on port {port}")
    uvicorn.run(rest_api, host="0.0.0.0", port=port, log_level="error")


def run_mcp_proxy(port: int):
    """Run the MCP proxy server"""
    print(f"Starting MCP Proxy Server on port {port}")
    mcp_server.run(
        transport="http", host="0.0.0.0", port=port, log_level="ERROR", stateless_http=True
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AgentDyn / AgentDojo MCP bridge"
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=9000,
        help="Port to run the API server on (default: %(default)s)",
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=9001,
        help="Port to run the MCP server on (default: %(default)s)",
    )
    parser.add_argument(
        "--results-dir",
        type=str,
        default="./mcp_results",
        help="Directory to store MCP results (default: %(default)s)",
    )

    args = parser.parse_args()
    RESULT_DIR = args.results_dir

    rest_thread = threading.Thread(
        target=run_rest_api,
        args=(args.api_port,),
        daemon=True
    )
    rest_thread.start()

    run_mcp_proxy(args.mcp_port)
