from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

load_dotenv()

def main():
    llm = ChatAnthropic(model="claude-sonnet-4-5")
    response = llm.invoke("Hello from Claude")
    print(response.content)

if __name__ == "__main__":
    main()