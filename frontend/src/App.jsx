import { useEffect, useState } from "react";
import "./App.css";

const API = "http://127.0.0.1:8001";

const money = (value) =>
  Number(value || 0).toLocaleString("en-IN", {
    style: "currency",
    currency: "INR",
  });

function Field({ label, ...props }) {
  return (
    <label>
      {label}
      <input {...props} />
    </label>
  );
}

export default function App() {
  const [token, setToken] = useState(
    () => sessionStorage.getItem("worksphere_token") || ""
  );
  const [user, setUser] = useState(null);
  const [page, setPage] = useState("Dashboard");
  const [register, setRegister] = useState(false);
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [version, setVersion] = useState(0);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(null);
  const [unread, setUnread] = useState(0);

  const manager = user && ["ADMIN", "HR"].includes(user.role);

  function logout() {
    sessionStorage.removeItem("worksphere_token");
    setToken("");
    setUser(null);
    setRows([]);
    setSummary(null);
    setUnread(0);
    setPage("Dashboard");
    setEditing(null);
    setMessage("");
  }

  async function request(path, options = {}) {
    const headers = { ...options.headers };
    if (token) headers.Authorization = `Bearer ${token}`;

    let body = options.body;
    if (body && typeof body !== "string") {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }

    let response;
    try {
      response = await fetch(API + path, {
        ...options,
        headers,
        body,
        signal: AbortSignal.timeout(15000),
      });
    } catch {
      throw new Error(
        "Backend connect avvatledu. Port 8001 lo backend run cheyyi."
      );
    }

    const data = await response.json().catch(() => null);

    if (!response.ok) {
      if (response.status === 401 && token) logout();

      const detail = data?.detail;
      const text = Array.isArray(detail)
        ? detail.map((item) => item.msg).join("; ")
        : detail || "Request failed";

      throw new Error(`${response.status}: ${path} — ${text}`);
    }
    return data;
  }

  async function action(work, success) {
    setBusy(true);
    setMessage("");
    try {
      await work();
      setMessage(success);
      setVersion((value) => value + 1);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!token) return;
    let active = true;

    request("/auth/me")
      .then((data) => {
        if (active) setUser(data);
      })
      .catch((error) => {
        if (active) setMessage(error.message);
      });

    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    if (!user) return;
    let active = true;
    setLoading(true);
    setRows([]);
    setSummary(null);

    async function load() {
      try {
        if (page === "Dashboard") {
          const data = await request(
            manager ? "/analytics/summary" : "/employees/me"
          );
          if (active) setSummary(data);
        } else {
          const paths = {
            Employees: `/employees?search=${encodeURIComponent(search)}`,
            Attendance: "/attendance",
            Leaves: "/leaves",
            Payroll: "/payroll",
            Notifications: "/notifications",
            Users: "/admin/users",
          };
          const data = await request(paths[page]);
          if (active) setRows(data);
        }
      } catch (error) {
        if (active) setMessage(error.message);
      } finally {
        if (active) setLoading(false);
      }

      // Notification failure does not stop the selected page.
      try {
        const data = await request("/notifications/unread-count");
        if (active) setUnread(data.unread_count);
      } catch {
        if (active) setUnread(0);
      }
    }

    load();
    return () => {
      active = false;
    };
  }, [user, page, version, search]);

  async function authenticate(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await action(async () => {
      if (register) {
        await request("/auth/register", {
          method: "POST",
          body: {
            username: form.get("username"),
            email: form.get("email"),
            password: form.get("password"),
          },
        });
        setRegister(false);
      } else {
        const data = await request("/auth/login", {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: new URLSearchParams({
            username: form.get("username"),
            password: form.get("password"),
          }).toString(),
        });
        sessionStorage.setItem("worksphere_token", data.access_token);
        setPage("Dashboard");
        setToken(data.access_token);
      }
    }, register ? "Account created. Please log in." : "Logged in.");
  }

  function navigate(next) {
    setPage(next);
    setMessage("");
    setEditing(null);
    setSearch("");
  }

  function submitEmployee(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    if (!editing) data.user_id = Number(data.user_id);

    action(async () => {
      await request(editing ? `/employees/${editing.id}` : "/employees", {
        method: editing ? "PATCH" : "POST",
        body: data,
      });
      setEditing(null);
      form.reset();
    }, "Employee saved.");
  }

  function submitLeave(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    action(async () => {
      await request("/leaves", { method: "POST", body: data });
      form.reset();
    }, "Leave request submitted.");
  }

  function submitPayroll(event) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    data.employee_id = Number(data.employee_id);
    action(
      () => request("/payroll", { method: "POST", body: data }),
      "Payroll generated."
    );
  }

  function table(headers, render) {
    return (
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {headers.map((header) => <th key={header}>{header}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map(render)}
            {!rows.length && (
              <tr>
                <td colSpan={headers.length}>
                  {loading ? "Loading..." : "No records found."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    );
  }

  if (!token) {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <div className="brand">W / WorkSphere</div>
          <h1>{register ? "Create your account" : "Welcome back"}</h1>
          <p>Your people. Your workplace. One connected space.</p>
          {message && <div className="notice" role="status">{message}</div>}

          <form onSubmit={authenticate}>
            <Field label="Username" name="username" required
              minLength={3} maxLength={50}
              pattern="[a-zA-Z0-9_]+" autoComplete="username" />
            {register && (
              <Field label="Email" name="email" type="email" required />
            )}
            <Field label="Password" name="password" type="password"
              required minLength={8} maxLength={128}
              autoComplete={register ? "new-password" : "current-password"} />
            <button disabled={busy}>
              {busy ? "Please wait..." : register ? "Register" : "Log in"}
            </button>
          </form>

          <button className="secondary" disabled={busy}
            onClick={() => {
              setRegister(!register);
              setMessage("");
            }}>
            {register ? "Already registered? Log in" : "Create employee account"}
          </button>
        </section>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <p>{message || "Loading your account..."}</p>
          <button onClick={logout}>Back to login</button>
        </section>
      </main>
    );
  }

  const pages = [
    "Dashboard",
    ...(manager ? ["Employees"] : []),
    "Attendance",
    "Leaves",
    "Payroll",
    "Notifications",
    ...(user.role === "ADMIN" ? ["Users"] : []),
  ];

  return (
    <div className="app-layout">
      <aside>
        <div className="brand">W / WorkSphere</div>
        <p className="sidebar-caption">WORKSPACE</p>
        <nav>
          {pages.map((item) => (
            <button key={item}
              className={page === item ? "active" : ""}
              onClick={() => navigate(item)}>
              {item}
            </button>
          ))}
        </nav>
        <div className="account">
          <strong>{user.username}</strong>
          <small>{user.role}</small>
          <button onClick={logout}>Log out</button>
        </div>
      </aside>

      <main className="workspace">
        <header>
          <div>
            <p className="eyebrow">WORKSPHERE / {user.role}</p>
            <h1>{page}</h1>
          </div>
          <button className="secondary"
            onClick={() => navigate("Notifications")}>
            Notifications · {unread}
          </button>
        </header>

        {message && <div className="notice" role="status">{message}</div>}
        {loading && <p>Loading...</p>}

        <fieldset disabled={busy || loading} className="content-fieldset">
          {page === "Dashboard" && summary && (
            manager ? (
              <>
                <div className="kpi-grid">
                  {[
                    ["Total employees", summary.total_employees],
                    ["Active employees", summary.active_employees],
                    ["Present today", summary.attendance_today.PRESENT],
                    ["Pending leaves", summary.leave_statistics.PENDING],
                    ["Monthly payroll", money(summary.payroll_overview.net_salary)],
                    ["Attendance not marked", summary.attendance_today.not_marked],
                  ].map(([label, value]) => (
                    <article className="kpi" key={label}>
                      <span>{label}</span>
                      <strong>{value}</strong>
                    </article>
                  ))}
                </div>
                <section className="panel">
                  <h2>Employees by department</h2>
                  {summary.employees_by_department.map((item) => (
                    <div className="stat-row" key={item.department}>
                      <span>{item.department}</span>
                      <strong>{item.count}</strong>
                    </div>
                  ))}
                </section>
                <section className="panel">
                  <h2>Attendance · last 7 days</h2>
                  {summary.attendance_trend.map((item) => (
                    <div className="stat-row" key={item.date}>
                      <span>{item.date}</span>
                      <span>
                        Present {item.PRESENT} · Half day {item.HALF_DAY} · Absent {item.ABSENT}
                      </span>
                    </div>
                  ))}
                </section>
              </>
            ) : (
              <section className="panel">
                <h2>Hello, {summary.full_name}</h2>
                <p>{summary.designation} · {summary.department}</p>
                <p>Joined: {summary.joining_date}</p>
                <p>Basic salary: {money(summary.salary)}</p>
                <span className="badge">{summary.status}</span>
              </section>
            )
          )}

          {page === "Employees" && (
            <>
              <section className="panel">
                <h2>{editing ? "Edit employee" : "Add employee"}</h2>
                <form className="form-grid" onSubmit={submitEmployee}
                  key={editing?.id || "new"}>
                  {!editing && (
                    <Field label="Registered user ID" name="user_id"
                      type="number" min="1" required />
                  )}
                  <Field label="Full name" name="full_name" required
                    defaultValue={editing?.full_name} />
                  <Field label="Designation" name="designation" required
                    defaultValue={editing?.designation} />
                  <Field label="Department" name="department" required
                    defaultValue={editing?.department} />
                  <Field label="Joining date" name="joining_date"
                    type="date" required defaultValue={editing?.joining_date} />
                  <Field label="Monthly salary" name="salary"
                    type="number" min="0" step="0.01" required
                    defaultValue={editing?.salary} />
                  <label>Status
                    <select name="status" defaultValue={editing?.status || "ACTIVE"}>
                      <option>ACTIVE</option>
                      <option>INACTIVE</option>
                    </select>
                  </label>
                  <button>Save employee</button>
                  {editing && (
                    <button type="button" className="secondary"
                      onClick={() => setEditing(null)}>Cancel</button>
                  )}
                </form>
              </section>
              <Field label="Search name, designation or department"
                value={search} onChange={(event) => setSearch(event.target.value)} />
              {table(
                ["ID", "Name", "Department", "Designation", "Salary", "Status", "Action"],
                (item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td><td>{item.full_name}</td>
                    <td>{item.department}</td><td>{item.designation}</td>
                    <td>{money(item.salary)}</td><td>{item.status}</td>
                    <td><button onClick={() => setEditing(item)}>Edit</button></td>
                  </tr>
                )
              )}
            </>
          )}

          {page === "Attendance" && (
            <>
              <section className="panel">
                <h2>Track your working day</h2>
                <p>8 hours or more: present. Less than 8 hours: half day after checkout.</p>
                <div className="actions">
                  <button onClick={() => action(
                    () => request("/attendance/check-in", { method: "POST" }),
                    "Checked in."
                  )}>Check in</button>
                  <button onClick={() => action(
                    () => request("/attendance/check-out", { method: "POST" }),
                    "Checked out."
                  )}>Check out</button>
                </div>
                {manager && (
                  <form className="form-grid" onSubmit={(event) => {
                    event.preventDefault();
                    const data = Object.fromEntries(new FormData(event.currentTarget));
                    action(() => request("/attendance/mark", {
                      method: "POST",
                      body: {
                        employee_id: Number(data.employee_id),
                        date: data.date,
                        status: "ABSENT",
                      },
                    }), "Absence recorded.");
                  }}>
                    <Field label="Employee ID" name="employee_id"
                      type="number" min="1" required />
                    <Field label="Past absence date" name="date" type="date" required />
                    <button>Mark absent</button>
                  </form>
                )}
              </section>
              {table(
                ["Employee", "Date", "Check in", "Check out", "Hours", "Status"],
                (item) => (
                  <tr key={item.id}>
                    <td>{item.employee_id}</td><td>{item.date}</td>
                    <td>{item.check_in || "—"}</td><td>{item.check_out || "—"}</td>
                    <td>{item.working_hours}</td><td>{item.status}</td>
                  </tr>
                )
              )}
            </>
          )}

          {page === "Leaves" && (
            <>
              <section className="panel">
                <h2>Apply for leave</h2>
                <form className="form-grid" onSubmit={submitLeave}>
                  <label>Leave type
                    <select name="leave_type">
                      <option>SICK</option><option>CASUAL</option><option>PAID</option>
                    </select>
                  </label>
                  <Field label="Start date" name="start_date" type="date" required />
                  <Field label="End date" name="end_date" type="date" required />
                  <Field label="Reason" name="reason" minLength={3}
                    maxLength={2000} required />
                  <button>Submit request</button>
                </form>
              </section>
              {table(
                ["ID", "Employee", "Type", "Dates", "Reason", "Status", "Review"],
                (item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td><td>{item.employee_id}</td>
                    <td>{item.leave_type}</td>
                    <td>{item.start_date} → {item.end_date}</td>
                    <td>{item.reason}</td><td>{item.status}</td>
                    <td>
                      {manager && item.status === "PENDING"
                        ? ["APPROVED", "REJECTED"].map((status) => (
                          <button key={status} onClick={() => action(
                            () => request(`/leaves/${item.id}/status`, {
                              method: "PATCH", body: { status },
                            }),
                            `Leave ${status.toLowerCase()}.`
                          )}>
                            {status === "APPROVED" ? "Approve" : "Reject"}
                          </button>
                        ))
                        : "—"}
                    </td>
                  </tr>
                )
              )}
            </>
          )}

          {page === "Payroll" && (
            <>
              {manager && (
                <section className="panel">
                  <h2>Generate monthly payroll</h2>
                  <form className="form-grid" onSubmit={submitPayroll}>
                    <Field label="Employee ID" name="employee_id"
                      type="number" min="1" required />
                    <Field label="Month" name="month" type="month" required />
                    <Field label="Deductions" name="deductions" type="number"
                      min="0" step="0.01" defaultValue="0" required />
                    <Field label="Bonus" name="bonus" type="number"
                      min="0" step="0.01" defaultValue="0" required />
                    <button>Generate payroll</button>
                  </form>
                </section>
              )}
              {table(
                ["Employee", "Month", "Basic salary", "Deductions", "Bonus", "Net salary"],
                (item) => (
                  <tr key={item.id}>
                    <td>{item.employee_id}</td><td>{item.month}</td>
                    <td>{money(item.basic_salary)}</td>
                    <td>{money(item.deductions)}</td>
                    <td>{money(item.bonus)}</td>
                    <td>{money(item.net_salary)}</td>
                  </tr>
                )
              )}
            </>
          )}

          {page === "Notifications" && (
            <section className="panel">
              <button onClick={() => action(
                () => request("/notifications/read-all", { method: "PATCH" }),
                "All notifications marked as read."
              )}>Mark all as read</button>
              {!rows.length && <p>No notifications.</p>}
              {rows.map((item) => (
                <article className="notification" key={item.id}>
                  <h3>{item.title} {!item.is_read && " · New"}</h3>
                  <p>{item.message}</p>
                  {!item.is_read && (
                    <button onClick={() => action(
                      () => request(`/notifications/${item.id}/read`, {
                        method: "PATCH",
                      }),
                      "Notification marked as read."
                    )}>Mark as read</button>
                  )}
                </article>
              ))}
            </section>
          )}

          {page === "Users" && table(
            ["ID", "Username", "Email", "Role"],
            (item) => (
              <tr key={item.id}>
                <td>{item.id}</td><td>{item.username}</td><td>{item.email}</td>
                <td>
                  <select value={item.role} disabled={item.id === user.id}
                    onChange={(event) => {
                      const role = event.target.value;
                      action(
                        () => request(`/admin/users/${item.id}/role`, {
                          method: "PATCH", body: { role },
                        }),
                        "Role updated."
                      );
                    }}>
                    <option>EMPLOYEE</option>
                    <option>HR</option>
                    <option>ADMIN</option>
                  </select>
                </td>
              </tr>
            )
          )}
        </fieldset>
      </main>
    </div>
  );
}