import inspect
import json
from typing import Callable, Dict, Any, List, Optional
from pydantic import BaseModel

class ToolManager:
    """Manages the registration and execution of tools."""
    
    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._schemas: Dict[str, Dict[str, Any]] = {}
        
    def register(self, func: Callable):
        """Registers a tool function."""
        name = func.__name__
        self._tools[name] = func
        
        # Parse docstring for description
        doc = inspect.getdoc(func)
        description = doc.split('\n')[0] if doc else f"Tool: {name}"
        
        # Parse signature for parameters
        sig = inspect.signature(func)
        params = {
            "type": "object",
            "properties": {},
            "required": []
        }
        
        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue
                
            param_type = "string" # Default
            if param.annotation != inspect.Parameter.empty:
                if param.annotation == int:
                    param_type = "integer"
                elif param.annotation == float:
                    param_type = "number"
                elif param.annotation == bool:
                    param_type = "boolean"
                elif param.annotation == list or param.annotation == List:
                    param_type = "array"
                elif param.annotation == dict or param.annotation == Dict:
                    param_type = "object"
            
            params["properties"][param_name] = {"type": param_type}
            
            if param.default == inspect.Parameter.empty:
                params["required"].append(param_name)
                
        schema = {
            "name": name,
            "description": description,
            "parameters": params
        }
        
        self._schemas[name] = schema
        return func
        
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Returns the JSON schemas for all registered tools."""
        return list(self._schemas.values())
        
    async def execute_tool(self, name: str, **kwargs) -> Any:
        """Executes a registered tool with the given arguments."""
        if name not in self._tools:
            raise ValueError(f"Tool '{name}' not found.")
            
        func = self._tools[name]
        
        # Check if it's an async function
        if inspect.iscoroutinefunction(func):
            return await func(**kwargs)
        else:
            return func(**kwargs)

    def get_system_prompt_addition(self) -> str:
        """Generates a system prompt addition describing the available tools."""
        if not self._schemas:
            return ""
            
        prompt = (
            "You are a helpful assistant with access to tools. You can answer the user directly, or use a tool to fetch more information.\n"
            "You have access to the following tools:\n\n"
        )
        for schema in self.get_tool_schemas():
            prompt += f"- {schema['name']}: {schema['description']}\n"
            prompt += f"  Parameters: {json.dumps(schema['parameters'])}\n\n"
            
        prompt += (
            "To use a tool, you MUST output EXACTLY a `<tool_call>` tag containing a JSON object with 'name' and 'arguments' fields. "
            "For example:\n"
            "<tool_call>{\"name\": \"tool_name\", \"arguments\": {\"param1\": \"value1\"}}</tool_call>\n"
            "After you use a tool, the system will execute it and provide the result. DO NOT output anything else after the </tool_call> tag. Wait for the result.\n"
        )
        return prompt
        
    def generate_gbnf_grammar(self) -> str:
        """Generates a strict GBNF grammar string based on the registered tools."""
        if not self._schemas:
            return ""
            
        grammar = r'''
root ::= (text | tool_call)*
text ::= [^<]+
tool_call ::= "<tool_call>" ws tool_choice ws "</tool_call>"
'''
        
        tools = self.get_tool_schemas()
        tool_choices = []
        
        for i, schema in enumerate(tools):
            name = schema["name"]
            params = schema["parameters"].get("properties", {})
            
            rule_name = f"tool_{i}"
            tool_choices.append(rule_name)
            
            args_parts = []
            for prop_name, prop_data in params.items():
                if prop_data.get("type") in ["integer", "number"]:
                    val_rule = "number"
                elif prop_data.get("type") == "boolean":
                    val_rule = "boolean"
                elif prop_data.get("type") == "array":
                    val_rule = "array"
                else:
                    val_rule = "string"
                    
                prop_rule = f'ws "\\"{prop_name}\\"" ws ":" ws {val_rule}'
                args_parts.append(prop_rule)
                
            if args_parts:
                args_str = f' ws "," ws '.join(args_parts)
                args_rule = f'"\\"arguments\\":" ws "{{" {args_str} ws "}}"'
            else:
                args_rule = f'"\\"arguments\\":" ws "{{}}"'
                
            rule_def = f'{rule_name} ::= "{{\\"name\\": \\"{name}\\", " ws {args_rule} ws "}}"'
            grammar += f"\n{rule_def}"
            
        grammar += f"\n\ntool_choice ::= {' | '.join(tool_choices)}\n"
        
        grammar += r'''
boolean ::= "true" | "false"
string ::= "\"" ([^"\\] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F]))* "\""
number ::= "-"? ("0" | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [-+]? [0-9]+)?
array ::= "[" ws (string (ws "," ws string)*)? ws "]"
ws ::= [ \t\n\r]*
'''
        return grammar.strip()

# Global ToolManager instance
tool_manager = ToolManager()

def tool(func: Callable):
    """Decorator to register a function as a tool."""
    return tool_manager.register(func)
