import { useState } from "react";

const REQUEST = "/api/respondents/auth/magic-login/request/";
const REDEEM = "/api/respondents/auth/magic-login/redeem/";
const LOGOUT = "/api/respondents/auth/logout/";
const LOGOUT_ALL = "/api/respondents/auth/logout-all/";

function csrfToken() {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function post(path, body) {
  const headers = { "Content-Type": "application/json" };
  const token = csrfToken();
  if (token) headers["X-CSRFToken"] = token;
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data = text;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  return { status: response.status, data };
}

const tokenFromLink = new URLSearchParams(window.location.search).get("token") ?? "";

export default function App() {
  const [email, setEmail] = useState("");
  const [token, setToken] = useState(tokenFromLink);
  const [log, setLog] = useState([]);

  async function run(label, path, body) {
    try {
      const result = await post(path, body);
      setLog((prev) => [{ label, ...result }, ...prev]);
    } catch (error) {
      setLog((prev) => [
        { label, status: "network", data: String(error) },
        ...prev,
      ]);
    }
  }

  return (
    <main>
      <h1>Respondent auth</h1>
      <p>
        Proxies to Django on port 8000. Create the respondent in admin first.
        The link in the mail uses whatever host you sent the request from.
        Open it, or paste the token. Mailpit is at{" "}
        <a href="http://127.0.0.1:8025">127.0.0.1:8025</a>. The session cookie
        is httpOnly, so it will not show up here.
      </p>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          run("request", REQUEST, { email });
        }}
      >
        <label>
          Email{" "}
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>{" "}
        <button type="submit">Request link</button>
      </form>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          run("redeem", REDEEM, { token });
        }}
      >
        <label>
          Token{" "}
          <input
            value={token}
            onChange={(event) => setToken(event.target.value)}
            required
            size={48}
          />
        </label>{" "}
        <button type="submit">Redeem</button>
      </form>

      <p>
        <button type="button" onClick={() => run("logout", LOGOUT)}>
          Logout
        </button>{" "}
        <button type="button" onClick={() => run("logout-all", LOGOUT_ALL)}>
          Logout everywhere
        </button>
      </p>

      <h2>Responses</h2>
      {log.length === 0 ? <p>None yet.</p> : null}
      <ul>
        {log.map((entry, index) => (
          <li key={index}>
            <strong>
              {entry.label} {entry.status}
            </strong>
            <pre>{JSON.stringify(entry.data, null, 2)}</pre>
          </li>
        ))}
      </ul>
    </main>
  );
}
