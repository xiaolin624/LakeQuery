import logging

import gradio as gr
import httpx

logger = logging.getLogger(__name__)

API_BASE = "http://localhost:8000/api/v1"

# ── Wes Anderson Pastel Theme (custom CSS) ──────────────────────────────────

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&family=Lora:ital,wght@0,400;0,500;1,400&display=swap');

:root {
    --pastel-pink:    #F2C4CE;
    --pastel-blue:    #A8D8EA;
    --pastel-yellow:  #FFEEAD;
    --pastel-cream:   #FFF8F0;
    --pastel-sage:    #C9E4C5;
    --warm-brown:     #8B6F47;
    --deep-rose:      #C4727F;
    --muted-navy:     #5B7B8A;
    --film-grain:     #FAF3EB;
}

body, .gradio-container {
    background-color: var(--film-grain) !important;
    font-family: 'Lora', 'Georgia', serif !important;
}

/* ── Header ─────────────────────────────────────────── */
#header-row {
    text-align: center;
    padding: 1.2rem 0 0.6rem 0;
    border-bottom: 2px solid var(--pastel-pink);
    margin-bottom: 0.8rem;
}
#header-row h1 {
    font-family: 'Playfair Display', serif !important;
    color: var(--warm-brown) !important;
    font-size: 2rem !important;
    letter-spacing: 0.15em;
    margin: 0 !important;
}
#header-row p {
    color: var(--muted-navy);
    font-style: italic;
    font-size: 0.95rem;
    margin-top: 0.25rem;
}

/* ── Sidebar panel ──────────────────────────────────── */
#sidebar {
    background: linear-gradient(180deg, var(--pastel-cream) 0%, #FFF5EC 100%) !important;
    border: 1.5px solid var(--pastel-pink) !important;
    border-radius: 12px !important;
    padding: 1rem !important;
}
#sidebar .gr-block-label, #sidebar label {
    font-family: 'Playfair Display', serif !important;
    color: var(--warm-brown) !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

/* ── Chatbot area ───────────────────────────────────── */
#chatbot {
    border: 1.5px solid var(--pastel-blue) !important;
    border-radius: 12px !important;
    background: white !important;
}
#chatbot .message.user {
    background: var(--pastel-yellow) !important;
    border-radius: 12px 12px 4px 12px !important;
    border: 1px solid #E8D89C !important;
    color: var(--warm-brown) !important;
}
#chatbot .message.bot {
    background: var(--pastel-blue) !important;
    border-radius: 12px 12px 12px 4px !important;
    border: 1px solid #8CC4D8 !important;
    color: #3A5A68 !important;
}

/* ── Input box ──────────────────────────────────────── */
#msg-input textarea {
    border: 1.5px solid var(--pastel-pink) !important;
    border-radius: 10px !important;
    background: var(--pastel-cream) !important;
    font-family: 'Lora', serif !important;
    font-size: 1rem !important;
    color: var(--warm-brown) !important;
}
#msg-input textarea:focus {
    border-color: var(--deep-rose) !important;
    box-shadow: 0 0 0 2px rgba(196, 114, 127, 0.2) !important;
}

/* ── Buttons ────────────────────────────────────────── */
#send-btn {
    background: var(--deep-rose) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-family: 'Playfair Display', serif !important;
    font-weight: 600 !important;
    letter-spacing: 0.08em;
    transition: all 0.2s ease;
}
#send-btn:hover {
    background: var(--warm-brown) !important;
    transform: translateY(-1px);
}
#clear-btn {
    background: transparent !important;
    border: 1.5px solid var(--pastel-sage) !important;
    color: var(--muted-navy) !important;
    border-radius: 10px !important;
    font-family: 'Lora', serif !important;
}

/* ── Dropdown / Radio ───────────────────────────────── */
#sidebar select, #sidebar input[type="text"] {
    border: 1px solid var(--pastel-pink) !important;
    border-radius: 8px !important;
    background: white !important;
    font-family: 'Lora', serif !important;
}

/* ── Symmetry accents ───────────────────────────────── */
.contain {
    max-width: 1100px !important;
    margin: 0 auto !important;
}

/* ── Footer ─────────────────────────────────────────── */
#footer-row {
    text-align: center;
    padding-top: 0.5rem;
    border-top: 1px solid var(--pastel-pink);
    margin-top: 0.5rem;
}
#footer-row p {
    color: var(--muted-navy);
    font-size: 0.8rem;
    font-style: italic;
    letter-spacing: 0.05em;
}
"""


async def _call_api(question: str, dialect: str, catalog: str) -> dict:
    """通过 HTTP 调用 FastAPI 后端"""
    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        resp = await client.post(
            f"{API_BASE}/query",
            json={
                "question": question,
                "dialect": dialect,
                "catalog": catalog,
            },
        )
        resp.raise_for_status()
        return resp.json()


def _format_response(data: dict) -> str:
    """将 API 返回格式化为聊天消息"""
    if data.get("error"):
        return f"**查询失败**\n\n{data['error']}"

    parts = []
    if data.get("sql"):
        parts.append(f"**生成的 SQL：**\n```sql\n{data['sql']}\n```")
    if data.get("dialect"):
        parts.append(f"**目标方言：** `{data['dialect']}`")
    if data.get("tables_used"):
        parts.append(f"**涉及的表：** {', '.join(data['tables_used'])}")
    parts.append(f"**校验通过：** {'✓' if data.get('validation_passed') else '✗'}")
    if data.get("retry_count", 0) > 0:
        parts.append(f"**重试次数：** {data['retry_count']}")

    return "\n\n".join(parts)


async def chat_fn(message: str, history: list, dialect: str, catalog: str):
    """Gradio 聊天回调"""
    if not message.strip():
        return history, ""

    history = history + [{"role": "user", "content": message}]

    try:
        data = await _call_api(message, dialect, catalog)
        reply = _format_response(data)
    except httpx.HTTPStatusError as e:
        reply = f"**请求错误：** HTTP {e.response.status_code}"
    except httpx.ConnectError:
        reply = "**连接失败：** 无法连接到后端服务，请确认 FastAPI 已启动（端口 8000）"
    except Exception as e:
        reply = f"**未知错误：** {e}"

    history = history + [{"role": "assistant", "content": reply}]
    return history, ""


def create_ui() -> gr.Blocks:
    with gr.Blocks(title="LakeQuery") as demo:
        # ── Header ──
        with gr.Row(elem_id="header-row"):
            gr.HTML(
                "<h1>✦ LAKEQUERY ✦</h1>"
                "<p>Natural Language to SQL — the lakehouse way</p>"
            )

        # ── Main layout: sidebar + chat ──
        with gr.Row():
            # Sidebar (left)
            with gr.Column(scale=1, min_width=220, elem_id="sidebar"):
                gr.HTML("<p style='text-align:center;margin:0 0 0.6rem 0;'>⚙ Parameters</p>")
                dialect = gr.Dropdown(
                    choices=["hive", "spark", "trino", "duckdb", "presto"],
                    value="hive",
                    label="Target Dialect",
                    interactive=True,
                )
                catalog = gr.Dropdown(
                    choices=["default"],
                    value="default",
                    label="Catalog",
                    interactive=True,
                )
                clear_btn = gr.Button("Clear History", elem_id="clear-btn")

            # Chat area (center)
            with gr.Column(scale=4):
                chatbot = gr.Chatbot(
                    elem_id="chatbot",
                    height=520,
                    buttons=["copy"],
                    placeholder='在下方输入自然语言查询，例如："查下昨天各省的 DAU"',
                )
                with gr.Row():
                    msg = gr.Textbox(
                        placeholder="输入你的取数需求…",
                        show_label=False,
                        scale=5,
                        elem_id="msg-input",
                    )
                    send_btn = gr.Button("发送 →", elem_id="send-btn", scale=1)

        # ── Footer ──
        with gr.Row(elem_id="footer-row"):
            gr.HTML("<p>Crafted with symmetry & pastel hues — inspired by the films of Wes Anderson</p>")

        # ── Events ──
        send_btn.click(
            fn=chat_fn,
            inputs=[msg, chatbot, dialect, catalog],
            outputs=[chatbot, msg],
        )
        msg.submit(
            fn=chat_fn,
            inputs=[msg, chatbot, dialect, catalog],
            outputs=[chatbot, msg],
        )
        clear_btn.click(fn=lambda: ([], ""), outputs=[chatbot, msg])

    return demo


def main():
    demo = create_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860, css=CUSTOM_CSS)


if __name__ == "__main__":
    main()
