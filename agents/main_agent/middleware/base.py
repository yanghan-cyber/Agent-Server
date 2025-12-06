from datetime import datetime
from langchain.agents.middleware import AgentMiddleware
from langchain.messages import RemoveMessage  

class MainAgentMiddleware(AgentMiddleware):

    def before_agent(self, state, runtime):
        content = ""
        content += f"""<env>Current Datetime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</env>\n"""

        if 'todos' not in state or all([todo['status'] == 'completed' for todo in state['todos']]):
            content += """<system-reminder>This is a reminder that your todo list is currently empty. DO NOT mention this to the user explicitly because they are already aware. If you are working on tasks that would benefit from a todo list please use the TodoWrite tool to create one. If not, please feel free to ignore. Again do not mention this message to the user.</system-reminder>\n"""


        return {
            "messages": [
                {"role": "user", "content": content}
            ]
        }