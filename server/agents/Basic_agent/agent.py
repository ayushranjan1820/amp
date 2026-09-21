import os
from pathlib import Path
from typing import Dict, Optional

from langchain_classic.memory import ConversationBufferMemory

from agents.session_memory import memory_for_session
from .tools import tools_list
from .ai_service import ai_service

# Load .env from the server root directory (PwC GenAI keys stripped — agent config only)
if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    env_path = Path(__file__).parent.parent.parent / '.env'
    load_dotenv_then_scrub_pwc(dotenv_path=env_path)


class BasicAgent:
    """A basic agent that can use tools to answer queries."""
    
    def __init__(self):
        """Initialize the Basic Agent with PwC GenAI service."""
        print("🔌 Using PwC GenAI service")
        self.ai_service = ai_service
        self._conversation_by_session: Dict[str, ConversationBufferMemory] = {}
        self.tools = tools_list
        
    def invoke_tool(self, tool_name: str, tool_input: str):
        """Invoke a tool by name and input."""
        for tool in self.tools:
            if tool.name == tool_name:
                try:
                    result = tool.invoke(tool_input)
                    return result
                except Exception as e:
                    return f"Error invoking {tool_name}: {str(e)}"
        return f"Tool '{tool_name}' not found"
    
    def get_tools_description(self):
        """Get description of all available tools."""
        descriptions = []
        for tool in self.tools:
            descriptions.append(f"- {tool.name}: {tool.description}")
        return "\n".join(descriptions)
    
    def process_query(
        self,
        user_input: str,
        clear_history: bool = False,
        session_id: Optional[str] = None,
    ) -> dict:
        """Process a user query and return the response with thinking steps."""
        thinking_steps = []

        memory = memory_for_session(self._conversation_by_session, session_id)

        if clear_history:
            memory.clear()

        # Build system message with tools
        try:
            from agents.source_citation_mandate import MANDATORY_MARKDOWN_SOURCE_LINKS
            _cite = f"\n\n{MANDATORY_MARKDOWN_SOURCE_LINKS}"
        except Exception:
            _cite = ""
        system_message = f"""You are a helpful AI assistant with access to the following tools:

{self.get_tools_description()}

When you need to use a tool, respond in this format:
TOOL_NAME: <tool_name>
TOOL_INPUT: <tool_input>
RESPONSE: <your explanation>

If you don't need a tool, just respond normally.{_cite}"""
        
        # Get conversation history
        conversation_history = ""
        if hasattr(memory, 'chat_memory') and memory.chat_memory.messages:
            for msg in memory.chat_memory.messages:
                role = "User" if msg.type == "human" else "Assistant"
                conversation_history += f"{role}: {msg.content}\n"
        
        # Add user input to memory
        memory.chat_memory.add_user_message(user_input)
        
        # Step 1: Analyzing query
        thinking_steps.append({
            "type": "thinking",
            "content": f"Analyzing query: '{user_input[:100]}...' and determining if tools are needed",
            "tool_name": None,
            "tool_input": None
        })
        
        # Generate initial response using PwC GenAI
        prompt = f"{system_message}\n\nConversation History:\n{conversation_history}\n\nUser: {user_input}\n\nAssistant:"
        response = self.ai_service.call_genai(prompt, temperature=0.7)
        
        # Check if tool usage is needed
        if "TOOL_NAME:" in response and "TOOL_INPUT:" in response:
            lines = response.split("\n")
            tool_name = None
            tool_input = None
            
            for line in lines:
                if "TOOL_NAME:" in line:
                    tool_name = line.split("TOOL_NAME:")[1].strip().lower()
                elif "TOOL_INPUT:" in line:
                    tool_input = line.split("TOOL_INPUT:")[1].strip()
            
            if tool_name and tool_input:
                # Add thinking step for tool selection
                thinking_steps.append({
                    "type": "thinking",
                    "content": f"Decided to use tool: {tool_name}",
                    "tool_name": None,
                    "tool_input": None
                })
                
                # Add tool call step
                thinking_steps.append({
                    "type": "tool_call",
                    "content": f"Calling {tool_name}",
                    "tool_name": tool_name,
                    "tool_input": tool_input
                })
                
                # Invoke the tool
                tool_result = self.invoke_tool(tool_name, tool_input)
                
                # Add tool result step
                result_preview = str(tool_result)[:500] if tool_result else "No result"
                thinking_steps.append({
                    "type": "tool_result",
                    "content": result_preview,
                    "tool_name": tool_name,
                    "tool_input": None
                })
                
                # Add thinking step for final response generation
                thinking_steps.append({
                    "type": "thinking",
                    "content": "Processing tool results and generating final response",
                    "tool_name": None,
                    "tool_input": None
                })
                
                # Get final response from PwC GenAI with tool result
                final_prompt = f"{system_message}\n\nConversation History:\n{conversation_history}\n\nUser: {user_input}\n\nTool '{tool_name}' returned: {tool_result}\n\nAssistant:"
                final_response = self.ai_service.call_genai(final_prompt, temperature=0.7)
                
                # Add final response to memory
                memory.chat_memory.add_ai_message(final_response)
                
                return {
                    "response": final_response,
                    "thinking_steps": thinking_steps
                }
            else:
                # Add response to memory
                memory.chat_memory.add_ai_message(response)
                return {
                    "response": response,
                    "thinking_steps": thinking_steps
                }
        else:
            # No tool needed
            thinking_steps.append({
                "type": "thinking",
                "content": "No tools needed, responding directly",
                "tool_name": None,
                "tool_input": None
            })
            
            # Add response to memory
            memory.chat_memory.add_ai_message(response)
            return {
                "response": response,
                "thinking_steps": thinking_steps
            }


def invoke_tool(tool_name: str, tool_input: str):
    """Invoke a tool by name and input."""
    for tool in tools_list:
        if tool.name == tool_name:
            try:
                result = tool.invoke(tool_input)
                return result
            except Exception as e:
                return f"Error invoking {tool_name}: {str(e)}"
    return f"Tool '{tool_name}' not found"


def get_tools_description():
    """Get description of all available tools."""
    descriptions = []
    for tool in tools_list:
        descriptions.append(f"- {tool.name}: {tool.description}")
    return "\n".join(descriptions)


def main():
    """Main function to run the agent."""
    agent = BasicAgent()
    
    print("=" * 60)
    print("🤖 Langchain Agent with PwC GenAI")
    print("=" * 60)
    print("\nAvailable Tools:")
    print("  • web_search - Search the web for information")
    print("  • save_to_json - Save data to JSON files")
    print("  • export_to_pdf - Export content to PDF")
    print("  • get_weather - Get weather information")
    print("\nType 'quit' or 'exit' to stop the agent.")
    print("Type 'clear' to clear conversation history.\n")
    
    # Interactive loop
    while True:
        try:
            user_input = input("\n👤 You: ").strip()
            
            if user_input.lower() in ['quit', 'exit']:
                print("\n👋 Goodbye!")
                break
            
            if user_input.lower() == 'clear':
                agent._conversation_by_session.clear()
                print("✨ Conversation history cleared.\n")
                continue
            
            if not user_input:
                continue
            
            print("\n🤖 Agent is thinking...")
            
            # Process the query using the agent
            response = agent.process_query(user_input)
            print(f"🤖 Agent: {response}")
            
        except KeyboardInterrupt:
            print("\n\n👋 Agent stopped by user.")
            break
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()
            print("Please try again.\n")


# Create singleton instance for API usage
basic_agent = BasicAgent()


if __name__ == "__main__":
    main()
