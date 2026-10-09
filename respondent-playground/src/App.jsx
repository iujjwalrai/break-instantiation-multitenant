import { useState } from "react";

const STAFF_LOGIN = "/api/staff/login/";
const STAFF_LOGOUT = "/api/staff/logout/";
const STAFF_ME = "/api/staff/me/";
const STAFF_ADMINS = "/api/staff/admins/";
const CLIENTS = "/api/clients/";
const MAGIC_REQUEST = "/api/clients/auth/magic-login/request/";
const MAGIC_REDEEM = "/api/clients/auth/magic-login/redeem/";
const INVITE_REDEEM = "/api/clients/auth/invites/redeem/";
const LOGOUT = "/api/clients/auth/logout/";
const LOGOUT_ALL = "/api/clients/auth/logout-all/";

function csrfToken() {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function call(path, { method = "POST", body } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = csrfToken();
  if (token) headers["X-CSRFToken"] = token;
  const response = await fetch(path, {
    method,
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

const params = new URLSearchParams(window.location.search);
const tokenFromLink = params.get("token") ?? "";
const linkIsInvite = window.location.pathname.startsWith("/invite");

export default function App() {
  const [staffEmail, setStaffEmail] = useState("test@test.com");
  const [staffPassword, setStaffPassword] = useState("test");
  const [fullName, setFullName] = useState("");
  const [clientEmail, setClientEmail] = useState("");
  const [clientId, setClientId] = useState("");
  const [magicEmail, setMagicEmail] = useState("");
  const [token, setToken] = useState(tokenFromLink);
  const [log, setLog] = useState([]);

  async function run(label, path, options) {
    try {
      const result = await call(path, options);
      setLog((prev) => [{ label, ...result }, ...prev]);
      return result;
    } catch (error) {
      setLog((prev) => [
        { label, status: "network", data: String(error) },
        ...prev,
      ]);
      return null;
    }
  }

  return (
    <main>
      <h1>Client portal</h1>
      <p>
        Staff sign in, create a client profile, then send the invite. The
        mail link opens <code>/invite?token=</code> on this page. Redeeming
        it creates the client login. Later sign-ins use the magic link.
        Mailpit is at <a href="http://127.0.0.1:8025">127.0.0.1:8025</a>.
        Session cookies are httpOnly.
      </p>

      <h2>Staff</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          run("staff login", STAFF_LOGIN, {
            body: { email: staffEmail, password: staffPassword },
          });
        }}
      >
        <label>
          Email{" "}
          <input
            type="email"
            value={staffEmail}
            onChange={(event) => setStaffEmail(event.target.value)}
            required
          />
        </label>{" "}
        <label>
          Password{" "}
          <input
            type="password"
            value={staffPassword}
            onChange={(event) => setStaffPassword(event.target.value)}
            required
          />
        </label>{" "}
        <button type="submit">Log in</button>
      </form>
      <p>
        <button type="button" onClick={() => run("staff me", STAFF_ME, { method: "GET" })}>
          Who am I
        </button>{" "}
        <button type="button" onClick={() => run("staff logout", STAFF_LOGOUT)}>
          Log out
        </button>{" "}
        <button
          type="button"
          onClick={() => run("list admins", STAFF_ADMINS, { method: "GET" })}
        >
          List admins
        </button>
      </p>

      <h2>Client profile</h2>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const result = await run("create client", CLIENTS, {
            body: { full_name: fullName, email: clientEmail },
          });
          if (result && result.data && result.data.id) {
            setClientId(result.data.id);
          }
        }}
      >
        <label>
          Name{" "}
          <input
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            required
          />
        </label>{" "}
        <label>
          Email{" "}
          <input
            type="email"
            value={clientEmail}
            onChange={(event) => setClientEmail(event.target.value)}
            required
          />
        </label>{" "}
        <button type="submit">Create profile</button>
      </form>
      <p>
        <button
          type="button"
          onClick={() => run("list clients", CLIENTS, { method: "GET" })}
        >
          List clients
        </button>
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          run("send invite", `${CLIENTS}${clientId}/invite/`);
        }}
      >
        <label>
          Client id{" "}
          <input
            value={clientId}
            onChange={(event) => setClientId(event.target.value)}
            required
            size={40}
          />
        </label>{" "}
        <button type="submit">Send invite</button>
      </form>

      <h2>Client sign-in</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          run("magic request", MAGIC_REQUEST, { body: { email: magicEmail } });
        }}
      >
        <label>
          Email{" "}
          <input
            type="email"
            value={magicEmail}
            onChange={(event) => setMagicEmail(event.target.value)}
            required
          />
        </label>{" "}
        <button type="submit">Request magic link</button>
      </form>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const path = linkIsInvite ? INVITE_REDEEM : MAGIC_REDEEM;
          run(linkIsInvite ? "redeem invite" : "redeem magic link", path, {
            body: { token },
          });
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
        <button type="submit">
          {linkIsInvite ? "Redeem invite" : "Redeem magic link"}
        </button>
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
