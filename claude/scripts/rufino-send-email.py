#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────
#  Rufino — Email helper
#  Manda email via Gmail SMTP (smtp.gmail.com:587 STARTTLS) leyendo
#  el app-password del macOS Keychain.
#
#  Usado por los outputs de Fase 5: weekly digest, bio mensual,
#  year-in-review.
#
#  Keychain entry esperada:
#    security add-generic-password \
#      -s rufino-gmail-app-password \
#      -a val \
#      -w '<16-char-app-password>' -U
#
#  Uso:
#    rufino-send-email.py --to me@example.com --subject "..." --body-plain "..."
#    rufino-send-email.py --to me@example.com --subject "..." --body-html "<p>...</p>"
#    rufino-send-email.py --to me@example.com --subject "..." --html-from-md /path/digest.md
#
#  Exit 0 OK, 1 si falla (con mensaje al stderr).
# ─────────────────────────────────────────────────────────────
import argparse
import os
import re
import smtplib
import ssl
import subprocess
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


DEFAULT_FROM = "valentinoerrandonea2002@gmail.com"
KEYCHAIN_SERVICE = "rufino-gmail-app-password"
KEYCHAIN_ACCOUNT = "val"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def fetch_app_password() -> str:
    """Lee el app-password de Gmail del macOS Keychain."""
    if not os.path.exists("/usr/bin/security"):
        die("/usr/bin/security no existe — esta tool requiere macOS Keychain.")
    try:
        out = subprocess.check_output(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                KEYCHAIN_ACCOUNT,
                "-w",
            ],
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError:
        die(
            "app password no está en Keychain. Generá uno en "
            "https://myaccount.google.com/apppasswords y guardalo con: "
            "security add-generic-password -s rufino-gmail-app-password "
            "-a val -w '<16-char-pwd>' -U"
        )
    pwd = out.decode("utf-8").strip()
    if not pwd:
        die("Keychain devolvió un app password vacío.")
    return pwd


# ─────────────────────────────────────────────────────────────
#  Markdown → HTML (regex-based, sin dependencias externas)
# ─────────────────────────────────────────────────────────────
#  Soporta:
#    - frontmatter YAML (lo descarta del cuerpo)
#    - # / ## / ### / #### headers
#    - listas con `-` o `*` y listas numeradas `1.`
#    - **bold** y _italic_ / *italic*
#    - inline `code`
#    - fenced ``` blocks
#    - wikilinks [[slug]] y [[slug|alias]]  → <code>alias</code>
#    - párrafos (bloques separados por blank line)
#    - separadores `---`
# ─────────────────────────────────────────────────────────────

def _strip_frontmatter(md: str) -> str:
    lines = md.splitlines()
    if not lines or lines[0].strip() != "---":
        return md
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1 :])
    return md


def _inline(text: str) -> str:
    # Wikilinks: [[slug|alias]] → alias, [[slug]] → slug — siempre como <code>
    text = re.sub(
        r"\[\[([^\]\|]+)\|([^\]]+)\]\]",
        lambda m: f"<code>{_escape(m.group(2))}</code>",
        text,
    )
    text = re.sub(
        r"\[\[([^\]]+)\]\]",
        lambda m: f"<code>{_escape(m.group(1))}</code>",
        text,
    )
    # Inline code `x`
    text = re.sub(
        r"`([^`]+)`",
        lambda m: f"<code>{_escape(m.group(1))}</code>",
        text,
    )
    # Markdown links [text](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^\)]+)\)",
        lambda m: f'<a href="{_escape(m.group(2))}">{_escape(m.group(1))}</a>',
        text,
    )
    # Bold **x**
    text = re.sub(r"\*\*([^\*]+)\*\*", r"<strong>\1</strong>", text)
    # Italic _x_ o *x*
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"(?<!\*)\*([^\*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    return text


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def md_to_html(md: str) -> str:
    md = _strip_frontmatter(md)
    out = []
    in_code = False
    code_buf: list[str] = []
    in_ul = False
    in_ol = False
    para_buf: list[str] = []

    def flush_para():
        nonlocal para_buf
        if para_buf:
            joined = " ".join(line.strip() for line in para_buf)
            out.append(f"<p>{_inline(_escape_keep_inline(joined))}</p>")
            para_buf = []

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def _escape_keep_inline(s: str) -> str:
        # Escapamos pero después _inline corre y mete HTML válido.
        # Solución: escapamos primero, después _inline reconvierte sus
        # patrones usando los escapes ya hechos. Eso podría romperse con
        # *bold* etc — para mantenerlo simple, no escapamos texto antes
        # de _inline (asumimos que el markdown está bien formado y no
        # tiene HTML literal raro).
        return s

    for raw_line in md.splitlines():
        line = raw_line.rstrip()

        # Fenced code block
        if line.strip().startswith("```"):
            if in_code:
                out.append(
                    "<pre><code>"
                    + _escape("\n".join(code_buf))
                    + "</code></pre>"
                )
                code_buf = []
                in_code = False
            else:
                flush_para()
                close_lists()
                in_code = True
            continue
        if in_code:
            code_buf.append(raw_line)
            continue

        stripped = line.strip()

        # Blank line → cierra párrafo y listas
        if not stripped:
            flush_para()
            close_lists()
            continue

        # Horizontal rule
        if stripped in {"---", "***", "___"}:
            flush_para()
            close_lists()
            out.append("<hr />")
            continue

        # Headers
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            close_lists()
            level = len(m.group(1))
            content = _inline(m.group(2))
            out.append(f"<h{level}>{content}</h{level}>")
            continue

        # Unordered list
        m = re.match(r"^[\-\*]\s+(.*)$", stripped)
        if m:
            flush_para()
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        # Ordered list
        m = re.match(r"^\d+\.\s+(.*)$", stripped)
        if m:
            flush_para()
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        # Default → acumular para párrafo
        close_lists()
        para_buf.append(line)

    flush_para()
    close_lists()
    if in_code:
        # Code block sin cerrar — emitimos lo que hay
        out.append(
            "<pre><code>" + _escape("\n".join(code_buf)) + "</code></pre>"
        )

    body = "\n".join(out)
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        "<style>"
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "max-width:720px;margin:1em auto;padding:0 1em;color:#222;line-height:1.5}"
        "h1{font-size:1.6em;border-bottom:1px solid #ddd;padding-bottom:.3em}"
        "h2{font-size:1.3em;margin-top:1.5em}"
        "h3{font-size:1.1em}"
        "code{background:#f4f4f4;padding:0 .25em;border-radius:3px;"
        "font-family:'SF Mono',Menlo,Consolas,monospace;font-size:.9em}"
        "pre code{display:block;padding:.6em;overflow-x:auto}"
        "ul,ol{padding-left:1.4em}"
        "hr{border:none;border-top:1px solid #ddd;margin:1.5em 0}"
        "a{color:#0366d6}"
        "</style></head><body>"
        f"{body}"
        "</body></html>"
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Rufino — Gmail SMTP sender")
    p.add_argument("--to", required=True, help="Destinatario")
    p.add_argument("--subject", required=True, help="Subject")
    p.add_argument(
        "--from",
        dest="from_addr",
        default=DEFAULT_FROM,
        help=f"From (default {DEFAULT_FROM})",
    )
    body_group = p.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body-plain", help="Body en plain text")
    body_group.add_argument("--body-html", help="Body en HTML")
    body_group.add_argument(
        "--html-from-md", help="Path a .md — convierte a HTML"
    )
    args = p.parse_args()

    # Resolver body
    plain_body = ""
    html_body = ""

    if args.body_plain:
        plain_body = args.body_plain
        html_body = (
            "<html><body><pre>"
            + _escape(args.body_plain)
            + "</pre></body></html>"
        )
    elif args.body_html:
        html_body = args.body_html
        plain_body = re.sub(r"<[^>]+>", "", args.body_html)
    elif args.html_from_md:
        md_path = os.path.expanduser(args.html_from_md)
        if not os.path.isfile(md_path):
            die(f"markdown file no existe: {md_path}")
        try:
            with open(md_path, "r", encoding="utf-8") as fh:
                md = fh.read()
        except OSError as exc:
            die(f"no pude leer {md_path}: {exc}")
        plain_body = _strip_frontmatter(md)
        html_body = md_to_html(md)

    # Credenciales
    app_pwd = fetch_app_password()

    # Compose
    msg = MIMEMultipart("alternative")
    msg["Subject"] = args.subject
    msg["From"] = args.from_addr
    msg["To"] = args.to
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # SMTP STARTTLS
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            smtp.login(args.from_addr, app_pwd)
            smtp.sendmail(args.from_addr, [args.to], msg.as_string())
    except smtplib.SMTPAuthenticationError as exc:
        die(
            "auth falló contra Gmail. Verificá que el app password en "
            f"Keychain corresponda a {args.from_addr} y que 2FA esté "
            f"activado en esa cuenta. Detalle: {exc}"
        )
    except (smtplib.SMTPException, OSError) as exc:
        die(f"SMTP falló: {exc}")

    print(f"OK: email enviado a {args.to} (subject: {args.subject!r})")


if __name__ == "__main__":
    main()
