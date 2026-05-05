import sys
from dotenv import load_dotenv
from qa_agent.graph import build_graph

load_dotenv()


def main(pdf_path: str = "sample.pdf") -> dict:
    app = build_graph()
    final_state = app.invoke({"pdf_path": pdf_path})
    result = final_state["ui_response"]
    print(result)
    return result


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "sample.pdf"
    main(path)
