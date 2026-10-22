import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";

const API = (
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

const ROLES = ["EMPLOYEE", "HR", "ADMIN"];
const LEAVE_TYPES = ["SICK", "CASUAL", "PAID"];

const money = (value) =>
  Number(value || 0).toLocaleString("en-IN", {
    style: "currency",
    currency: "INR",
  });

function indiaDate() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function dateTime(value) {
  if (!value) return "—";

  // SQLite can return UTC timestamps without an explicit offset.
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
    ? value
    : `${value}Z`;

  const parsed = new Date(normalized);

  if (Number.isNaN(parsed.getTime())) return value;

  return parsed.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function Field({ label, ...props }) {
  return (
    <label>
      <span>{label}</span>
      <input {...props} />
    </label>
  );
}

function SelectField({ label, values, ...props }) {
  return (
    <label>
      <span>{label}</span>
      <select {...props}>
        {values.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
    </label>
  );
}

function Badge({ children }) {
  return <span className="badge">{children}</span>;
}

function DataTable({ headers, rows, render, loading = false }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header}>{header}</th>
            ))}
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

function ProfileDetails({ employee }) {
  return (
    <section className="panel">
      <h2>{employee.full_name}</h2>
      <div className="stat-row">
        <span>Employee ID</span>
        <strong>{employee.id}</strong>
      </div>
      <div className="stat-row">
        <span>Designation</span>
        <strong>{employee.designation}</strong>
      </div>
      <div className="stat-row">
        <span>Department</span>
        <strong>{employee.department}</strong>
      </div>
      <div className="stat-row">
        <span>Joining date</span>
        <strong>{employee.joining_date}</strong>
      </div>
      <div className="stat-row">
        <span>Basic monthly salary</span>
        <strong>{money(employee.salary)}</strong>
      </div>
      <div className="stat-row">
        <span>Status</span>
        <Badge>{employee.status}</Badge>
      </div>
    </section>
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
  const [balances, setBalances] = useState([]);
  const [policies, setPolicies] = useState([]);
  const [summary, setSummary] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [version, setVersion] = useState(0);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(null);
  const [unread, setUnread] = useState(0);
  const [month, setMonth] = useState(() => indiaDate().slice(0, 7));
  const [payslip, setPayslip] = useState(null);

  const actionRunning = useRef(false);

  const manager = ["ADMIN", "HR"].includes(user?.role);
  const admin = user?.role === "ADMIN";

  const logout = useCallback(() => {
    sessionStorage.removeItem("worksphere_token");
    setToken("");
    setUser(null);
    setRows([]);
    setBalances([]);
    setPolicies([]);
    setSummary(null);
    setUnread(0);
    setPage("Dashboard");
    setEditing(null);
    setPayslip(null);
    setMessage("");
  }, []);

  const request = useCallback(
    async (path, options = {}) => {
      const headers = { ...options.headers };

      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }

      let body = options.body;

      if (body !== undefined && typeof body !== "string") {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(body);
      }

      const controller = new AbortController();
      const timeout = window.setTimeout(
        () => controller.abort(),
        20000
      );

      let response;

      try {
        response = await fetch(`${API}${path}`, {
          ...options,
          headers,
          body,
          signal: controller.signal,
        });
      } catch (error) {
        if (error.name === "AbortError") {
          throw new Error(
            "Request timed out. Refresh to check whether the action completed."
          );
        }

        throw new Error(
          `Backend connect avvatledu. ${API} running undho check cheyyi.`
        );
      } finally {
        window.clearTimeout(timeout);
      }

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        const detail = data?.detail;
        const errorText = Array.isArray(detail)
          ? detail
              .map((item) => {
                const field = item.loc?.slice(1).join(".");
                return `${field ? `${field}: ` : ""}${item.msg}`;
              })
              .join("; ")
          : typeof detail === "string"
            ? detail
            : "Request failed";

        if (
          token &&
          (response.status === 401 ||
            (response.status === 403 &&
              errorText.toLowerCase().includes("deactivated")))
        ) {
          logout();
        }

        const error = new Error(errorText);
        error.status = response.status;
        throw error;
      }

      return data;
    },
    [token, logout]
  );

  async function action(work, success) {
    if (actionRunning.current) return;

    actionRunning.current = true;
    setBusy(true);
    setMessage("");

    try {
      await work();
      setMessage(success);
      setVersion((value) => value + 1);
    } catch (error) {
      setMessage(error.message);
    } finally {
      actionRunning.current = false;
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
  }, [token, request]);

  useEffect(() => {
    if (!user) return;

    let active = true;
    setLoading(true);
    setRows([]);
    setBalances([]);
    setPolicies([]);
    setSummary(null);

    async function load() {
      try {
        if (page === "Dashboard") {
          const path = admin
            ? "/analytics/summary"
            : manager
              ? "/dashboard/hr"
              : "/dashboard/employee";

          const data = await request(path);
          if (active) setSummary(data);
        } else if (page === "Profile") {
          const data = await request("/employees/me");
          if (active) setSummary(data);
        } else if (page === "Leaves") {
          const [leaveRows, balanceRows, policyRows] = await Promise.all([
            request("/leaves"),
            request("/leave-balances"),
            request("/leave-policies"),
          ]);

          if (active) {
            setRows(leaveRows);
            setBalances(balanceRows);
            setPolicies(policyRows);
          }
        } else if (page === "Policies") {
          const data = await request("/leave-policies");
          if (active) setRows(data);
        } else if (page === "Payroll") {
          const query = month
            ? `?month=${encodeURIComponent(month)}`
            : "";

          const [payrollRows, monthlySummary] = await Promise.all([
            request(`/payroll${query}`),
            month
              ? request(
                  `/payroll/summary?month=${encodeURIComponent(month)}`
                )
              : Promise.resolve(null),
          ]);

          if (active) {
            setRows(payrollRows);
            setSummary(monthlySummary);
          }
        } else {
          const paths = {
            Employees: `/employees?search=${encodeURIComponent(search)}`,
            Attendance: "/attendance",
            Notifications: "/notifications",
            Users: "/admin/users",
          };

          const data = await request(paths[page]);
          if (active) setRows(data);
        }
      } catch (error) {
        if (active) {
          const missingProfile =
            error.status === 404 &&
            (page === "Profile" ||
              (page === "Dashboard" && !manager));

          setMessage(
            missingProfile
              ? "Employee profile inka create kaaledu. HR/Admin ni contact cheyyi."
              : error.message
          );
        }
      } finally {
        if (active) setLoading(false);
      }

      try {
        const data = await request("/notifications/unread-count");
        if (active) setUnread(data.unread_count);
      } catch {
        // Keep the previous count if notification refresh fails.
      }
    }

    load();

    return () => {
      active = false;
    };
  }, [
    user,
    page,
    version,
    search,
    month,
    request,
    manager,
    admin,
  ]);

  function navigate(next) {
    setPage(next);
    setMessage("");
    setEditing(null);
    setPayslip(null);
    setSearch("");
  }

  async function authenticate(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const creating = register;

    await action(async () => {
      if (creating) {
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

        sessionStorage.setItem(
          "worksphere_token",
          data.access_token
        );

        setPage("Dashboard");
        setToken(data.access_token);
      }
    }, creating ? "Account created. Please log in." : "Logged in.");
  }

  function submitEmployee(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));

    if (!editing) data.user_id = Number(data.user_id);

    action(async () => {
      await request(
        editing ? `/employees/${editing.id}` : "/employees",
        {
          method: editing ? "PATCH" : "POST",
          body: data,
        }
      );

      setEditing(null);
      form.reset();
    }, "Employee saved.");
  }

  function submitLeave(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));

    if (data.end_date < data.start_date) {
      setMessage("End date must be on or after start date.");
      return;
    }

    action(async () => {
      await request("/leaves", {
        method: "POST",
        body: data,
      });
      form.reset();
    }, "Leave request submitted.");
  }

  function submitPolicy(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    const data = {
      total_days_allowed: Number(values.total_days_allowed),
    };

    if (!editing) data.leave_type = values.leave_type;

    action(async () => {
      await request(
        editing ? `/leave-policies/${editing.id}` : "/leave-policies",
        {
          method: editing ? "PATCH" : "POST",
          body: data,
        }
      );

      setEditing(null);
      form.reset();
    }, "Leave policy and balances updated.");
  }

  function submitPayroll(event) {
    event.preventDefault();

    const data = Object.fromEntries(
      new FormData(event.currentTarget)
    );
    data.employee_id = Number(data.employee_id);

    action(async () => {
      await request("/payroll", {
        method: "POST",
        body: data,
      });

      setMonth(data.month);
    }, "Payroll generated.");
  }

  function submitUser(event) {
    event.preventDefault();

    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));

    data.is_active = data.is_active === "true";

    if (editing && !data.password) {
      delete data.password;
    }

    // Disabled self-role/status controls are not included in FormData.
    if (editing?.id === user.id) {
      delete data.role;
      delete data.is_active;
    }

    action(async () => {
      const saved = await request(
        editing ? `/admin/users/${editing.id}` : "/admin/users",
        {
          method: editing ? "PATCH" : "POST",
          body: data,
        }
      );

      if (saved.id === user.id) setUser(saved);

      setEditing(null);
      form.reset();
    }, "User saved.");
  }

  const table = (headers, render, data = rows) => (
    <DataTable
      headers={headers}
      rows={data}
      render={render}
      loading={loading}
    />
  );

  if (!token) {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <div className="brand">W / WorkSphere</div>
          <h1>{register ? "Create your account" : "Welcome back"}</h1>
          <p>Your people. Your workplace. One connected space.</p>

          {message && (
            <div className="notice" role="status">
              {message}
            </div>
          )}

          <form onSubmit={authenticate}>
            <Field
              label="Username"
              name="username"
              required
              minLength={3}
              maxLength={50}
              pattern="[a-zA-Z0-9_]+"
              autoComplete="username"
            />

            {register && (
              <Field
                label="Email"
                name="email"
                type="email"
                required
                autoComplete="email"
              />
            )}

            <Field
              label="Password"
              name="password"
              type="password"
              required
              minLength={8}
              maxLength={128}
              autoComplete={
                register ? "new-password" : "current-password"
              }
            />

            <button disabled={busy}>
              {busy
                ? "Please wait..."
                : register
                  ? "Register"
                  : "Log in"}
            </button>
          </form>

          <button
            className="secondary"
            disabled={busy}
            onClick={() => {
              setRegister((value) => !value);
              setMessage("");
            }}
          >
            {register
              ? "Already registered? Log in"
              : "Create employee account"}
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
    "Profile",
    ...(manager ? ["Employees"] : []),
    "Attendance",
    "Leaves",
    "Policies",
    "Payroll",
    "Notifications",
    ...(admin ? ["Users"] : []),
  ];

  return (
    <div className="app-layout">
      <aside>
        <div className="brand">W / WorkSphere</div>
        <p className="sidebar-caption">WORKSPACE</p>

        <nav>
          {pages.map((item) => (
            <button
              key={item}
              className={page === item ? "active" : ""}
              aria-current={page === item ? "page" : undefined}
              disabled={busy}
              onClick={() => navigate(item)}
            >
              {item}
            </button>
          ))}
        </nav>

        <div className="account">
          <strong>{user.username}</strong>
          <small>{user.role}</small>
          <button disabled={busy} onClick={logout}>
            Log out
          </button>
        </div>
      </aside>

      <main className="workspace">
        <header>
          <div>
            <p className="eyebrow">WORKSPHERE / {user.role}</p>
            <h1>{page}</h1>
          </div>

          <div className="actions">
            <button
              className="secondary"
              disabled={busy || loading}
              onClick={() => {
                setMessage("");
                setVersion((value) => value + 1);
              }}
            >
              Refresh
            </button>

            <button
              className="secondary"
              disabled={busy}
              onClick={() => navigate("Notifications")}
            >
              Notifications · {unread}
            </button>
          </div>
        </header>

        {message && (
          <div className="notice" role="status">
            {message}
          </div>
        )}

        {loading && <p role="status">Loading...</p>}

        <fieldset
          disabled={busy || loading}
          className="content-fieldset"
        >
          {page === "Dashboard" && summary && (
            admin ? (
              <>
                <div className="kpi-grid">
                  {[
                    ["Total users", summary.total_users],
                    ["Total employees", summary.total_employees],
                    ["Active employees", summary.active_employees],
                    ["Present today", summary.attendance_today.PRESENT],
                    ["Late today", summary.attendance_today.late],
                    ["Pending leaves", summary.leave_statistics.PENDING],
                    [
                      "Monthly payroll",
                      money(summary.payroll_overview.net_salary),
                    ],
                    [
                      "Attendance not marked",
                      summary.attendance_today.not_marked,
                    ],
                  ].map(([label, value]) => (
                    <article className="kpi" key={label}>
                      <span>{label}</span>
                      <strong>{value}</strong>
                    </article>
                  ))}
                </div>

                <section className="panel">
                  <h2>Employees by department</h2>
                  {!summary.employees_by_department.length && (
                    <p>No employees yet.</p>
                  )}
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
                        Present {item.PRESENT} · Half day {item.HALF_DAY}
                        {" · "}Absent {item.ABSENT} · Late {item.late}
                      </span>
                    </div>
                  ))}
                </section>
              </>
            ) : manager ? (
              <section className="panel">
                <h2>{summary.message}</h2>
                <p>
                  Manage employees, review attendance and leave requests,
                  configure policies, and generate payroll.
                </p>
                <div className="actions">
                  {["Employees", "Attendance", "Leaves", "Policies", "Payroll"]
                    .map((item) => (
                      <button key={item} onClick={() => navigate(item)}>
                        {item}
                      </button>
                    ))}
                </div>
              </section>
            ) : (
              <>
                <ProfileDetails employee={summary.employee} />
                <div className="kpi-grid">
                  <article className="kpi">
                    <span>Today's attendance</span>
                    <strong>
                      {summary.attendance_today
                        ? summary.attendance_today.check_out
                          ? summary.attendance_today.status
                          : "Checked in"
                        : "Not marked"}
                    </strong>
                  </article>
                  <article className="kpi">
                    <span>Pending leave requests</span>
                    <strong>{summary.pending_leaves}</strong>
                  </article>
                  <article className="kpi">
                    <span>Latest net salary</span>
                    <strong>
                      {summary.latest_payroll
                        ? money(summary.latest_payroll.net_salary)
                        : "Not available"}
                    </strong>
                  </article>
                </div>
                <section className="panel">
                  <h2>My leave balances</h2>
                  {!summary.leave_balances.length && (
                    <p>Leave policies have not been assigned yet.</p>
                  )}
                  {summary.leave_balances.map((item) => (
                    <div className="stat-row" key={item.id}>
                      <span>{item.leave_type}</span>
                      <strong>{item.remaining_days} days</strong>
                    </div>
                  ))}
                </section>
              </>
            )
          )}

          {page === "Profile" && summary && (
            <ProfileDetails employee={summary} />
          )}

          {page === "Employees" && manager && (
            <>
              <section className="panel">
                <h2>{editing ? "Edit employee" : "Add employee"}</h2>
                <form
                  className="form-grid"
                  onSubmit={submitEmployee}
                  key={editing?.id || "new-employee"}
                >
                  {!editing && (
                    <Field
                      label="Registered user ID"
                      name="user_id"
                      type="number"
                      min="1"
                      step="1"
                      required
                    />
                  )}
                  <Field
                    label="Full name"
                    name="full_name"
                    maxLength={150}
                    required
                    defaultValue={editing?.full_name}
                  />
                  <Field
                    label="Designation"
                    name="designation"
                    maxLength={100}
                    required
                    defaultValue={editing?.designation}
                  />
                  <Field
                    label="Department"
                    name="department"
                    maxLength={100}
                    required
                    defaultValue={editing?.department}
                  />
                  <Field
                    label="Joining date"
                    name="joining_date"
                    type="date"
                    required
                    defaultValue={editing?.joining_date}
                  />
                  <Field
                    label="Monthly basic salary"
                    name="salary"
                    type="number"
                    min="0"
                    step="0.01"
                    required
                    defaultValue={editing?.salary}
                  />
                  <SelectField
                    label="Status"
                    name="status"
                    values={["ACTIVE", "INACTIVE"]}
                    defaultValue={editing?.status || "ACTIVE"}
                  />
                  <button>Save employee</button>
                  {editing && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setEditing(null)}
                    >
                      Cancel
                    </button>
                  )}
                </form>
              </section>

              <Field
                label="Search name, designation or department"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />

              {table(
                ["ID", "Name", "Department", "Designation", "Salary", "Status", "Action"],
                (item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td>
                    <td>{item.full_name}</td>
                    <td>{item.department}</td>
                    <td>{item.designation}</td>
                    <td>{money(item.salary)}</td>
                    <td><Badge>{item.status}</Badge></td>
                    <td>
                      <button onClick={() => setEditing(item)}>Edit</button>
                    </td>
                  </tr>
                )
              )}
            </>
          )}

          {page === "Attendance" && (
            <>
              <section className="panel">
                <h2>Track your working day</h2>
                <p>
                  Check-in requires an active employee profile.
                  Eight hours or more counts as present after checkout.
                  Times are shown in IST.
                </p>
                <div className="actions">
                  <button
                    onClick={() => action(
                      () => request("/attendance/check-in", { method: "POST" }),
                      "Checked in. Your attendance and late status are shown below."
                    )}
                  >
                    Check in
                  </button>
                  <button
                    onClick={() => action(
                      () => request("/attendance/check-out", { method: "POST" }),
                      "Checked out."
                    )}
                  >
                    Check out
                  </button>
                </div>
              </section>

              {manager && (
                <section className="panel">
                  <h2>Attendance controls</h2>
                  <form
                    className="form-grid"
                    onSubmit={(event) => {
                      event.preventDefault();
                      const data = Object.fromEntries(
                        new FormData(event.currentTarget)
                      );
                      action(
                        () => request("/attendance/mark", {
                          method: "POST",
                          body: {
                            employee_id: Number(data.employee_id),
                            date: data.date,
                            status: "ABSENT",
                          },
                        }),
                        "Absence recorded."
                      );
                    }}
                  >
                    <Field
                      label="Employee ID"
                      name="employee_id"
                      type="number"
                      min="1"
                      required
                    />
                    <Field
                      label="Past absence date"
                      name="date"
                      type="date"
                      required
                    />
                    <button>Mark absent</button>
                  </form>

                  <form
                    className="form-grid"
                    onSubmit={(event) => {
                      event.preventDefault();
                      const day = new FormData(event.currentTarget).get("day");
                      action(async () => {
                        await request(
                          `/attendance/reconcile?day=${encodeURIComponent(day)}`,
                          { method: "POST" }
                        );
                      }, "Missing attendance reconciled for the selected date.");
                    }}
                  >
                    <Field
                      label="Past date to reconcile"
                      name="day"
                      type="date"
                      required
                    />
                    <button>Reconcile missing attendance</button>
                  </form>
                  <p>
                    Approved leave and configured non-working days are skipped.
                  </p>
                </section>
              )}

              {table(
                ["Employee", "Date", "Check in", "Check out", "Hours", "Overtime", "Arrival", "Status"],
                (item) => (
                  <tr key={item.id}>
                    <td>{item.employee_id}</td>
                    <td>{item.date}</td>
                    <td>{dateTime(item.check_in)}</td>
                    <td>{dateTime(item.check_out)}</td>
                    <td>{item.working_hours}</td>
                    <td>{item.overtime_hours}</td>
                    <td>
                      {!item.check_in
                        ? "—"
                        : item.is_late
                          ? `Late · ${item.late_minutes} min`
                          : "On-time"}
                    </td>
                    <td>
                      <Badge>
                        {item.check_in && !item.check_out
                          ? "CHECKED IN"
                          : item.status}
                      </Badge>
                    </td>
                  </tr>
                )
              )}
            </>
          )}

          {page === "Leaves" && (
            <>
              <section className="panel">
                <h2>{manager ? "Employee leave balances" : "My leave balances"}</h2>
                <p>
                  Balance is deducted on approval. Pending requests also limit
                  how many additional days you can request.
                </p>
                {table(
                  ["Employee", "Type", "Remaining days"],
                  (item) => (
                    <tr key={item.id}>
                      <td>{item.employee_id}</td>
                      <td>{item.leave_type}</td>
                      <td>{item.remaining_days}</td>
                    </tr>
                  ),
                  balances
                )}
              </section>

              <section className="panel">
                <h2>Apply for leave</h2>
                <p>
                  Requests apply to your own employee profile.
                  Calendar days, including the start and end dates, are counted.
                </p>
                {!policies.length ? (
                  <p>HR/Admin must create leave policies first.</p>
                ) : (
                  <form className="form-grid" onSubmit={submitLeave}>
                    <SelectField
                      label="Leave type"
                      name="leave_type"
                      values={policies.map((item) => item.leave_type)}
                    />
                    <Field
                      label="Start date"
                      name="start_date"
                      type="date"
                      min={indiaDate()}
                      required
                    />
                    <Field
                      label="End date"
                      name="end_date"
                      type="date"
                      min={indiaDate()}
                      required
                    />
                    <Field
                      label="Reason"
                      name="reason"
                      minLength={3}
                      maxLength={2000}
                      required
                    />
                    <button>Submit request</button>
                  </form>
                )}
              </section>

              {table(
                ["ID", "Employee", "Type", "Dates", "Reason", "Status", "Review"],
                (item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td>
                    <td>{item.employee_id}</td>
                    <td>{item.leave_type}</td>
                    <td>{item.start_date} → {item.end_date}</td>
                    <td>{item.reason}</td>
                    <td><Badge>{item.status}</Badge></td>
                    <td>
                      {manager && item.status === "PENDING"
                        ? ["APPROVED", "REJECTED"].map((status) => (
                            <button
                              key={status}
                              onClick={() => action(
                                () => request(`/leaves/${item.id}/status`, {
                                  method: "PATCH",
                                  body: { status },
                                }),
                                `Leave ${status.toLowerCase()}.`
                              )}
                            >
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

          {page === "Policies" && (
            <>
              <section className="panel">
                <h2>Leave policy overview</h2>
                <p>
                  Full-day leave is supported. These balances do not reset
                  automatically each year.
                </p>
              </section>

              {manager && (
                <section className="panel">
                  <h2>{editing ? `Edit ${editing.leave_type} policy` : "Create policy"}</h2>
                  <form
                    className="form-grid"
                    onSubmit={submitPolicy}
                    key={editing?.id || "new-policy"}
                  >
                    {!editing && (
                      <SelectField
                        label="Leave type"
                        name="leave_type"
                        values={LEAVE_TYPES}
                      />
                    )}
                    <Field
                      label="Total days allowed"
                      name="total_days_allowed"
                      type="number"
                      min="0"
                      max="366"
                      step="1"
                      required
                      defaultValue={editing?.total_days_allowed}
                    />
                    <button>Save policy</button>
                    {editing && (
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => setEditing(null)}
                      >
                        Cancel
                      </button>
                    )}
                  </form>
                </section>
              )}

              {table(
                ["Type", "Total days allowed", "Action"],
                (item) => (
                  <tr key={item.id}>
                    <td>{item.leave_type}</td>
                    <td>{item.total_days_allowed}</td>
                    <td>
                      {manager
                        ? <button onClick={() => setEditing(item)}>Edit</button>
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
                    <Field
                      label="Employee ID"
                      name="employee_id"
                      type="number"
                      min="1"
                      required
                    />
                    <Field
                      label="Month"
                      name="month"
                      type="month"
                      required
                      defaultValue={indiaDate().slice(0, 7)}
                    />
                    {[
                      ["Allowances", "allowances"],
                      ["Deductions", "deductions"],
                      ["Bonus", "bonus"],
                    ].map(([label, name]) => (
                      <Field
                        key={name}
                        label={label}
                        name={name}
                        type="number"
                        min="0"
                        step="0.01"
                        defaultValue="0"
                        required
                      />
                    ))}
                    <button>Generate payroll</button>
                  </form>
                </section>
              )}

              <section className="panel">
                <h2>Payroll history</h2>
                <Field
                  label="Filter month — clear to view all"
                  type="month"
                  value={month}
                  onChange={(event) => {
                    setMonth(event.target.value);
                    setPayslip(null);
                  }}
                />
                <button
                  className="secondary"
                  onClick={() => {
                    setMonth("");
                    setPayslip(null);
                  }}
                >
                  View all months
                </button>
              </section>

              {summary && (
                <div className="kpi-grid">
                  {[
                    ["Payslips", summary.employee_count],
                    ["Basic", money(summary.total_basic_salary)],
                    ["Allowances", money(summary.total_allowances)],
                    ["Bonus", money(summary.total_bonus)],
                    ["Deductions", money(summary.total_deductions)],
                    ["Net salary", money(summary.total_net_salary)],
                  ].map(([label, value]) => (
                    <article className="kpi" key={label}>
                      <span>{label}</span>
                      <strong>{value}</strong>
                    </article>
                  ))}
                </div>
              )}

              {table(
                ["Employee", "Month", "Basic", "Allowances", "Deductions", "Bonus", "Net", "Payslip"],
                (item) => (
                  <tr key={item.id}>
                    <td>{item.employee_id}</td>
                    <td>{item.month}</td>
                    <td>{money(item.basic_salary)}</td>
                    <td>{money(item.allowances)}</td>
                    <td>{money(item.deductions)}</td>
                    <td>{money(item.bonus)}</td>
                    <td>{money(item.net_salary)}</td>
                    <td>
                      <button onClick={() => setPayslip(item)}>View</button>
                    </td>
                  </tr>
                )
              )}

              {payslip && (
                <section className="panel">
                  <h2>Payslip · {payslip.month}</h2>
                  <p>
                    Employee #{payslip.employee_id} · Payslip #{payslip.id}
                  </p>
                  {[
                    ["Basic salary", payslip.basic_salary],
                    ["Allowances", payslip.allowances],
                    ["Bonus", payslip.bonus],
                    ["Deductions", payslip.deductions],
                    ["Net salary", payslip.net_salary],
                  ].map(([label, value]) => (
                    <div className="stat-row" key={label}>
                      <span>{label}</span>
                      <strong>{money(value)}</strong>
                    </div>
                  ))}
                  <p>Generated: {dateTime(payslip.created_at)}</p>
                  <button
                    className="secondary"
                    onClick={() => setPayslip(null)}
                  >
                    Close payslip
                  </button>
                </section>
              )}
            </>
          )}

          {page === "Notifications" && (
            <section className="panel">
              <button
                onClick={() => action(
                  () => request("/notifications/read-all", { method: "PATCH" }),
                  "All notifications marked as read."
                )}
              >
                Mark all as read
              </button>
              {!rows.length && <p>No notifications.</p>}

              {rows.map((item) => (
                <article className="notification" key={item.id}>
                  <h3>{item.title}{!item.is_read && " · New"}</h3>
                  <p>{item.message}</p>
                  <small>{dateTime(item.created_at)}</small>
                  {!item.is_read && (
                    <button
                      onClick={() => action(
                        () => request(`/notifications/${item.id}/read`, {
                          method: "PATCH",
                        }),
                        "Notification marked as read."
                      )}
                    >
                      Mark as read
                    </button>
                  )}
                </article>
              ))}
            </section>
          )}

          {page === "Users" && admin && (
            <>
              <section className="panel">
                <h2>{editing ? "Edit user" : "Create user"}</h2>
                <form
                  className="form-grid"
                  onSubmit={submitUser}
                  key={editing?.id || "new-user"}
                >
                  <Field
                    label="Username"
                    name="username"
                    minLength={3}
                    maxLength={50}
                    pattern="[a-zA-Z0-9_]+"
                    required
                    defaultValue={editing?.username}
                  />
                  <Field
                    label="Email"
                    name="email"
                    type="email"
                    required
                    defaultValue={editing?.email}
                  />
                  <Field
                    label={
                      editing
                        ? "New password — leave blank to keep current"
                        : "Password"
                    }
                    name="password"
                    type="password"
                    minLength={8}
                    maxLength={128}
                    required={!editing}
                    autoComplete="new-password"
                  />
                  <SelectField
                    label="Role"
                    name="role"
                    values={ROLES}
                    defaultValue={editing?.role || "EMPLOYEE"}
                    disabled={editing?.id === user.id}
                  />
                  <label>
                    <span>Account status</span>
                    <select
                      name="is_active"
                      defaultValue={String(editing?.is_active ?? true)}
                      disabled={editing?.id === user.id}
                    >
                      <option value="true">ACTIVE</option>
                      <option value="false">INACTIVE</option>
                    </select>
                  </label>
                  <button>Save user</button>
                  {editing && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setEditing(null)}
                    >
                      Cancel
                    </button>
                  )}
                </form>
                <p>
                  Users linked to employee records must be deactivated
                  instead of deleted, to preserve HR history.
                </p>
              </section>

              {table(
                ["ID", "Username", "Email", "Role", "Status", "Actions"],
                (item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td>
                    <td>{item.username}</td>
                    <td>{item.email}</td>
                    <td>
                      <select
                        aria-label={`Role for ${item.username}`}
                        value={item.role}
                        disabled={item.id === user.id}
                        onChange={(event) => {
                          const role = event.target.value;
                          action(
                            () => request(`/admin/users/${item.id}/role`, {
                              method: "PATCH",
                              body: { role },
                            }),
                            "Role updated. The user must log in again."
                          );
                        }}
                      >
                        {ROLES.map((role) => (
                          <option key={role}>{role}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <Badge>{item.is_active ? "ACTIVE" : "INACTIVE"}</Badge>
                    </td>
                    <td>
                      <div className="actions">
                        <button onClick={() => setEditing(item)}>Edit</button>
                        <button
                          disabled={item.id === user.id}
                          onClick={() => action(
                            () => request(`/admin/users/${item.id}/status`, {
                              method: "PATCH",
                              body: { is_active: !item.is_active },
                            }),
                            item.is_active
                              ? "User deactivated."
                              : "User activated."
                          )}
                        >
                          {item.is_active ? "Deactivate" : "Activate"}
                        </button>
                        <button
                          disabled={item.id === user.id}
                          onClick={() => {
                            if (!window.confirm(
                              `Delete user "${item.username}"? This cannot be undone.`
                            )) return;

                            action(async () => {
                              await request(`/admin/users/${item.id}`, {
                                method: "DELETE",
                              });
                              if (editing?.id === item.id) setEditing(null);
                            }, "User deleted.");
                          }}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              )}
            </>
          )}
        </fieldset>
      </main>
    </div>
  );
}