from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

def main():
    llm = ChatOpenAI(model="gpt-4o-mini")
    response = llm.invoke("Hello, LangChain!")
    print(response.content)

if __name__ == "__main__":
    main()