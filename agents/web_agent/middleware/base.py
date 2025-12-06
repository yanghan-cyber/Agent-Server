from datetime import datetime
from langchain.agents.middleware import AgentMiddleware
from langchain.messages import RemoveMessage  

class WebAgentMiddleware(AgentMiddleware):
    def __init__(self, max_iterations: int = 20):
        self.max_iterations = max_iterations
        self.iteration_count = 0

    def before_agent(self, state, runtime):
        
        return self.inject_env()
    
    def before_model(self, state, runtime):
        self.iteration_count += 1
        if (self.iteration_count < self.max_iterations):
            if (self.max_iterations-self.iteration_count) < 3:
                content = f"<system-reminder>You only have {self.max_iterations-self.iteration_count} more rounds left to complete the task.</system-reminder>"
                return {
                    "messages": [
                        {"role": "user", "content": content}
                    ]
                }
        else:
            content = "<system-reminder>You have reached the maximum number of iterations. Please MUST complete the task based on the information obtained and never call other tools.</system-reminder>"
            return {
                "messages": [
                    {"role": "user", "content": content}
                ]
            }

    
    def inject_env(self) -> str:
    # 在模型调用前添加系统提示
        inject_datetime = f"""<env>Current Datetime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</env>"""
        return {
            "messages": [
                {"role": "user", "content": inject_datetime}
            ]
        }