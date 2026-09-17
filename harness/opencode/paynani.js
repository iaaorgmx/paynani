// The paynani plugin for OpenCode: the session side of the OpenCode runtime.
//
// The dispatcher cannot speak into OpenCode (harness/adapters/opencode.py says
// why), so it writes each event to state/opencode.spool and stops. This plugin
// runs inside the OpenCode process and closes the loop from there:
//
// 1. It claims the single-consumer lock. Two OpenCode processes reading one
//    spool and advancing one offset would repeat mail and corrupt the record of
//    what was handed over, so only the lock holder delivers.
// 2. It remembers the session a person is working in: the last root session
//    that received a user message. Subagent sessions have a parent and are
//    never a target.
// 3. When that session is idle, it asks `session_start.py --opencode-pending`
//    what is unread, sends the instruction with `client.session.promptAsync`,
//    and only after OpenCode accepted it runs `--opencode-ack` with the exact
//    byte offset it was given. A failed send is not acknowledged and is tried
//    again on the next pass: repeating an instruction is survivable, skipping
//    mail is not.
//
// The prompt carries event ids and a fixed instruction, never a mail body. The
// spool, offset and lock logic live in Python, where the rest of paynani's is
// tested; this file only moves answers between that and OpenCode.
//
// Nothing here may take OpenCode down. Every failure is caught and logged.

import { execFile, execFileSync } from "node:child_process"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..")
const SESSION_START = resolve(REPO, "harness", "session_start.py")
const SERVICE = "paynani"
const POLL_MS = 5000
const PYTHON_TIMEOUT_MS = 30000

function pythonBinary(env) {
  return (env.PAYNANI_PYTHON || "").trim() || "python3"
}

// `opencode run` is a one-shot command. Letting it take the lock would hand mail
// to a run that exits before anyone reads the answer, so the plugin stays out of
// it. PAYNANI_OPENCODE_DISABLE=1 turns the plugin off everywhere.
//
// A compiled Bun binary reports its own path as an argument ahead of the
// command, so leading arguments that are the program itself are skipped.
export function shouldRun(argv, env) {
  if ((env.PAYNANI_OPENCODE_DISABLE || "").trim() === "1") return false
  const positional = argv.slice(1).filter((arg) => arg && !arg.startsWith("-"))
  while (positional.length && (positional[0].includes("/") || positional[0] === "opencode")) {
    positional.shift()
  }
  return positional[0] !== "run"
}

export function runSessionStart(args, env = process.env) {
  return new Promise((resolvePromise) => {
    execFile(
      pythonBinary(env),
      [SESSION_START, ...args],
      { env, timeout: PYTHON_TIMEOUT_MS, maxBuffer: 1024 * 1024 },
      (error, stdout) => {
        if (error) return resolvePromise(null)
        const text = String(stdout || "").trim()
        if (!text) return resolvePromise(null)
        try {
          resolvePromise(JSON.parse(text))
        } catch {
          resolvePromise(null)
        }
      },
    )
  })
}

function sentOk(result) {
  if (!result) return true
  if (result.error) return false
  if (result.response && result.response.ok === false) return false
  return true
}

export function createPaynani({ client, run, pid, pollMs = POLL_MS, setTimer, clearTimer }) {
  const state = {
    target: null,
    children: new Set(),
    status: new Map(),
    owner: false,
    busy: false,
    toldSystem: false,
    disposed: false,
  }

  async function log(level, message) {
    try {
      await client.app.log({ body: { service: SERVICE, level, message } })
    } catch {
      // Logging is the last resort; there is nowhere left to report a failure.
    }
  }

  function idle(sessionID) {
    const status = state.status.get(sessionID)
    return status === undefined || status === "idle"
  }

  async function tick() {
    if (state.disposed || state.busy || !state.target) return
    if (!idle(state.target)) return
    state.busy = true
    try {
      const claim = await run(["--opencode-claim", String(pid)])
      state.owner = Boolean(claim && claim.owner)
      if (!state.owner) return
      const pending = await run(
        state.toldSystem ? ["--opencode-pending"] : ["--opencode-pending", "--status"],
      )
      if (!pending) return
      if (!state.toldSystem) {
        state.toldSystem = true
        if (pending.system) {
          await log("warn", pending.system)
          try {
            await client.tui.showToast({
              body: { title: "paynani", message: pending.system, variant: "warning" },
            })
          } catch {
            // A headless server has no TUI to show it in; the log still has it.
          }
        }
      }
      if (!pending.prompt) return
      const target = state.target
      let result
      try {
        result = await client.session.promptAsync({
          path: { id: target },
          body: { parts: [{ type: "text", text: pending.prompt }] },
        })
      } catch (error) {
        await log("error", `could not send ${pending.count} paynani event(s): ${error}`)
        return
      }
      if (!sentOk(result)) {
        await log("error", `OpenCode refused ${pending.count} paynani event(s); will retry`)
        return
      }
      state.status.set(target, "busy")
      const ack = await run(["--opencode-ack", String(pending.through)])
      if (!ack) {
        await log("warn", `sent paynani events but could not record offset ${pending.through}`)
        return
      }
      await log("info", `sent ${pending.count} paynani event(s) to session ${target}`)
    } catch (error) {
      await log("error", `paynani delivery failed: ${error}`)
    } finally {
      state.busy = false
    }
  }

  function observe(event) {
    if (!event || !event.type) return false
    const props = event.properties || {}
    if (event.type === "session.created" || event.type === "session.updated") {
      const info = props.info || {}
      if (info.id && info.parentID) state.children.add(info.id)
      return false
    }
    if (event.type === "session.status" && props.sessionID) {
      const type = props.status && props.status.type
      if (type) state.status.set(props.sessionID, type)
      return type === "idle" && props.sessionID === state.target
    }
    if (event.type === "session.idle" && props.sessionID) {
      state.status.set(props.sessionID, "idle")
      return props.sessionID === state.target
    }
    if (event.type === "session.deleted") {
      const info = props.info || {}
      if (info.id === state.target) state.target = null
      if (info.id) state.status.delete(info.id)
      return false
    }
    return false
  }

  const timer = setTimer ? setTimer(() => void tick(), pollMs) : null

  async function dispose() {
    if (state.disposed) return
    state.disposed = true
    if (timer && clearTimer) clearTimer(timer)
    if (state.owner) await run(["--opencode-release", String(pid)])
    state.owner = false
    await run(["--opencode-bye", String(pid)])
  }

  const hooks = {
    event: async ({ event }) => {
      try {
        if (observe(event)) await tick()
      } catch (error) {
        await log("error", `paynani event handling failed: ${error}`)
      }
    },
    "chat.message": async (input) => {
      const sessionID = input && input.sessionID
      if (sessionID && !state.children.has(sessionID)) state.target = sessionID
    },
    dispose,
  }

  return { hooks, tick, observe, dispose, state }
}

export const PaynaniPlugin = async ({ client }) => {
  if (!shouldRun(process.argv, process.env)) return {}
  const paynani = createPaynani({
    client,
    run: (args) => runSessionStart(args),
    pid: process.pid,
    setTimer: (fn, ms) => {
      const handle = setInterval(fn, ms)
      if (handle && typeof handle.unref === "function") handle.unref()
      return handle
    },
    clearTimer: (handle) => clearInterval(handle),
  })
  // Presence is separate from the lock: the lock waits for a session to deliver
  // to, and until then this is the only sign that OpenCode is open (#160). Not
  // awaited, so a slow Python start never delays OpenCode.
  void runSessionStart(["--opencode-hello", String(process.pid)])
  // dispose is not guaranteed on every way a terminal can close, so the lock and
  // the presence record are also removed on exit. Anything left behind anyway
  // belongs to a dead pid: the next plugin takes the lock over, and
  // healthcheck.py drops the stale presence record.
  process.once("exit", () => {
    const steps = paynani.state.owner ? ["--opencode-release", "--opencode-bye"] : ["--opencode-bye"]
    for (const step of steps) {
      try {
        execFileSync(pythonBinary(process.env), [SESSION_START, step, String(process.pid)], {
          timeout: 5000,
          stdio: "ignore",
        })
      } catch {
        // Nothing to do at exit; what is left belongs to a dead pid.
      }
    }
  })
  return paynani.hooks
}
