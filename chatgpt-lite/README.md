# ChatGPT Lite

Optional local chat client for the Automation Toolkit's llama.cpp server.
Based on [blrchen/chatgpt-lite](https://github.com/blrchen/chatgpt-lite), MIT
licensed; see [LICENSE](LICENSE). The model, chat history and UI are separate:
llama.cpp serves the model, and this app stores conversations in the browser.

From the toolkit root, with Node.js 22+ and npm:

```bash
bash setup.sh chat-lite status
bash setup.sh chat-lite build --yes
bash setup.sh chat-lite serve --yes
```

For a background service, use **Local AI → ChatGPT Lite → Start in background**
or run `bash setup.sh chat-lite start --yes`. This requires a systemd user
manager and keeps the app available after you close the dashboard during the
user session. Stop it with `bash setup.sh chat-lite stop --yes` before rebuilding.

Open **http://127.0.0.1:3001**. The model picker discovers the current model
through llama.cpp on **http://127.0.0.1:8080/v1/models**. Start the separately
configured AI server if the picker reports **Server unavailable**, then press
**Refresh**. No API key or cloud inference provider is needed for this
loopback setup. Keep the app local; it has no user login. Use Open WebUI if
you need authenticated accounts.

```bash
bash setup.sh chat-lite debug --port 3002 --yes
```

Debug starts the development server with hot reload and redacted server
diagnostics. `GET /api/health` checks the client process; `GET /api/chat-models`
checks the client-to-llama.cpp connection. Build first to install the locked
dependencies. Debug has a separate browser origin when using a different port,
so it does not display chats stored under the production origin.

Web lookup defaults to off. Turning it on can send the current question to a
web provider; attachments and prior messages stay out of web lookup. Document
attachments are text inputs to the local model. This app does not migrate
existing external chat databases. Keep the browser origin stable to retain
access to browser-local chat history.
